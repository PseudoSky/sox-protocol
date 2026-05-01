# SPDX-License-Identifier: Apache-2.0
"""Pytest fixtures for HTTP transport tests.

Phase 03-build-http: PassthroughIdentityResolver removed; create_app now
builds a Pipeline internally.  The ``resolver`` fixture is replaced by a
``pipeline`` fixture for tests that need to inspect middleware behaviour.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.transports.http.config import HttpConfig
from sox_protocol.adapters.transports.http.liveness import LivenessStore
from sox_protocol.adapters.transports.http.server import create_app


@pytest.fixture()
def config() -> HttpConfig:
    """Return a test HttpConfig with safe defaults."""
    return HttpConfig(
        host="127.0.0.1",
        port=9999,
        cors_origins=["http://localhost:3000"],
        buffer_limit=100,
        reconnect_max_s=5,
    )


@pytest.fixture()
def memory_store() -> MemoryStore:
    """Return a fresh MemoryStore (not yet initialized)."""
    return MemoryStore()


@pytest.fixture()
def liveness() -> LivenessStore:
    """Return a fresh LivenessStore."""
    return LivenessStore()


@pytest_asyncio.fixture()
async def store(memory_store: MemoryStore) -> AsyncGenerator[MemoryStore, None]:
    """Return an initialized MemoryStore."""
    await memory_store.initialize()
    yield memory_store


@pytest_asyncio.fixture()
async def client(
    store: MemoryStore,
    config: HttpConfig,
) -> AsyncGenerator[AsyncClient, None]:
    """Return an httpx.AsyncClient backed by the test ASGI app."""
    app = create_app(store=store, config=config)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


def auth_headers(agent_id: str) -> dict[str, str]:
    """Return Authorization headers for the given agent_id."""
    return {"Authorization": f"Bearer {agent_id}"}
