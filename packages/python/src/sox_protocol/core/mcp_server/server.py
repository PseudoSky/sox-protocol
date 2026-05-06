# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol MCP server.

Entry point for the long-lived MCP server process.  Reads configuration
from environment variables, validates tool schemas against the spec at
startup (fail-fast on drift), starts the background listener task, and
registers the four SOX tools with FastMCP.

Configuration
-------------
``SOX_BACKING_STORE``
    URI of the backing store.  Supported schemes:

    - ``sqlite://<absolute-path>`` or ``sqlite:///<absolute-path>`` —
      persistent SQLite database at *<path>*.
    - ``sqlite://:memory:`` — in-process ephemeral SQLite (testing only).
    - ``memory://`` — pure in-memory store (testing only; no durability).
    - ``file://<absolute-path>`` — filesystem-backed store rooted at *<path>*.

    Defaults to ``memory://`` if not set (convenient for interactive
    development; not suitable for production).

``SOX_AGENT_ID``
    Non-empty string identifier for this agent.  MUST be set.

``SOX_MCP_TRANSPORT``
    ``stdio`` (default) or ``http``.  Selects the FastMCP transport.

``SOX_HTTP_HOST`` / ``SOX_HTTP_PORT``
    Bind address / port for the HTTP transport (default ``127.0.0.1`` /
    ``8000``).

Schema validation
-----------------
At startup (inside the lifespan context manager, before the first tool
call is served) the server validates the Python tool output shapes
against the corresponding ``spec/schemas/tools/*.schema.json`` files
using the ``jsonschema`` library.  If any schema fails to load or
validate, the process exits with a non-zero status rather than serving
potentially non-conformant responses.

This module MUST NOT import from ``sox_protocol.adapters`` (import-linter
enforced).  The adapter is instantiated dynamically by string dispatch in
``_build_store()``.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import jsonschema
from fastmcp import FastMCP

from sox_protocol.core.identity import AuditLogWriter, InMemoryCredentialRegistry
from sox_protocol.core.identity.keys import generate_keypair
from sox_protocol.core.identity.verifier import IdentityVerifier
from sox_protocol.core.mcp_server.listener import Listener
from sox_protocol.core.mcp_server.tools import register_tools
from sox_protocol.core.middleware import build_default_pipeline, extend_pipeline_with_registry
from sox_protocol.core.middleware.errors import PluginStartupError
from sox_protocol.core.middleware.registry import register_middleware
from sox_protocol.core.ports.backing_store import BackingStore

# Host protocol version — used for plugin compatibility checks.
# Kept here (not in a shared version module) because no such module exists;
# both bootstraps hard-code it from this same constant pattern.
_HOST_PROTOCOL_VERSION = "1.0.0"

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Spec schema root.  Two resolution paths:
#
#  1. Installed wheel: ``spec/`` is bundled inside the ``sox_protocol``
#     package via the symlink at ``packages/python/src/sox_protocol/spec ->
#     ../../../spec`` followed by hatchling at build time. We resolve
#     ``spec/schemas/tools/`` inside the installed package via
#     ``importlib.resources``.
#
#  2. Editable / source checkout: ``spec/`` lives at the repo root. Walk up
#     from this file until we find a directory containing ``spec/schemas/tools``.
#
# The previous implementation (``Path(__file__).resolve().parents[6]``) only
# worked in source checkouts because in an installed wheel ``parents[6]`` lands
# at the Python prefix (e.g. ``/opt/homebrew/Caskroom/miniconda/base/``)
# instead of the package root, producing a path like
# ``<prefix>/spec/schemas/tools`` that has never existed. Reproduced as a
# BrokenPipe at the TUI client because the server crashed at module import.
# ---------------------------------------------------------------------------


def _resolve_spec_schemas_dir() -> Path:
    """Return the absolute path to ``spec/schemas/tools/`` for both install modes."""
    # 1. Installed wheel: bundled at sox_protocol/spec/schemas/tools/
    try:
        pkg_ref = importlib.resources.files("sox_protocol")
        candidate = Path(str(pkg_ref)) / "spec" / "schemas" / "tools"
        if candidate.is_dir():
            return candidate
    except (FileNotFoundError, TypeError, ModuleNotFoundError):  # pragma: no cover
        pass

    # 2. Source checkout: walk up to find the repo's spec/ directory.
    here = Path(__file__).resolve()
    for ancestor in [here, *here.parents]:
        candidate = ancestor / "spec" / "schemas" / "tools"
        if candidate.is_dir():
            return candidate

    # 3. Fallback — return the (broken) path so the downstream is_dir check
    #    fires its existing error message rather than a confusing exception.
    return here.parents[6] / "spec" / "schemas" / "tools"


_SPEC_SCHEMAS_DIR: Path = _resolve_spec_schemas_dir()

# ---------------------------------------------------------------------------
# Canonical sample outputs used to smoke-test schema loading.
# Each dict must be valid against the corresponding *.output.schema.json.
# ---------------------------------------------------------------------------
_SCHEMA_SMOKE_SAMPLES: dict[str, dict[str, object]] = {
    "send.output.schema.json": {
        "sent_at": 1_714_300_000.0,
        "message_id": "1",
        "seq": 1,
        "backpressure": {"queue_depth": 0, "threshold": 1000, "state": "ok"},
    },
    "recv.output.schema.json": {
        "drained_at": 1_714_300_000.0,
        "messages": [],
    },
    "subscribe.output.schema.json": {
        "subscribed": [],
    },
    "list-channels.output.schema.json": {
        "channels": [],
        "_sox_protocol": {
            "server_version": "1.0",
            "supported_versions": ["1.0"],
            "min_client_version": "1.0",
        },
    },
}


def _load_and_validate_schemas() -> None:
    """Load every output schema from ``spec/`` and validate smoke samples.

    Raises:
        SystemExit: If any schema file is missing or any smoke sample fails
            validation.  The failure message is logged to stderr so CI picks
            it up.
    """
    if not _SPEC_SCHEMAS_DIR.is_dir():
        _log.error(
            "spec/schemas/tools/ not found at %s — "
            "is the repo checkout complete?",
            _SPEC_SCHEMAS_DIR,
        )
        sys.exit(1)

    for schema_filename, sample in _SCHEMA_SMOKE_SAMPLES.items():
        schema_path = _SPEC_SCHEMAS_DIR / schema_filename
        if not schema_path.exists():
            _log.error("Missing spec schema file: %s", schema_path)
            sys.exit(1)

        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        try:
            jsonschema.validate(instance=sample, schema=schema)
        except jsonschema.ValidationError as exc:
            _log.error(
                "Schema smoke-test failed for %s: %s\n"
                "This indicates a mismatch between the Python tool "
                "implementation and the spec schema — fix the code or the "
                "spec before running the server.",
                schema_filename,
                exc.message,
            )
            sys.exit(1)

    _log.info("All SOX tool schemas validated successfully against spec/.")


# ---------------------------------------------------------------------------
# BackingStore factory
# ---------------------------------------------------------------------------


def _build_store(uri: str) -> BackingStore:
    """Construct and return the appropriate ``BackingStore`` from *uri*.

    The import of adapter modules is deferred to here so that
    ``sox_protocol.core`` never has a static dependency on
    ``sox_protocol.adapters`` (import-linter rule).

    Args:
        uri: Backing-store URI string.

    Returns:
        An uninitialised ``BackingStore`` instance.

    Raises:
        ValueError: If *uri* has an unrecognised scheme.
    """
    if uri.startswith("memory://"):
        mod = importlib.import_module("sox_protocol.adapters.backing_stores.memory.store")
        return mod.MemoryStore()  # type: ignore[no-any-return]

    if uri.startswith("sqlite://"):
        # sqlite://:memory:         — in-process ephemeral
        # sqlite:///absolute/path   — triple-slash canonical form
        # sqlite://absolute/path    — double-slash convenience form
        mod = importlib.import_module("sox_protocol.adapters.backing_stores.sqlite.store")
        raw_path = uri[len("sqlite://"):]
        # Strip a leading "/" so "sqlite:///tmp/foo.db" → "/tmp/foo.db"
        if raw_path.startswith("/"):
            db_path: str = raw_path  # already absolute
        elif raw_path == ":memory:":
            db_path = ":memory:"
        else:
            db_path = raw_path
        return mod.SqliteStore(db_path)  # type: ignore[no-any-return]

    if uri.startswith("file://"):
        mod = importlib.import_module(
            "sox_protocol.adapters.backing_stores.filesystem.store"
        )
        root = uri[len("file://"):]
        return mod.FilesystemStore(root)  # type: ignore[no-any-return]

    raise ValueError(
        f"Unrecognised SOX_BACKING_STORE URI: {uri!r}.  "
        "Supported schemes: sqlite://, memory://, file://"
    )


# ---------------------------------------------------------------------------
# Agent-id resolution
# ---------------------------------------------------------------------------


def _resolve_agent_id_from_env(env: dict[str, str] | None = None) -> str:
    """Resolve the agent_id string from the process environment.

    Per spec/ports/identity.md §6 the credential — including agent_id — lives
    on the connection seam (here: MCP launch params), not in tool-call inputs.
    The ``SOX_AGENT_ID_SOURCE`` env var declares which channel the runtime
    adapter is using to inject the verified identity.

    Recognized ``SOX_AGENT_ID_SOURCE`` values:
        ``claude_code_agent_name``
            Read ``CLAUDE_AGENT_NAME`` (Claude Code subagent runtime).  Falls
            back to ``SOX_AGENT_ID`` then literal ``"default"``.
        ``env:VARNAME``
            Read an arbitrary env var (e.g. ``env:SOX_AGENT_NAME``).  Useful
            when integrating with a host that already exports its own
            agent-id env var under a different name.  Falls back to
            ``SOX_AGENT_ID`` then ``CLAUDE_AGENT_NAME`` then ``"default"``.
        ``""`` / unset
            Historical default: ``SOX_AGENT_ID`` then ``CLAUDE_AGENT_NAME``
            then ``"default"``.

    Args:
        env: Override mapping used in tests.  ``None`` (default) reads
            ``os.environ`` directly.

    Returns:
        The resolved agent_id string.  Always non-empty (falls back to
        ``"default"``).

    Side effect:
        When the configured source produces ``"default"`` despite an
        explicit non-empty ``SOX_AGENT_ID_SOURCE``, emits a WARNING log
        line naming the var that was expected to be set.  Without this,
        every misconfigured agent silently identified as ``default`` and
        the user could not figure out why ``list_agents`` only ever
        showed one entry — see CHANGELOG 0.2.3.
    """
    if env is None:
        env = dict(os.environ)

    agent_id_source = (env.get("SOX_AGENT_ID_SOURCE") or "").strip()

    if agent_id_source == "claude_code_agent_name":
        resolved = (
            (env.get("CLAUDE_AGENT_NAME") or "").strip()
            or (env.get("SOX_AGENT_ID") or "").strip()
            or "default"
        )
        if resolved == "default":
            _log.warning(
                "SOX agent_id resolved to 'default'.  "
                "SOX_AGENT_ID_SOURCE=%r expects CLAUDE_AGENT_NAME (the Claude "
                "Code subagent runtime channel), but it is unset and neither "
                "SOX_AGENT_ID nor CLAUDE_AGENT_NAME has a value.  "
                "Top-level Claude Code sessions do not set CLAUDE_AGENT_NAME "
                "— set SOX_AGENT_ID explicitly in this project's .mcp.json "
                "env block, or use SOX_AGENT_ID_SOURCE=env:<your-var-name> "
                "if you have your own identity env var.",
                agent_id_source,
            )
        return resolved

    if agent_id_source.startswith("env:"):
        custom_var = agent_id_source[len("env:"):].strip()
        resolved = (
            ((env.get(custom_var) or "").strip() if custom_var else "")
            or (env.get("SOX_AGENT_ID") or "").strip()
            or (env.get("CLAUDE_AGENT_NAME") or "").strip()
            or "default"
        )
        if resolved == "default":
            _log.warning(
                "SOX agent_id resolved to 'default'.  "
                "SOX_AGENT_ID_SOURCE=%r expects env var %r to carry the agent's "
                "identity, but %r is unset (and neither SOX_AGENT_ID nor "
                "CLAUDE_AGENT_NAME is set as a fallback).  "
                "Either export %s=<id> in the parent process before launching "
                "the MCP server, or change SOX_AGENT_ID_SOURCE to a working "
                "channel (e.g. set SOX_AGENT_ID directly in .mcp.json env).",
                agent_id_source,
                custom_var,
                custom_var,
                custom_var,
            )
        return resolved

    resolved = (
        (env.get("SOX_AGENT_ID") or "").strip()
        or (env.get("CLAUDE_AGENT_NAME") or "").strip()
        or "default"
    )
    if resolved == "default" and agent_id_source:
        # agent_id_source is non-empty but matches none of the recognised
        # forms — that's a typo, warn loudly.
        _log.warning(
            "SOX agent_id resolved to 'default'.  SOX_AGENT_ID_SOURCE=%r is "
            "not one of the recognised values ('claude_code_agent_name', "
            "'env:VARNAME', or empty).  Treating as empty — fell back to "
            "SOX_AGENT_ID then CLAUDE_AGENT_NAME, both unset.",
            agent_id_source,
        )
    return resolved


# ---------------------------------------------------------------------------
# FastMCP server factory
# ---------------------------------------------------------------------------


def create_server() -> FastMCP[dict[str, object]]:
    """Build and return a configured ``FastMCP`` instance.

    Reads ``SOX_BACKING_STORE`` and ``SOX_AGENT_ID`` from the environment.
    Registers the four SOX tools and attaches a lifespan context manager
    that:

    1. Validates tool schemas against ``spec/schemas/tools/`` (fail-fast).
    2. Initialises the backing store.
    3. Starts the background listener task.
    4. Yields the shared context dict ``{store, listener, agent_id}`` that
       the tools access via ``ctx.fastmcp._lifespan_result``.
    5. Cleans up on shutdown (stops the listener, closes the store).

    Returns:
        A ready-to-run ``FastMCP`` instance.

    Raises:
        SystemExit: If ``SOX_AGENT_ID`` is unset or ``SOX_BACKING_STORE``
            has an unrecognised URI scheme.

    Lifespan result keys
    --------------------
    ``store``
        The initialised :class:`~sox_protocol.core.ports.backing_store.BackingStore`.
    ``listener``
        The background :class:`~sox_protocol.core.mcp_server.listener.Listener` task.
    ``agent_id``
        The resolved agent identifier string (v1 transitional; kept for
        legacy-compat readers).
    ``pipeline``
        The configured :class:`~sox_protocol.core.middleware.pipeline.Pipeline`
        that all tool handlers dispatch through.
    ``verifier``
        The :class:`~sox_protocol.core.identity.verifier.IdentityVerifier`
        constructed at startup.
    ``registry``
        The :class:`~sox_protocol.core.identity.registry.InMemoryCredentialRegistry`
        holding the agent's synthetic keypair.
    ``_private_key``
        The ephemeral Ed25519 private key (v1 transitional) used by
        :func:`~sox_protocol.core.mcp_server._credential.resolve_credential`
        to produce per-call :class:`~sox_protocol.core.identity.envelope.SignedRequest`
        envelopes.  Not for direct use by tool handlers.
    """
    # Resolve the agent_id from the configured source.  See
    # ``_resolve_agent_id_from_env`` for the precedence rules and the
    # recognized ``SOX_AGENT_ID_SOURCE`` values.
    agent_id = _resolve_agent_id_from_env()

    backing_store_uri = os.environ.get("SOX_BACKING_STORE", "memory://")
    _log.info(
        "SOX MCP server starting: agent_id=%r backing_store=%r",
        agent_id,
        backing_store_uri,
    )

    try:
        store = _build_store(backing_store_uri)
    except ValueError as exc:
        _log.error("%s", exc)
        sys.exit(1)

    @contextlib.asynccontextmanager
    async def _lifespan(
        server: FastMCP[dict[str, object]],
    ) -> AsyncIterator[dict[str, object]]:
        """FastMCP lifespan: validate schemas, init store, build pipeline, start listener."""
        # 1. Fail-fast schema validation.
        _load_and_validate_schemas()

        # 2. Initialise the backing store.
        await store.initialize()  # type: ignore[attr-defined]

        # 3. Build the identity stack.
        #    v1 transitional: generate a synthetic Ed25519 keypair for this
        #    agent so that per-call SignedRequest envelopes can be verified
        #    by AuthMiddleware without requiring external key material.
        #    v1.1 will replace this with a real key loaded from disk.
        #    See _credential.py and implementation-plan.json risk R8.
        registry = InMemoryCredentialRegistry()
        audit = AuditLogWriter()
        verifier = IdentityVerifier(registry=registry, audit=audit)
        private_seed, public_key_bytes = generate_keypair()

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        private_key: Ed25519PrivateKey = Ed25519PrivateKey.from_private_bytes(private_seed)
        await registry.register(agent_id, public_key_bytes)

        # 4. Build the middleware pipeline.
        pipeline = build_default_pipeline(verifier=verifier, store=store)

        # 4b. Discover and load out-of-tree plugins, then extend the pipeline.
        #     Reads SOX_ALLOWED_PLUGINS, SOX_ENV, SOX_NO_DISCOVERY env vars
        #     (written by cli/serve.py _resolve_plugin_env before transport branch).
        _raw_allowlist = os.environ.get("SOX_ALLOWED_PLUGINS", "")
        _plugin_allowlist: list[str] | None = (
            [p for p in _raw_allowlist.split(",") if p]
            if _raw_allowlist
            else None
        )
        _plugin_env = os.environ.get("SOX_ENV", "dev")
        _no_discovery = os.environ.get("SOX_NO_DISCOVERY", "") == "1"
        try:
            register_middleware.load_plugins(
                allowlist=_plugin_allowlist,
                env=_plugin_env,
                host_protocol_version=_HOST_PROTOCOL_VERSION,
                no_discovery=_no_discovery,
            )
        except PluginStartupError as _exc:
            _envelope = _exc.to_envelope()
            _log.error(
                "[sox] plugin startup failed: %s",
                _envelope,
                extra={"sox_error_envelope": _envelope},
            )
            print(
                f"[sox] ERROR: plugin startup failed — {_envelope}",
                file=sys.stderr,
            )
            sys.exit(1)

        if register_middleware.resolved_order:
            from sox_protocol.core.middleware.default_chain import _StoreTerminal  # noqa: PLC0415
            from sox_protocol.core.middleware.plugins.store_dispatch import (  # noqa: PLC0415
                StoreDispatchMiddleware,
            )
            _store_terminal = _StoreTerminal(StoreDispatchMiddleware(store))
            pipeline = extend_pipeline_with_registry(
                pipeline, register_middleware, _store_terminal
            )
            _log.info(
                "[sox] pipeline extended with %d plugin(s): %s",
                len(register_middleware.resolved_order),
                list(register_middleware.resolved_order),
            )

        # 5. Start the background listener.
        listener = Listener(store=store, agent_id=agent_id)
        task = listener.start()

        try:
            yield {
                "store": store,
                "listener": listener,
                "agent_id": agent_id,
                "pipeline": pipeline,
                "verifier": verifier,
                "registry": registry,
                "_private_key": private_key,
            }
        finally:
            # 6. Graceful shutdown.
            await listener.stop()
            close = getattr(store, "close", None)
            if callable(close):
                await close()
            if not task.done():
                task.cancel()

    mcp: FastMCP[dict[str, object]] = FastMCP(
        name="sox-protocol",
        instructions=(
            "SOX Protocol inter-agent channel tools.  "
            "Use channels__send to send, channels__recv to receive, "
            "channels__subscribe to register interest, "
            "channels__list_channels for discovery."
        ),
        lifespan=_lifespan,
    )

    register_tools(mcp)
    return mcp


# ---------------------------------------------------------------------------
# __main__ entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the SOX MCP server.

    Transport is controlled by ``SOX_MCP_TRANSPORT``:

    - ``stdio`` (default) — standard MCP stdio transport.
    - ``http`` — HTTP/SSE transport.  Bind address / port controlled by
      ``SOX_HTTP_HOST`` and ``SOX_HTTP_PORT``.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    mcp = create_server()

    transport = os.environ.get("SOX_MCP_TRANSPORT", "stdio").lower()
    if transport == "http":
        host = os.environ.get("SOX_HTTP_HOST", "127.0.0.1")
        port = int(os.environ.get("SOX_HTTP_PORT", "8000"))
        _log.info("SOX MCP server HTTP transport on %s:%d", host, port)
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()  # pragma: no cover
