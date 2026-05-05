# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol CLI — main entrypoint.

Dispatches to subcommands:
  sox serve --transport http [--host HOST] [--port PORT]
  sox serve --transport stdio

Spec reference: ``spec/ports/transport.md``
"""

from __future__ import annotations

import argparse
import sys

from sox_protocol import __version__
from sox_protocol.cli.chat import register_subparser as add_chat_subcommand
from sox_protocol.cli.install import add_install_subcommand
from sox_protocol.cli.lint_discipline import add_lint_discipline_subcommand
from sox_protocol.cli.serve import add_serve_subcommand
from sox_protocol.cli.upgrade import add_upgrade_subcommand
from sox_protocol.cli.verify import add_verify_subcommand


def _version_command(_args: argparse.Namespace) -> int:
    """Print the installed sox-protocol version and exit."""
    print(__version__)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code.
    """
    parser = argparse.ArgumentParser(
        prog="sox-protocol",
        description=f"SOX Protocol server and tooling.  (version {__version__})",
    )
    # `-V` / `--version` global flag — exits before subcommand dispatch.
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Print the installed sox-protocol version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommand")
    add_serve_subcommand(subparsers)
    add_chat_subcommand(subparsers)
    add_install_subcommand(subparsers)
    add_upgrade_subcommand(subparsers)
    add_verify_subcommand(subparsers)
    add_lint_discipline_subcommand(subparsers)

    # `sox-protocol version` subcommand — same output as `--version`, but
    # discoverable via tab completion + listed in the subcommand help.
    version_parser = subparsers.add_parser(
        "version",
        help="Print the installed sox-protocol version and exit.",
    )
    version_parser.set_defaults(func=_version_command)

    args = parser.parse_args(argv)

    if not hasattr(args, "func") or args.func is None:
        parser.print_help()
        return 0

    rc: int = args.func(args)
    return rc


if __name__ == "__main__":
    sys.exit(main())
