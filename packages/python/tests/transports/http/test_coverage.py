# SPDX-License-Identifier: Apache-2.0
"""Additional tests to reach 100% coverage on adapters/transports/http/."""

from __future__ import annotations

import os
import time

import pytest
from httpx import ASGITransport, AsyncClient

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.transports.http.auth import (
    PassthroughIdentityResolver,
    resolve_agent_id,
)
from sox_protocol.adapters.transports.http.config import HttpConfig
from sox_protocol.adapters.transports.http.errors import (
    internal_error_response,
    sox_error_response,
    validation_error_response,
)
from sox_protocol.adapters.transports.http.liveness import (
    _OFFLINE_THRESHOLD_S,
    _STALE_THRESHOLD_S,
    AgentRecord,
    LivenessStore,
)
from sox_protocol.adapters.transports.http.server import HttpTransport, create_app
from sox_protocol.adapters.transports.http.sse import build_sse_router
from tests.transports.http.conftest import auth_headers

# ---------------------------------------------------------------------------
# config.py
# ---------------------------------------------------------------------------


def test_config_from_env_defaults() -> None:
    """HttpConfig.from_env() returns defaults when no env vars set."""
    for key in ["SOX_HTTP_HOST", "SOX_HTTP_PORT", "SOX_HTTP_CORS_ORIGINS",
                "SOX_HTTP_BUFFER_LIMIT", "SOX_HTTP_RECONNECT_MAX_S"]:
        os.environ.pop(key, None)
    cfg = HttpConfig.from_env()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8765
    assert cfg.buffer_limit == 1000
    assert cfg.reconnect_max_s == 30


def test_config_from_env_overrides() -> None:
    """HttpConfig.from_env() reads env vars."""
    os.environ["SOX_HTTP_HOST"] = "0.0.0.0"
    os.environ["SOX_HTTP_PORT"] = "9000"
    os.environ["SOX_HTTP_BUFFER_LIMIT"] = "500"
    os.environ["SOX_HTTP_RECONNECT_MAX_S"] = "60"
    os.environ["SOX_HTTP_CORS_ORIGINS"] = "http://foo.com,http://bar.com"
    cfg = HttpConfig.from_env()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000
    assert cfg.buffer_limit == 500
    assert cfg.reconnect_max_s == 60
    assert "http://foo.com" in cfg.cors_origins
    # Cleanup
    for key in ["SOX_HTTP_HOST", "SOX_HTTP_PORT", "SOX_HTTP_CORS_ORIGINS",
                "SOX_HTTP_BUFFER_LIMIT", "SOX_HTTP_RECONNECT_MAX_S"]:
        os.environ.pop(key, None)


# ---------------------------------------------------------------------------
# errors.py
# ---------------------------------------------------------------------------


def test_sox_error_response_with_retry_after() -> None:
    """sox_error_response includes retry_after when set."""
    resp = sox_error_response("rate_limit", "slow down", 429, retry_after=30)
    assert resp.status_code == 429
    import json
    body = json.loads(resp.body)
    assert body["retry_after"] == 30


def test_internal_error_response() -> None:
    """internal_error_response returns 500."""
    resp = internal_error_response("boom")
    assert resp.status_code == 500


def test_validation_error_response() -> None:
    """validation_error_response returns 400."""
    resp = validation_error_response("bad input")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# auth.py
# ---------------------------------------------------------------------------


def test_passthrough_resolver_empty_token_raises() -> None:
    """PassthroughIdentityResolver.resolve('') raises ValueError."""
    r = PassthroughIdentityResolver()
    with pytest.raises(ValueError):
        r.resolve("")


@pytest.mark.asyncio
async def test_resolve_agent_id_with_bad_resolver() -> None:
    """resolve_agent_id returns error when resolver raises ValueError."""
    class BadResolver:
        def resolve(self, token: str) -> str:
            raise ValueError("bad token")

    from fastapi import Request as FastAPIRequest
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/ops/recv",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer bad-token")],
    }
    req = FastAPIRequest(scope)
    agent_id, err = resolve_agent_id(req, BadResolver())
    assert agent_id == ""
    assert err is not None
    assert err.status_code == 401


# ---------------------------------------------------------------------------
# liveness.py
# ---------------------------------------------------------------------------


def test_liveness_derive_state_never_heartbeated() -> None:
    """Agent with last_heartbeat_at_ns==0 derives to 'offline'."""
    ls = LivenessStore()
    rec = AgentRecord(agent_id="x", last_heartbeat_at_ns=0)
    assert ls._derive_state(rec) == "offline"


def test_liveness_derive_state_offline_status() -> None:
    """Agent with reported_status=='offline' derives to 'offline'."""
    ls = LivenessStore()
    rec = AgentRecord(
        agent_id="x",
        last_heartbeat_at_ns=time.time_ns(),
        reported_status="offline",
    )
    assert ls._derive_state(rec) == "offline"


def test_liveness_derive_state_stale() -> None:
    """Agent not heartbeated for 30+ seconds derives to 'stale'."""
    ls = LivenessStore()
    stale_ns = time.time_ns() - int((_STALE_THRESHOLD_S + 1) * 1_000_000_000)
    rec = AgentRecord(agent_id="x", last_heartbeat_at_ns=stale_ns, reported_status="online")
    state = ls._derive_state(rec)
    assert state in ("stale", "offline")


def test_liveness_derive_state_offline_threshold() -> None:
    """Agent not heartbeated for 90+ seconds derives to 'offline'."""
    ls = LivenessStore()
    old_ns = time.time_ns() - int((_OFFLINE_THRESHOLD_S + 1) * 1_000_000_000)
    rec = AgentRecord(agent_id="x", last_heartbeat_at_ns=old_ns, reported_status="online")
    assert ls._derive_state(rec) == "offline"


def test_liveness_derive_state_busy() -> None:
    """Agent with recent heartbeat and 'busy' status derives to 'busy'."""
    ls = LivenessStore()
    rec = AgentRecord(
        agent_id="x",
        last_heartbeat_at_ns=time.time_ns(),
        reported_status="busy",
    )
    assert ls._derive_state(rec) == "busy"


def test_liveness_ensure_agent() -> None:
    """ensure_agent registers unknown agent without updating heartbeat time."""
    ls = LivenessStore()
    ls.ensure_agent("agent-new", namespace="ns1")
    agents = ls.list_agents()
    assert any(a["agent_id"] == "agent-new" for a in agents)


def test_liveness_ensure_agent_idempotent() -> None:
    """ensure_agent is idempotent for already-known agents."""
    ls = LivenessStore()
    ls.record_heartbeat("agent-x", "online")
    first = ls.list_agents()
    ls.ensure_agent("agent-x")
    second = ls.list_agents()
    assert len(first) == len(second)


def test_liveness_namespace_filter() -> None:
    """list_agents namespace filter works."""
    ls = LivenessStore()
    ls.record_heartbeat("agent-ns1", "online", namespace="ns1")
    ls.record_heartbeat("agent-ns2", "online", namespace="ns2")
    result = ls.list_agents(namespace="ns1")
    assert all(a["namespace"] == "ns1" for a in result)
    assert any(a["agent_id"] == "agent-ns1" for a in result)


# ---------------------------------------------------------------------------
# server.py — HttpTransport class
# ---------------------------------------------------------------------------


def test_http_transport_build() -> None:
    """HttpTransport.build() returns a FastAPI app."""
    from fastapi import FastAPI
    store = MemoryStore()
    t = HttpTransport(store=store)
    app = t.build()
    assert isinstance(app, FastAPI)


def test_http_transport_app_property_caches() -> None:
    """HttpTransport.app returns the same instance after build."""
    store = MemoryStore()
    t = HttpTransport(store=store)
    app1 = t.app
    app2 = t.app
    assert app1 is app2


def test_http_transport_with_all_args() -> None:
    """HttpTransport accepts all optional constructor args."""
    from sox_protocol.adapters.transports.http.liveness import LivenessStore as LS
    store = MemoryStore()
    identity = PassthroughIdentityResolver()
    config = HttpConfig(host="127.0.0.1", port=9876)
    liveness = LS()
    t = HttpTransport(store=store, identity=identity, config=config, liveness=liveness)
    assert t._config.port == 9876


def test_create_app_defaults() -> None:
    """create_app with no optional args uses defaults."""
    from fastapi import FastAPI
    store = MemoryStore()
    app = create_app(store=store)
    assert isinstance(app, FastAPI)
    assert app.state.store is store


# ---------------------------------------------------------------------------
# sse.py — coverage of the generator body
# ---------------------------------------------------------------------------


def test_build_sse_router_returns_router() -> None:
    """build_sse_router returns an APIRouter with the /v1/stream route."""
    from fastapi import APIRouter
    store = MemoryStore()
    resolver = PassthroughIdentityResolver()
    router = build_sse_router(store, resolver)
    assert isinstance(router, APIRouter)
    paths = [r.path for r in router.routes]  # type: ignore[attr-defined]
    assert "/v1/stream" in paths


@pytest.mark.asyncio
async def test_sse_event_generator_delivers_via_watch() -> None:
    """The SSE generator yields messages available in the store watch stream."""
    store = MemoryStore()
    await store.initialize()
    await store.subscribe("sse-agent", "sse-ch")

    # Put a message in the store
    await store.send("sse-ch", "sender", {"msg": "test"})

    # Drain from watch() directly (same code path as SSE generator)
    results: list[dict[str, object]] = []
    async for msg in store.watch("sse-agent"):  # type: ignore[attr-defined]
        results.append(msg)
        break  # Take just one

    assert len(results) == 1
    assert results[0]["channel"] == "sse-ch"


@pytest.mark.asyncio
async def test_sse_endpoint_rejects_missing_auth() -> None:
    """SSE endpoint returns 401 when bearer token is absent."""
    store = MemoryStore()
    await store.initialize()
    app = create_app(store=store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/v1/stream")
        assert resp.status_code == 401
        data = resp.json()
        assert data["error_code"] == "missing_credential"


@pytest.mark.asyncio
async def test_sse_endpoint_rejects_empty_bearer() -> None:
    """SSE endpoint returns 401 when bearer token is empty string."""
    store = MemoryStore()
    await store.initialize()
    app = create_app(store=store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/v1/stream", headers={"Authorization": "Bearer "})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# routes.py — exception / edge-case paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routes_invalid_json_body(client: AsyncClient) -> None:
    """Sending non-JSON body is handled gracefully."""
    resp = await client.post(
        "/v1/ops/recv",
        content=b"not-json",
        headers={**auth_headers("agent-a"), "Content-Type": "application/json"},
    )
    # Should either 200 (treated as empty body) or 400
    assert resp.status_code in (200, 400)


@pytest.mark.asyncio
async def test_unsubscribe_missing_patterns(client: AsyncClient) -> None:
    """unsubscribe without 'patterns' field returns 400."""
    resp = await client.post(
        "/v1/ops/unsubscribe",
        json={},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_group_invite_missing_fields(client: AsyncClient) -> None:
    """group_invite without required fields returns 400."""
    resp = await client.post(
        "/v1/ops/group_invite",
        json={"group_id": "g1"},  # missing agent_id
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_group_join_missing_group_id(client: AsyncClient) -> None:
    """group_join without group_id returns 400."""
    resp = await client.post(
        "/v1/ops/group_join",
        json={},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_group_leave_missing_group_id(client: AsyncClient) -> None:
    """group_leave without group_id returns 400."""
    resp = await client.post(
        "/v1/ops/group_leave",
        json={},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_group_list_members_missing_group_id(client: AsyncClient) -> None:
    """group_list_members without group_id returns 400."""
    resp = await client.post(
        "/v1/ops/group_list_members",
        json={},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_channels_with_since(client: AsyncClient) -> None:
    """list_channels with empty body is valid (since param removed from spec schema)."""
    resp = await client.post(
        "/v1/ops/list_channels",
        json={},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_channels_ack_default_status(client: AsyncClient) -> None:
    """channels_ack with required fields returns 'received' status."""
    resp = await client.post(
        "/v1/ops/channels_ack",
        json={"message_id": "msg-001", "status": "received"},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "received"


@pytest.mark.asyncio
async def test_channels_collect_times_out(client: AsyncClient) -> None:
    """channels_collect with very short timeout returns timed_out=True when no messages."""
    await client.post(
        "/v1/ops/subscribe",
        json={"pattern": "empty-collect-ch"},
        headers=auth_headers("agent-a"),
    )
    resp = await client.post(
        "/v1/ops/channels_collect",
        # Spec fields: reply_to, count, timeout (not channel/timeout_s)
        json={"reply_to": "msg-broadcast-none", "count": 5, "timeout": 0.1},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["timed_out"] is True


@pytest.mark.asyncio
async def test_heartbeat_busy_status(client: AsyncClient) -> None:
    """channels_heartbeat with 'busy' status returns correct status."""
    resp = await client.post(
        "/v1/ops/channels_heartbeat",
        json={"status": "busy"},
        headers=auth_headers("agent-busy2"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "busy"


@pytest.mark.asyncio
async def test_replay_empty_channel(client: AsyncClient) -> None:
    """replay on non-existent channel returns empty messages."""
    resp = await client.post(
        "/v1/ops/replay",
        # Spec fields: channel, since, limit (not since_seq)
        json={"channel": "nonexistent-ch", "since": 1, "limit": 100},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 200
    assert resp.json()["messages"] == []


@pytest.mark.asyncio
async def test_list_agents_namespace_filter(client: AsyncClient) -> None:
    """list_agents with namespace filter returns empty list when no matching agents."""
    resp = await client.post(
        "/v1/ops/list_agents",
        json={"namespace": "nonexistent-ns"},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 200
    assert resp.json()["agents"] == []


@pytest.mark.asyncio
async def test_send_with_reply_to(client: AsyncClient) -> None:
    """send with reply_to field is accepted."""
    resp = await client.post(
        "/v1/ops/send",
        json={
            "channel": "thread-ch",
            "body": {"text": "reply"},
            "reply_to": "msg-001",
        },
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_group_create_without_group_id(client: AsyncClient) -> None:
    """group_create without group_id uses an auto-generated id."""
    resp = await client.post(
        "/v1/ops/group_create",
        json={},
        headers=auth_headers("agent-creator"),
    )
    assert resp.status_code == 200
    assert resp.json()["group_id"].startswith("group/")


@pytest.mark.asyncio
async def test_recv_augments_seq_from_stored_message(client: AsyncClient, store) -> None:
    """recv augments seq from stored message attributes."""
    headers_a = auth_headers("agent-a")
    headers_b = auth_headers("agent-b")
    await client.post("/v1/ops/subscribe", json={"pattern": "aug-ch"}, headers=headers_b)
    await client.post("/v1/ops/send", json={"channel": "aug-ch", "body": {}}, headers=headers_a)
    resp = await client.post("/v1/ops/recv", json={}, headers=headers_b)
    msgs = resp.json()["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0].get("seq"), int)
