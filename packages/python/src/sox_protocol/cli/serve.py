# SPDX-License-Identifier: Apache-2.0
"""``sox serve`` subcommand implementation.

Starts the SOX server on the requested transport (http or stdio).

For ``--transport http``:
  - Reads config from env vars (SOX_HTTP_HOST, SOX_HTTP_PORT, etc.)
  - Instantiates an in-memory backing store
  - Builds the FastAPI app via :func:`create_app`
  - Runs uvicorn

For ``--transport stdio``:
  - Delegates to the existing MCP server entrypoint

Spec reference: ``spec/ports/transport.md §2``
"""

from __future__ import annotations

import argparse


def add_serve_subcommand(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Add the ``serve`` subcommand to *subparsers*.

    Args:
        subparsers: The argparse subparsers action from the main parser.
    """
    parser = subparsers.add_parser(
        "serve",
        help="Start the SOX server on the specified transport.",
        description="Start the SOX Protocol server.",
    )
    parser.add_argument(
        "--transport",
        choices=["http", "stdio"],
        default="http",
        help="Transport type (default: http).",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Bind host (HTTP only; overrides SOX_HTTP_HOST).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (HTTP only; overrides SOX_HTTP_PORT).",
    )
    parser.set_defaults(func=serve_command)


def serve_command(args: argparse.Namespace) -> int:
    """Execute the serve command.

    Args:
        args: Parsed argparse namespace with ``transport``, ``host``, ``port``.

    Returns:
        Exit code (0 on clean exit).
    """
    transport = getattr(args, "transport", "http")

    if transport == "stdio":
        # Delegate to the existing MCP server
        from sox_protocol.core.mcp_server import server as mcp_server
        mcp_server.main()
        return 0

    # HTTP transport
    import os

    from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
    from sox_protocol.adapters.transports.http.config import HttpConfig
    from sox_protocol.adapters.transports.http.server import create_app

    # Allow CLI --host / --port to override env
    if args.host:
        os.environ["SOX_HTTP_HOST"] = args.host
    if args.port:
        os.environ["SOX_HTTP_PORT"] = str(args.port)

    config = HttpConfig.from_env()
    store = MemoryStore()

    import asyncio

    loop = asyncio.new_event_loop()
    loop.run_until_complete(store.initialize())

    app = create_app(store=store, config=config)

    import uvicorn

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level="info",
        loop="asyncio",
    )
    return 0
