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
from pathlib import Path
from typing import Any, AsyncIterator

import jsonschema
from fastmcp import FastMCP

from sox_protocol.core.mcp_server.listener import Listener
from sox_protocol.core.mcp_server.tools import register_tools
from sox_protocol.core.ports.backing_store import BackingStore

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Spec schema root (relative to this file: packages/python/src/.../server.py
# → climb 8 levels to sox-protocol/, then spec/schemas/tools/).
# ---------------------------------------------------------------------------
_SPEC_SCHEMAS_DIR: Path = (
    Path(__file__).resolve().parents[6] / "spec" / "schemas" / "tools"
)

# ---------------------------------------------------------------------------
# Canonical sample outputs used to smoke-test schema loading.
# Each dict must be valid against the corresponding *.output.schema.json.
# ---------------------------------------------------------------------------
_SCHEMA_SMOKE_SAMPLES: dict[str, dict[str, object]] = {
    "send.output.schema.json": {
        "sent_at": 1_714_300_000.0,
        "message_id": "1",
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
        "protocol_version": "1.0",
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
    """
    agent_id = (
        os.environ.get("SOX_AGENT_ID", "").strip()
        or os.environ.get("CLAUDE_AGENT_NAME", "").strip()
        or "default"
    )

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
        """FastMCP lifespan: validate schemas, init store, start listener."""
        # 1. Fail-fast schema validation.
        _load_and_validate_schemas()

        # 2. Initialise the backing store.
        await store.initialize()  # type: ignore[attr-defined]

        # 3. Start the background listener.
        listener = Listener(store=store, agent_id=agent_id)
        task = listener.start()

        try:
            yield {
                "store": store,
                "listener": listener,
                "agent_id": agent_id,
            }
        finally:
            # 4. Graceful shutdown.
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


if __name__ == "__main__":
    main()
