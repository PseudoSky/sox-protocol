# SPDX-License-Identifier: Apache-2.0
"""Tests covering the auth-error branches (if err is not None: return err)
and exception paths in every route handler in routes.py.

Each route has an `if err is not None: return err` check after _auth_and_body().
When no Authorization header is provided, resolve_agent_id returns an error,
hitting lines 91, 151, 170, 193, 222, 230-231, 243, 248-249, 265, 296,
321, 332-333, 345, 364, 391, 411, 431.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.transports.http.auth import PassthroughIdentityResolver
from sox_protocol.adapters.transports.http.config import HttpConfig
from sox_protocol.adapters.transports.http.liveness import LivenessStore
from sox_protocol.adapters.transports.http.server import create_app


@pytest_asyncio.fixture()
async def anon_client() -> AsyncGenerator[AsyncClient, None]:
    """Client with no authorization header capability — store initialized."""
    store = MemoryStore()
    await store.initialize()
    resolver = PassthroughIdentityResolver()
    config = HttpConfig(
        host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5
    )
    liveness = LivenessStore()
    app = create_app(store=store, identity=resolver, config=config, liveness=liveness)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Each test hits one route without auth → triggers `if err is not None: return err`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Line 91: op_send auth error path."""
    resp = await anon_client.post("/v1/ops/send", json={"channel": "ch/1", "body": {}})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_subscribe_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Line 151: op_subscribe auth error path."""
    resp = await anon_client.post("/v1/ops/subscribe", json={"pattern": "ch/*"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unsubscribe_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Line 170: op_unsubscribe auth error path."""
    resp = await anon_client.post("/v1/ops/unsubscribe", json={"patterns": ["ch/*"]})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_channels_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Line 193: op_list_channels auth error path."""
    resp = await anon_client.post("/v1/ops/list_channels", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_channels_ack_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Lines 222, 230-231: op_channels_ack auth error path."""
    resp = await anon_client.post(
        "/v1/ops/channels_ack", json={"message_id": "1", "status": "received"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_channels_collect_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Lines 243, 248-249: op_channels_collect auth error path."""
    resp = await anon_client.post(
        "/v1/ops/channels_collect", json={"channel": "ch/1", "count": 1}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_replay_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Lines 265, 296: op_replay auth error path."""
    resp = await anon_client.post("/v1/ops/replay", json={"channel": "ch/1"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_group_create_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Line 321: op_group_create auth error path."""
    resp = await anon_client.post("/v1/ops/group_create", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_group_invite_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Lines 332-333: op_group_invite auth error path."""
    resp = await anon_client.post(
        "/v1/ops/group_invite", json={"group_id": "group/x", "agent_id": "y"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_group_join_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Lines 345, 364: op_group_join auth error path."""
    resp = await anon_client.post("/v1/ops/group_join", json={"group_id": "group/x"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_group_leave_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Lines 391, 411: op_group_leave auth error path."""
    resp = await anon_client.post("/v1/ops/group_leave", json={"group_id": "group/x"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_group_list_members_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Line 431: op_group_list_members auth error path."""
    resp = await anon_client.post(
        "/v1/ops/group_list_members", json={"group_id": "group/x"}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Exception paths: channels_ack (230-231), channels_heartbeat (248-249),
# list_agents (332-333)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def erroring_client_ack_hb() -> AsyncGenerator[AsyncClient, None]:
    """Client whose store raises on ack and heartbeat."""
    from unittest.mock import AsyncMock, MagicMock
    store = MagicMock(spec=MemoryStore)
    store.ack = AsyncMock(side_effect=RuntimeError("ack exploded"))
    store.heartbeat = AsyncMock(side_effect=RuntimeError("heartbeat exploded"))
    resolver = PassthroughIdentityResolver()
    config = HttpConfig(
        host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5
    )
    liveness = LivenessStore()
    app = create_app(store=store, identity=resolver, config=config, liveness=liveness)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_channels_ack_store_exception(
    erroring_client_ack_hb: AsyncClient,
) -> None:
    """Lines 230-231: store.ack raises → internal_error_response."""
    resp = await erroring_client_ack_hb.post(
        "/v1/ops/channels_ack",
        json={"message_id": "1", "status": "received"},
        headers={"Authorization": "Bearer agent-a"},
    )
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_channels_heartbeat_store_exception(
    erroring_client_ack_hb: AsyncClient,
) -> None:
    """Lines 248-249: store.heartbeat raises → internal_error_response."""
    resp = await erroring_client_ack_hb.post(
        "/v1/ops/channels_heartbeat",
        json={"status": "online"},
        headers={"Authorization": "Bearer agent-a"},
    )
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_list_agents_liveness_exception() -> None:
    """FIX-4: store.list_agents raises → internal_error_response.

    list_agents now delegates to BackingStore.list_agents(), not LivenessStore.
    """
    from unittest.mock import AsyncMock, MagicMock
    store = MagicMock(spec=MemoryStore)
    store.list_agents = AsyncMock(side_effect=RuntimeError("store exploded"))
    resolver = PassthroughIdentityResolver()
    config = HttpConfig(
        host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5
    )
    liveness = LivenessStore()
    app = create_app(store=store, identity=resolver, config=config, liveness=liveness)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        resp = await ac.post(
            "/v1/ops/list_agents",
            json={},
            headers={"Authorization": "Bearer agent-a"},
        )
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Auth error tests for channels_heartbeat and list_agents (lines 243, 321)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_heartbeat_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Line 243: op_channels_heartbeat auth error path."""
    resp = await anon_client.post("/v1/ops/channels_heartbeat", json={"status": "online"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_agents_no_auth_returns_401(anon_client: AsyncClient) -> None:
    """Line 321: op_list_agents auth error path."""
    resp = await anon_client.post("/v1/ops/list_agents", json={})
    assert resp.status_code == 401
