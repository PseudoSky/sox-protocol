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

from sox_protocol.cli.serve import add_serve_subcommand


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code.
    """
    parser = argparse.ArgumentParser(
        prog="sox",
        description="SOX Protocol server and tooling.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand")
    add_serve_subcommand(subparsers)

    args = parser.parse_args(argv)

    if not hasattr(args, "func") or args.func is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
