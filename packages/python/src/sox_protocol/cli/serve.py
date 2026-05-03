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

Plugin allowlist flags:
  ``--allow-plugins ID,...``
      Comma-separated plugin id allowlist.  Overrides ``SOX_ALLOWED_PLUGINS``
      when both are present (CLI takes precedence per §6.1).

  ``--no-discovery``
      Disable plugin entry-point scanning entirely.  Short-circuits all
      allowlist evaluation — even if ``--allow-plugins`` is also supplied,
      no discovery is performed and no ``PluginNotFound`` errors are raised
      (R4 precedence rule).  Useful for test runs and security audits where
      site-packages contamination must be prevented.

Environment variables (read when corresponding flag is absent):
  ``SOX_ALLOWED_PLUGINS``
      Comma-separated allowlist, same shape as ``--allow-plugins``.
  ``SOX_ENV``
      ``production`` or ``dev`` (default ``dev``).  In production mode an
      empty allowlist refuses all plugins (supply-chain protection).
  ``SOX_NO_DISCOVERY``
      Set to ``1`` to replicate ``--no-discovery`` via environment.

Spec reference: ``spec/ports/transport.md §2``;
``spec/ports/middleware/03-plugin-contract.md §6.1``
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
    parser.add_argument(
        "--allow-plugins",
        default=None,
        dest="allow_plugins",
        metavar="ID,...",
        help=(
            "Comma-separated plugin id allowlist.  "
            "Overrides SOX_ALLOWED_PLUGINS when both are provided."
        ),
    )
    parser.add_argument(
        "--no-discovery",
        action="store_true",
        dest="no_discovery",
        default=False,
        help=(
            "Disable plugin entry-point scanning entirely.  "
            "Short-circuits allowlist evaluation (R4 precedence rule).  "
            "Safe for test runs and security audits."
        ),
    )
    parser.set_defaults(func=serve_command)


def _resolve_plugin_env(args: argparse.Namespace) -> None:
    """Propagate CLI plugin flags into environment variables.

    ``--allow-plugins`` takes precedence over ``SOX_ALLOWED_PLUGINS``.
    ``--no-discovery`` sets ``SOX_NO_DISCOVERY=1``.

    Both bootstrap paths (stdio lifespan, HTTP create_app) read these env
    vars uniformly — the CLI is the single write point.

    Args:
        args: Parsed argparse namespace (must have ``allow_plugins`` and
            ``no_discovery`` attributes, set by :func:`add_serve_subcommand`).
    """
    import os

    # --allow-plugins wins over SOX_ALLOWED_PLUGINS (§6.1 CLI precedence).
    # Use getattr to defend against ad-hoc Namespace constructions in tests
    # that predate phase 03 — argparse-built namespaces always carry the
    # attribute (default None) per add_serve_subcommand().
    allow_plugins = getattr(args, "allow_plugins", None)
    if allow_plugins is not None:
        os.environ["SOX_ALLOWED_PLUGINS"] = allow_plugins

    # --no-discovery short-circuits the loader (R4).
    if getattr(args, "no_discovery", False):
        os.environ["SOX_NO_DISCOVERY"] = "1"


def serve_command(args: argparse.Namespace) -> int:
    """Execute the serve command.

    Args:
        args: Parsed argparse namespace with ``transport``, ``host``, ``port``,
            ``allow_plugins``, and ``no_discovery``.

    Returns:
        Exit code (0 on clean exit).
    """
    # Resolve plugin flags into env vars BEFORE branching on transport so
    # both the stdio lifespan and the HTTP bootstrap read them uniformly.
    _resolve_plugin_env(args)

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
