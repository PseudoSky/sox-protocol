# SPDX-License-Identifier: Apache-2.0
"""Command-line entry point for the SOX reference agent.

Usage examples
--------------
# Start the agent in long-running mode against a local SOX MCP server:
    python cli.py --agent-id my-agent --namespace reference

# Run a single drain cycle and exit (used by run_standalone.sh):
    python cli.py --agent-id my-agent --once

# Point at a specific SQLite backing store:
    python cli.py --agent-id my-agent --backing-store sqlite:///tmp/sox.db
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

# FastMCP client + server imports for in-process wiring (used when no external
# MCP server URL is configured — the default for standalone / test mode).
from fastmcp import Client, FastMCP

# Guard: ensure examples/reference-agent/ is importable as a plain package.
sys.path.insert(0, str(Path(__file__).parent))

from agent import ReferenceAgent  # noqa: E402 — path manipulation above


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser.

    Returns:
        Configured ``ArgumentParser`` with all reference-agent flags.
    """
    parser = argparse.ArgumentParser(
        prog="sox-reference-agent",
        description="SOX Protocol canonical reference agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # --agent-id: the stable identity for this agent instance.
    parser.add_argument(
        "--agent-id",
        default=os.environ.get("SOX_AGENT_ID", "reference-agent"),
        help="Unique agent identifier (default: SOX_AGENT_ID env or 'reference-agent').",
    )
    # --namespace: the SOX namespace to operate in.
    parser.add_argument(
        "--namespace",
        default=os.environ.get("SOX_NAMESPACE", "reference"),
        help="SOX namespace (default: SOX_NAMESPACE env or 'reference').",
    )
    # --backing-store: URI for the backing store (memory:// by default).
    parser.add_argument(
        "--backing-store",
        default=os.environ.get("SOX_BACKING_STORE", "memory://"),
        help="Backing store URI: memory://, sqlite://path, file://path.",
    )
    # --state-dir: where to persist seq.json for recovery.
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(
            os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
        )
        / "sox-reference-agent",
        help="Directory for seq.json state file (recovery cursor).",
    )
    # --once: run a single drain cycle and exit — used by run_standalone.sh.
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single recv drain cycle then exit. Used for CI / standalone test.",
    )
    # --log-level: controls verbosity.
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser


async def _run_agent(
    agent_id: str,
    namespace: str,
    backing_store_uri: str,
    state_dir: Path,
    once: bool,
) -> None:
    """Build an in-process FastMCP server, wire the agent, and run it.

    This helper owns the server + client lifecycle so the top-level ``main``
    function stays clean. The server uses the same backing-store URI that the
    SOX MCP server would use in production, but wired in-process via FastMCP's
    ``Client(mcp_instance)`` harness — no network required.

    Args:
        agent_id:         Unique agent identifier string.
        namespace:        SOX namespace name.
        backing_store_uri: Backing store URI (memory://, sqlite://..., etc.).
        state_dir:        Directory for seq.json persistence.
        once:             If True, run a single drain cycle.
    """
    # Lazily import server helpers to avoid circular imports in tests.
    from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
    from sox_protocol.core.mcp_server.listener import Listener
    from sox_protocol.core.mcp_server.server import _build_store, _load_and_validate_schemas
    from sox_protocol.core.mcp_server.tools import register_tools

    # Build the backing store from the URI.
    store = _build_store(backing_store_uri)

    @contextlib.asynccontextmanager
    async def _lifespan(server: FastMCP[Any]) -> AsyncIterator[dict[str, object]]:
        """FastMCP lifespan: validate schemas, init store, start listener."""
        # Validate spec schemas at startup (fail-fast on drift).
        _load_and_validate_schemas()
        await store.initialize()
        # The listener runs a background task pushing new messages into a queue.
        listener = Listener(store=store, agent_id=agent_id)
        listener.start()
        try:
            yield {"store": store, "listener": listener, "agent_id": agent_id}
        finally:
            await listener.stop()
            if hasattr(store, "close"):
                await store.close()

    # Build an in-process FastMCP server for this agent.
    mcp: FastMCP[Any] = FastMCP(name=f"sox-{agent_id}", lifespan=_lifespan)
    register_tools(mcp)

    # Connect via FastMCP's in-process client harness.
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id=agent_id,
            namespace=namespace,
            state_dir=state_dir,
        )
        await agent.run(once=once)


def main() -> None:
    """Parse arguments and run the reference agent.

    This is the console_scripts entry point. It configures logging, parses
    args, and drives the async event loop.
    """
    parser = _build_arg_parser()
    args = parser.parse_args()

    # Configure logging before anything else.
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Ensure the state directory exists before the agent starts.
    args.state_dir.mkdir(parents=True, exist_ok=True)

    # Run the async agent on the default event loop.
    asyncio.run(
        _run_agent(
            agent_id=args.agent_id,
            namespace=args.namespace,
            backing_store_uri=args.backing_store,
            state_dir=args.state_dir,
            once=args.once,
        )
    )


if __name__ == "__main__":
    main()
