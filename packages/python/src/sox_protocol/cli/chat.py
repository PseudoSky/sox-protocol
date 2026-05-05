# SPDX-License-Identifier: Apache-2.0
"""``sox chat`` CLI subcommand.

Boots the SOX chat TUI (Textual-based four-pane interface).

Options
-------
--agent-id      Agent identifier for this session (default: ``tui-user``).
--channel       Initial channel to focus (default: ``#general``).
--no-spawn      Attach to an existing SOX MCP server instead of spawning one.
                Requires ``--server-cmd`` or a running server accessible via
                the default stdio command.
--server-cmd    Override the default server spawn command.
                Accepts a space-separated shell string; split on whitespace.

Spec reference: ``docs/decisions/tui-connection-model.md``
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

# Module-level import so tests can monkeypatch sox_protocol.cli.chat.run
from sox_protocol.tui.app import run

_log = logging.getLogger(__name__)


def _discover_mcp_env(start: Path | None = None) -> dict[str, str]:
    """Read ``mcpServers.sox.env`` from the nearest ``.mcp.json`` ancestor.

    The Claude Code installer writes ``.mcp.json`` at the project root with
    the SOX server's env vars (``SOX_BACKING_STORE``, ``SOX_AGENT_ID_SOURCE``)
    baked in. Without this discovery, ``sox-protocol chat`` would spawn a
    fresh MCP server with no env (defaults to ``memory://``), so the TUI
    would silently see a *different* backing store than the project's Claude
    Code agents — one of those "why aren't my messages showing up" gotchas.

    Walks up from *start* (defaults to ``Path.cwd()``) looking for the first
    ``.mcp.json`` whose ``mcpServers.sox.env`` block exists.  Returns the
    env dict or ``{}`` if no such file is found.

    Args:
        start: Starting directory; defaults to the current working directory.

    Returns:
        Dict of env vars from the discovered ``.mcp.json``, or ``{}``.
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
        env = (
            cfg.get("mcpServers", {})
            .get("sox", {})
            .get("env", {})
        )
        if isinstance(env, dict) and env:
            _log.debug("Discovered SOX env from %s: keys=%s", candidate, list(env))
            return {str(k): str(v) for k, v in env.items()}
    return {}


def register_subparser(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Add the ``chat`` subcommand to *subparsers*.

    Args:
        subparsers: The argparse subparsers action from the main parser.
    """
    parser = subparsers.add_parser(
        "chat",
        help="Launch the SOX chat TUI.",
        description=(
            "Start the interactive SOX Protocol chat terminal UI.  "
            "By default, spawns a local SOX MCP server as a stdio subprocess "
            "and connects the TUI to it as an MCP client."
        ),
    )
    parser.add_argument(
        "--agent-id",
        default="tui-user",
        metavar="ID",
        help="Agent identifier for this TUI session (default: tui-user).",
    )
    parser.add_argument(
        "--channel",
        default="#general",
        metavar="CHANNEL",
        help="Initial channel to focus (default: #general).",
    )
    parser.add_argument(
        "--no-spawn",
        action="store_true",
        default=False,
        help=(
            "Do not spawn a local server; attach to an existing one.  "
            "Requires a pre-running SOX MCP server accessible on stdio."
        ),
    )
    parser.add_argument(
        "--server-cmd",
        default=None,
        metavar="CMD",
        help=(
            "Override the server spawn command (space-separated string).  "
            "Ignored when --no-spawn is set."
        ),
    )
    parser.set_defaults(func=chat_command)


def chat_command(args: argparse.Namespace) -> int:
    """Execute the ``sox chat`` command.

    Args:
        args: Parsed namespace with ``agent_id``, ``channel``, ``no_spawn``,
            ``server_cmd``.

    Returns:
        Exit code (0 on clean exit).
    """
    agent_id: str = getattr(args, "agent_id", "tui-user")
    channel: str = getattr(args, "channel", "#general")
    no_spawn: bool = getattr(args, "no_spawn", False)
    server_cmd_str: str | None = getattr(args, "server_cmd", None)

    spawn_server = not no_spawn

    if no_spawn:
        # Attach mode: client wraps pre-opened stdio (advanced usage)
        run(
            agent_id=agent_id,
            initial_channel=channel,
            spawn_server=False,
        )
        return 0

    # 1. Auto-discover env from nearest ancestor .mcp.json (the Claude Code
    #    installer writes SOX_BACKING_STORE, SOX_AGENT_ID_SOURCE, etc. there).
    # 2. Layer SOX_AGENT_ID from --agent-id on top — explicit CLI flag wins
    #    over file values, so different TUI sessions can share one project's
    #    DB while having distinct identities.
    server_env: dict[str, str] = _discover_mcp_env()
    server_env["SOX_AGENT_ID"] = agent_id

    if server_cmd_str:
        # Pass the override command via env so ServerProcess can pick it up.
        # The actual split happens inside the app when constructing
        # ServerProcess — for now we store it in env for the app to read.
        server_env["SOX_TUI_SERVER_CMD"] = server_cmd_str

    run(
        agent_id=agent_id,
        initial_channel=channel,
        spawn_server=spawn_server,
        server_env=server_env,
    )
    return 0


# Alias for backward compatibility and direct import
main = chat_command
