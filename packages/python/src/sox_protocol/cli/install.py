# SPDX-License-Identifier: Apache-2.0
"""``sox-protocol install`` CLI subcommand.

Installs the SOX inter-agent-channels skill, MCP server registration, and
cadence hooks into a Claude Code project. Wraps
``sox_protocol.adapters.runtimes.claude_code.install.install`` so users
don't have to remember the long module path.

Equivalent to:

    python -m sox_protocol.adapters.runtimes.claude_code install [--project-dir DIR] [--quiet]

but discoverable via ``sox-protocol --help``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sox_protocol.adapters.runtimes.claude_code.install import install


def add_install_subcommand(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Register the ``install`` subcommand."""
    parser = subparsers.add_parser(
        "install",
        help="Install the SOX adapter into a Claude Code project.",
        description=(
            "Install the SOX inter-agent-channels skill, MCP server "
            "registration, and cadence hooks into a Claude Code project. "
            "Idempotent — re-running merges into existing settings rather "
            "than overwriting."
        ),
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Path to the Claude Code project root (default: current directory).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the per-file write log.",
    )
    parser.add_argument(
        "--auto-subscribe",
        action="store_true",
        help=(
            "Append an Activation section to the installed SKILL.md that "
            "tells the LLM to subscribe to its personal inbox "
            "(`agent/<your-id>`), drain pending messages, and emit one "
            "heartbeat on first skill load.  Without this flag the skill "
            "is purely descriptive (no auto-action)."
        ),
    )
    parser.add_argument(
        "--channel",
        action="append",
        dest="default_channels",
        metavar="CHANNEL",
        help=(
            "Extra channel pattern to include in the auto-subscribe "
            "instruction (in addition to `agent/<your-id>`).  Repeat for "
            "multiple channels.  Ignored without --auto-subscribe."
        ),
    )
    parser.add_argument(
        "--no-permissions",
        action="store_true",
        help=(
            "Skip injecting the SOX MCP tool names into "
            "`.claude/settings.json` `permissions.allow`.  By default the "
            "installer adds all 15 SOX tools so agents can call them "
            "without per-call approval prompts.  Pass this flag to keep "
            "the historical 'ask on every call' UX."
        ),
    )
    parser.set_defaults(func=install_command)


def install_command(args: argparse.Namespace) -> int:
    """Execute the ``install`` subcommand.

    Args:
        args: Parsed namespace with ``project_dir``, ``quiet``,
            ``auto_subscribe``, ``default_channels``.

    Returns:
        Exit code (0 on success).
    """
    install(
        project_dir=args.project_dir,
        verbose=not args.quiet,
        auto_subscribe=getattr(args, "auto_subscribe", False),
        default_channels=getattr(args, "default_channels", None),
        inject_permissions=not getattr(args, "no_permissions", False),
    )
    return 0
