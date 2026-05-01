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

# Module-level import so tests can monkeypatch sox_protocol.cli.chat.run
from sox_protocol.tui.app import run


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

    # Build optional server_env from server_cmd override
    server_env: dict[str, str] = {"SOX_AGENT_ID": agent_id}

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
