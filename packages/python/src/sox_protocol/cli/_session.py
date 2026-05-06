# SPDX-License-Identifier: Apache-2.0
"""Shared CLI session helpers for ``sox-protocol`` subcommands.

These helpers let one-shot CLI commands (``sox-protocol channels send`` etc.)
share the same ``.mcp.json`` discovery, agent-id resolution, and
backing-store construction that the chat TUI and MCP server use.

They deliberately bypass the MCP-over-stdio layer and talk to the
``BackingStore`` port directly.  The MCP layer adds:

  - per-call schema validation
  - synthetic Ed25519 signature envelopes (v1 transitional)
  - background listener task for push-delivery

For one-shot CLI commands these are not necessary — the user wants to
exercise the same data flow the MCP server would have produced, fast,
without spawning a subprocess per command.  Long-running commands
(``listen``) construct the listener themselves.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
from pathlib import Path

from sox_protocol.core.mcp_server.server import (
    _build_store as build_store,
)
from sox_protocol.core.mcp_server.server import (
    _resolve_agent_id_from_env as resolve_agent_id_from_env,
)
from sox_protocol.core.ports.backing_store import BackingStore

_log = logging.getLogger(__name__)

# Name of the MCP server entry the installer writes into ``.mcp.json``.
# Mirrors ``adapters.runtimes.claude_code.install._MCP_SERVER_NAME``.
_MCP_SERVER_KEY = "sox"

# Default backing-store URI used when nothing is discovered.  The chat TUI
# defaults to ``memory://`` (ephemeral); for one-shot CLI commands we
# prefer to fail loudly so the user knows the project isn't installed.
_FALLBACK_URI = "memory://"


def discover_mcp_env(start: Path | None = None) -> dict[str, str]:
    """Return ``mcpServers.sox.env`` from the nearest ancestor ``.mcp.json``.

    Walks up from *start* (defaults to ``Path.cwd()``).  Returns ``{}`` if
    no ancestor contains a SOX MCP server entry.

    Args:
        start: Starting directory; defaults to the current working directory.

    Returns:
        Env dict (string keys/values only), or empty dict.
    """
    here = (start or Path.cwd()).resolve()
    for ancestor in [here, *here.parents]:
        candidate = ancestor / ".mcp.json"
        if not candidate.is_file():
            continue
        try:
            with candidate.open(encoding="utf-8") as fh:
                cfg = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            _log.debug("Skipping unreadable %s: %s", candidate, exc)
            continue
        env = cfg.get("mcpServers", {}).get(_MCP_SERVER_KEY, {}).get("env", {})
        if isinstance(env, dict) and env:
            return {str(k): str(v) for k, v in env.items()}
    return {}


def resolve_backing_store_uri(project_dir: Path | None = None) -> str:
    """Resolve the effective ``SOX_BACKING_STORE`` URI.

    Order of precedence:
      1. ``SOX_BACKING_STORE`` env var on the current process.
      2. ``mcpServers.sox.env.SOX_BACKING_STORE`` from the nearest
         ``.mcp.json`` ancestor.
      3. ``memory://`` fallback.

    Args:
        project_dir: Override the discovery start directory.

    Returns:
        Backing-store URI string.
    """
    env_uri = os.environ.get("SOX_BACKING_STORE", "").strip()
    if env_uri:
        return env_uri
    discovered = discover_mcp_env(project_dir)
    uri = discovered.get("SOX_BACKING_STORE", "").strip()
    return uri or _FALLBACK_URI


def resolve_agent_id(
    cli_arg: str | None,
    project_dir: Path | None = None,
) -> str:
    """Resolve the effective agent_id for a CLI command.

    Order of precedence:
      1. ``--agent-id`` CLI argument (when non-empty).
      2. ``SOX_AGENT_ID_SOURCE``-driven env resolution, layered on top of
         the discovered ``.mcp.json`` env so commands run in a SOX-installed
         project use the same identity the MCP server would.
      3. The OS user (``getpass.getuser()``) prefixed with ``cli-``.

    Args:
        cli_arg: Value of the command's ``--agent-id`` flag.
        project_dir: Override the discovery start directory.

    Returns:
        Agent ID string.
    """
    if cli_arg:
        return cli_arg.strip()

    # Layer the discovered .mcp.json env on top of the process env so that
    # SOX_AGENT_ID_SOURCE = "env:SOX_AGENT_NAME" picks up SOX_AGENT_NAME from
    # whichever side actually exports it.
    layered = dict(os.environ)
    layered.update(discover_mcp_env(project_dir))
    resolved = resolve_agent_id_from_env(layered)
    if resolved and resolved != "default":
        return resolved

    try:
        return f"cli-{getpass.getuser()}"
    except Exception:
        return "cli-user"


async def open_store(uri: str | None = None) -> BackingStore:
    """Open and initialize a backing store from *uri* (or the resolved URI).

    Args:
        uri: Optional URI override.  When None, calls
            :func:`resolve_backing_store_uri`.

    Returns:
        An initialized :class:`BackingStore` ready for tool calls.
    """
    effective_uri = uri or resolve_backing_store_uri()
    store = build_store(effective_uri)
    await store.initialize()
    return store
