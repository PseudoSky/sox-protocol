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

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.core.identity import AuditLogWriter, InMemoryCredentialRegistry
from sox_protocol.core.identity.keys import generate_keypair
from sox_protocol.core.identity.verifier import IdentityVerifier
from sox_protocol.core.mcp_server.listener import Listener
from sox_protocol.core.mcp_server.server import _load_and_validate_schemas
from sox_protocol.core.mcp_server.tools import register_tools
from sox_protocol.core.middleware import build_default_pipeline


async def build_server(store: MemoryStore, agent_id: str) -> FastMCP[Any]:
    """Build an in-process FastMCP server wired to *store* as *agent_id*.

    Mirrors the production lifespan in core/mcp_server/server.py: builds the
    identity stack (registry + verifier + audit + synthetic Ed25519 keypair),
    constructs the middleware pipeline via ``build_default_pipeline``, and
    yields a lifespan dict with all keys ``tools.py`` reads from
    ``ctx.fastmcp._lifespan_result``.
    """

    @contextlib.asynccontextmanager
    async def _lifespan(server: FastMCP[Any]) -> AsyncIterator[dict[str, object]]:
        _load_and_validate_schemas()
        await store.initialize()

        registry = InMemoryCredentialRegistry()
        audit = AuditLogWriter()
        verifier = IdentityVerifier(registry=registry, audit=audit)
        private_seed, public_key_bytes = generate_keypair()
        private_key: Ed25519PrivateKey = Ed25519PrivateKey.from_private_bytes(
            private_seed
        )
        await registry.register(agent_id, public_key_bytes)

        pipeline = build_default_pipeline(verifier=verifier, store=store)

        listener = Listener(store=store, agent_id=agent_id)
        listener.start()
        try:
            yield {
                "store": store,
                "listener": listener,
                "agent_id": agent_id,
                "pipeline": pipeline,
                "verifier": verifier,
                "registry": registry,
                "_private_key": private_key,
            }
        finally:
            await listener.stop()

    mcp: FastMCP[Any] = FastMCP(name=f"sox-{agent_id}", lifespan=_lifespan)
    register_tools(mcp)
    return mcp
