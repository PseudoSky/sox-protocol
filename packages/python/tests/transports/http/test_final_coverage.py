# SPDX-License-Identifier: Apache-2.0
"""Final coverage gap tests for HTTP transport.

Covers:
- routes.py line 69: FileNotFoundError from _load_schema
- routes.py line 259: internal_error_response in op_recv exception handler
- routes.py line 295: val_err for subscribe (schema validation failure)
- routes.py line 359: val_err for list_channels (schema validation failure)
- routes.py line 535: val_err for list_agents (schema validation failure)
- routes.py line 563: val_err for group_create (schema validation failure)
- liveness.py line 139: status_filter filtering in list_agents
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.transports.http.auth import PassthroughIdentityResolver
from sox_protocol.adapters.transports.http.config import HttpConfig
from sox_protocol.adapters.transports.http.liveness import LivenessStore
from sox_protocol.adapters.transports.http.server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config() -> HttpConfig:
    return HttpConfig(
        host="127.0.0.1",
        port=9999,
        cors_origins=[],
        buffer_limit=100,
        reconnect_max_s=5,
    )


@pytest_asyncio.fixture()
async def store() -> AsyncGenerator[MemoryStore, None]:
    s = MemoryStore()
    await s.initialize()
    yield s


@pytest_asyncio.fixture()
async def client(
    store: MemoryStore,
    config: HttpConfig,
) -> AsyncGenerator[AsyncClient, None]:
    resolver = PassthroughIdentityResolver()
    app = create_app(store=store, identity=resolver, config=config)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


def auth(agent_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {agent_id}"}


# ---------------------------------------------------------------------------
# routes.py line 69: _load_schema raises FileNotFoundError
# This is covered by testing _load_schema directly.
# ---------------------------------------------------------------------------


def test_load_schema_raises_for_unknown_op() -> None:
    """Line 69: _load_op_schema raises FileNotFoundError for a non-existent op."""
    from sox_protocol.adapters.transports.http.routes import _load_op_schema

    with pytest.raises(FileNotFoundError, match="Schema not found"):
        _load_op_schema("nonexistent_operation_xyz")


# ---------------------------------------------------------------------------
# routes.py line 259: internal_error_response in op_recv
# Trigger by making store.recv raise an exception.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_op_recv_schema_validation_error_returns_400(
    client: AsyncClient,
) -> None:
    """Line 259: op_recv returns 400 when body fails schema validation.

    The recv schema uses additionalProperties:false, so unknown fields fail.
    """
    resp = await client.post(
        "/v1/ops/recv",
        json={"unknown_field": "x"},
        headers=auth("agent-a"),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_op_recv_store_exception_returns_500(
    client: AsyncClient,
    store: MemoryStore,
) -> None:
    """Line 270: op_recv returns 500 when store.recv raises."""
    from unittest.mock import AsyncMock

    with patch.object(store, "recv", new_callable=AsyncMock, side_effect=RuntimeError("db error")):
        resp = await client.post(
            "/v1/ops/recv",
            json={},
            headers=auth("agent-a"),
        )
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# routes.py line 295: wildcard subscription rejection
# Send a subscribe request with a valid pattern that is a dm/* wildcard.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_op_subscribe_wildcard_dm_returns_400(
    client: AsyncClient,
) -> None:
    """Line 295: subscribe with dm/* wildcard returns 400 (forbidden wildcard)."""
    resp = await client.post(
        "/v1/ops/subscribe",
        json={"pattern": "dm/*"},
        headers=auth("agent-a"),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_op_subscribe_invalid_body_returns_400(
    client: AsyncClient,
) -> None:
    """Line 290: subscribe with invalid body (additional property) returns 400."""
    resp = await client.post(
        "/v1/ops/subscribe",
        json={"not_pattern": "value"},
        headers=auth("agent-a"),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# routes.py line 359: val_err for list_channels — schema validation failure
# Send a list_channels request with an invalid body.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_op_list_channels_invalid_body_returns_400(
    client: AsyncClient,
) -> None:
    """Line 359: list_channels with invalid body returns 400."""
    # Send a body that violates the schema (e.g., since as a string when it
    # must be a number)
    resp = await client.post(
        "/v1/ops/list_channels",
        json={"since": "not-a-number"},
        headers=auth("agent-a"),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# routes.py line 535: val_err for list_agents — schema validation failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_op_list_agents_invalid_body_returns_400(
    client: AsyncClient,
) -> None:
    """Line 535: list_agents with invalid body returns 400."""
    # status_filter must be an array; send a string to trigger validation error
    resp = await client.post(
        "/v1/ops/list_agents",
        json={"status_filter": "online"},
        headers=auth("agent-a"),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# routes.py line 563: val_err for group_create — schema validation failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_op_group_create_invalid_body_returns_400(
    client: AsyncClient,
) -> None:
    """Line 563: group_create with invalid body returns 400."""
    # group_id must be a string; send an integer to trigger validation error
    resp = await client.post(
        "/v1/ops/group_create",
        json={"group_id": 12345},
        headers=auth("agent-a"),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# liveness.py line 139: status_filter filtering — state not in status_filter
# ---------------------------------------------------------------------------


def test_liveness_store_list_agents_status_filter_excludes() -> None:
    """Line 139: list_agents with status_filter skips agents whose state
    doesn't match the filter."""
    from sox_protocol.adapters.transports.http.liveness import AgentRecord, LivenessStore

    ls = LivenessStore()

    # Register an "online" agent via record_heartbeat
    ls.record_heartbeat("agent-online", "online")

    # Register an "offline" agent by inserting a record with last_heartbeat_at_ns=0
    ls._records["agent-never"] = AgentRecord(
        agent_id="agent-never",
        reported_status="online",
        last_heartbeat_at_ns=0,  # triggers "offline" in _derive_state
        namespace=None,
    )

    # Filter to only "online" — should exclude "agent-never" (offline)
    result = ls.list_agents(status_filter=["online"])
    agent_ids = [r["agent_id"] for r in result]
    assert "agent-online" in agent_ids
    assert "agent-never" not in agent_ids
