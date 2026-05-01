# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for reference agent tests (importable module, not conftest)."""

from __future__ import annotations

import contextlib
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# Ensure examples/reference-agent/ is importable.
_REF_AGENT_DIR = Path(__file__).parents[4] / "examples" / "reference-agent"
if str(_REF_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_REF_AGENT_DIR))

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.core.mcp_server.listener import Listener
from sox_protocol.core.mcp_server.server import _load_and_validate_schemas
from sox_protocol.core.mcp_server.tools import register_tools


async def build_server(store: MemoryStore, agent_id: str) -> FastMCP[Any]:
    """Build an in-process FastMCP server wired to *store* as *agent_id*."""

    @contextlib.asynccontextmanager
    async def _lifespan(server: FastMCP[Any]) -> AsyncIterator[dict[str, object]]:
        _load_and_validate_schemas()
        await store.initialize()
        listener = Listener(store=store, agent_id=agent_id)
        listener.start()
        try:
            yield {"store": store, "listener": listener, "agent_id": agent_id}
        finally:
            await listener.stop()

    mcp: FastMCP[Any] = FastMCP(name=f"sox-{agent_id}", lifespan=_lifespan)
    register_tools(mcp)
    return mcp
