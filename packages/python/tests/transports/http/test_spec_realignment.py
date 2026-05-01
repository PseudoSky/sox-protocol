# SPDX-License-Identifier: Apache-2.0
"""Tests for the 04-spec-realignment fixes.

Covers:
- FIX-1: Schema-driven validation_error per op
- FIX-2: Wildcard subscription rejection (dm/*, group/*)
- FIX-3: backpressure_over_limit emission
- FIX-4: list_agents from BackingStore (not LivenessStore)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.transports.http.auth import PassthroughIdentityResolver
from sox_protocol.adapters.transports.http.config import HttpConfig
from sox_protocol.adapters.transports.http.server import create_app
from sox_protocol.core.ports.backing_store import BackpressureInfo


def auth(agent_id: str) -> dict[str, str]:
    """Return Authorization header for *agent_id*."""
    return {"Authorization": f"Bearer {agent_id}"}


@pytest_asyncio.fixture()
async def store() -> AsyncGenerator[MemoryStore, None]:
    """Fresh initialized MemoryStore."""
    s = MemoryStore()
    await s.initialize()
    yield s


@pytest_asyncio.fixture()
async def client(store: MemoryStore) -> AsyncGenerator[AsyncClient, None]:
    """ASGI test client backed by MemoryStore."""
    resolver = PassthroughIdentityResolver()
    config = HttpConfig(host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5)
    app = create_app(store=store, identity=resolver, config=config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


# ===========================================================================
# FIX-1: Schema-driven validation_error per op
# ===========================================================================


class TestSchemaValidationErrors:
    """Each op returns validation_error envelope with detail.violations on bad input."""

    @pytest.mark.asyncio
    async def test_send_missing_body_field(self, client: AsyncClient) -> None:
        """send without body returns validation_error."""
        resp = await client.post(
            "/v1/ops/send",
            json={"channel": "ch"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error_code"] == "validation_error"
        assert "violations" in data["detail"]

    @pytest.mark.asyncio
    async def test_send_missing_channel_field(self, client: AsyncClient) -> None:
        """send without channel returns validation_error."""
        resp = await client.post(
            "/v1/ops/send",
            json={"body": {"text": "hi"}},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error_code"] == "validation_error"
        assert "violations" in data["detail"]

    @pytest.mark.asyncio
    async def test_send_additional_properties_rejected(self, client: AsyncClient) -> None:
        """send with unknown field returns validation_error (additionalProperties: false)."""
        resp = await client.post(
            "/v1/ops/send",
            json={"channel": "ch", "body": {}, "unknown_field": True},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_subscribe_missing_pattern(self, client: AsyncClient) -> None:
        """subscribe without pattern returns validation_error."""
        resp = await client.post(
            "/v1/ops/subscribe",
            json={},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_unsubscribe_missing_channels(self, client: AsyncClient) -> None:
        """unsubscribe without channels returns validation_error."""
        resp = await client.post(
            "/v1/ops/unsubscribe",
            json={},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_channels_ack_missing_message_id(self, client: AsyncClient) -> None:
        """channels_ack without message_id returns validation_error."""
        resp = await client.post(
            "/v1/ops/channels_ack",
            json={"status": "received"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_channels_ack_missing_status(self, client: AsyncClient) -> None:
        """channels_ack without status returns validation_error."""
        resp = await client.post(
            "/v1/ops/channels_ack",
            json={"message_id": "msg-001"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_channels_heartbeat_missing_status(self, client: AsyncClient) -> None:
        """channels_heartbeat without status returns validation_error."""
        resp = await client.post(
            "/v1/ops/channels_heartbeat",
            json={},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_channels_collect_missing_reply_to(self, client: AsyncClient) -> None:
        """channels_collect without reply_to returns validation_error."""
        resp = await client.post(
            "/v1/ops/channels_collect",
            json={"count": 1, "timeout": 5.0},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_channels_collect_missing_count(self, client: AsyncClient) -> None:
        """channels_collect without count returns validation_error."""
        resp = await client.post(
            "/v1/ops/channels_collect",
            json={"reply_to": "msg-001", "timeout": 5.0},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_channels_collect_missing_timeout(self, client: AsyncClient) -> None:
        """channels_collect without timeout returns validation_error."""
        resp = await client.post(
            "/v1/ops/channels_collect",
            json={"reply_to": "msg-001", "count": 1},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_replay_missing_channel(self, client: AsyncClient) -> None:
        """replay without channel returns validation_error."""
        resp = await client.post(
            "/v1/ops/replay",
            json={"since": 0, "limit": 100},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_replay_missing_since(self, client: AsyncClient) -> None:
        """replay without since returns validation_error."""
        resp = await client.post(
            "/v1/ops/replay",
            json={"channel": "ch", "limit": 100},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_replay_missing_limit(self, client: AsyncClient) -> None:
        """replay without limit returns validation_error."""
        resp = await client.post(
            "/v1/ops/replay",
            json={"channel": "ch", "since": 0},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_group_invite_missing_group_id(self, client: AsyncClient) -> None:
        """group_invite without group_id returns validation_error."""
        resp = await client.post(
            "/v1/ops/group_invite",
            json={"agent_id": "agent-b"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_group_invite_missing_agent_id(self, client: AsyncClient) -> None:
        """group_invite without agent_id returns validation_error."""
        resp = await client.post(
            "/v1/ops/group_invite",
            json={"group_id": "group/eng"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_group_join_missing_group_id(self, client: AsyncClient) -> None:
        """group_join without group_id returns validation_error."""
        resp = await client.post(
            "/v1/ops/group_join",
            json={},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_group_leave_missing_group_id(self, client: AsyncClient) -> None:
        """group_leave without group_id returns validation_error."""
        resp = await client.post(
            "/v1/ops/group_leave",
            json={},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_group_list_members_missing_group_id(self, client: AsyncClient) -> None:
        """group_list_members without group_id returns validation_error."""
        resp = await client.post(
            "/v1/ops/group_list_members",
            json={},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_violation_detail_shape(self, client: AsyncClient) -> None:
        """validation_error response includes detail.violations with field+issue."""
        resp = await client.post(
            "/v1/ops/send",
            json={},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error_code"] == "validation_error"
        assert data["detail"] is not None
        violations = data["detail"]["violations"]
        assert isinstance(violations, list)
        assert len(violations) > 0
        for v in violations:
            assert "field" in v
            assert "issue" in v


# ===========================================================================
# FIX-2: Wildcard subscription rejection
# ===========================================================================


class TestWildcardSubscriptionRejection:
    """Wildcard patterns on dm/ and group/ prefixes are rejected at transport boundary."""

    @pytest.mark.asyncio
    async def test_dm_wildcard_rejected(self, client: AsyncClient) -> None:
        """subscribe with dm/* pattern returns validation_error.

        The rejection may come from the JSON Schema validator (not/anyOf clause in
        subscribe.input.schema.json) or the transport-boundary wildcard check —
        both return error_code=validation_error with status 400.
        """
        resp = await client.post(
            "/v1/ops/subscribe",
            json={"pattern": "dm/*"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_dm_wildcard_with_prefix_rejected(self, client: AsyncClient) -> None:
        """subscribe with dm/agent-alpha~* pattern returns validation_error."""
        resp = await client.post(
            "/v1/ops/subscribe",
            json={"pattern": "dm/agent-alpha~*"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_group_wildcard_rejected(self, client: AsyncClient) -> None:
        """subscribe with group/* pattern returns validation_error."""
        resp = await client.post(
            "/v1/ops/subscribe",
            json={"pattern": "group/*"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_group_wildcard_with_prefix_rejected(self, client: AsyncClient) -> None:
        """subscribe with group/eng-* wildcard returns validation_error."""
        resp = await client.post(
            "/v1/ops/subscribe",
            json={"pattern": "group/eng-*"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "validation_error"

    @pytest.mark.asyncio
    async def test_dm_exact_match_allowed(self, client: AsyncClient) -> None:
        """subscribe with exact dm/agent-a~agent-b (no wildcard) is allowed."""
        resp = await client.post(
            "/v1/ops/subscribe",
            json={"pattern": "dm/agent-a~agent-b"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_group_exact_match_allowed(self, client: AsyncClient) -> None:
        """subscribe with exact group/eng-team (no wildcard) is allowed."""
        resp = await client.post(
            "/v1/ops/subscribe",
            json={"pattern": "group/eng-team"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_regular_wildcard_allowed(self, client: AsyncClient) -> None:
        """subscribe with ticket:* wildcard (no reserved prefix) is allowed."""
        resp = await client.post(
            "/v1/ops/subscribe",
            json={"pattern": "ticket:ENGI-*"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_broadcast_wildcard_allowed(self, client: AsyncClient) -> None:
        """subscribe with broadcast:* (no reserved prefix) is allowed."""
        resp = await client.post(
            "/v1/ops/subscribe",
            json={"pattern": "broadcast:*"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_wildcard_rejection_includes_violations_detail(self, client: AsyncClient) -> None:
        """Wildcard rejection response includes detail.violations."""
        resp = await client.post(
            "/v1/ops/subscribe",
            json={"pattern": "group/*"},
            headers=auth("agent-a"),
        )
        data = resp.json()
        assert data["detail"]["violations"][0]["field"] == "pattern"


# ===========================================================================
# FIX-3: backpressure_over_limit emission
# ===========================================================================


class TestBackpressureOverLimit:
    """When BackingStore.send returns over_limit=True, op_send emits backpressure_over_limit."""

    @pytest.mark.asyncio
    async def test_backpressure_over_limit_emitted(self) -> None:
        """op_send emits backpressure_over_limit when bp.over_limit is True."""
        store = MagicMock(spec=MemoryStore)
        bp = BackpressureInfo(queue_depth=1001, threshold=1000, over_limit=True, mode="enforced")
        store.send = AsyncMock(return_value=("msg-001", 1234567890.0, 1, bp))
        resolver = PassthroughIdentityResolver()
        config = HttpConfig(host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5)
        app = create_app(store=store, identity=resolver, config=config)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
            resp = await ac.post(
                "/v1/ops/send",
                json={"channel": "busy-ch", "body": {"text": "msg"}},
                headers=auth("agent-a"),
            )
        assert resp.status_code == 429
        data = resp.json()
        assert data["error_code"] == "backpressure_over_limit"
        assert data["detail"]["queue_depth"] == 1001
        assert data["detail"]["threshold"] == 1000
        assert data["detail"]["mode"] == "enforced"

    @pytest.mark.asyncio
    async def test_send_ok_when_under_limit(self, client: AsyncClient) -> None:
        """op_send returns 200 with state=ok when queue is under threshold."""
        resp = await client.post(
            "/v1/ops/send",
            json={"channel": "normal-ch", "body": {"text": "hi"}},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["backpressure"]["state"] == "ok"
        assert data["backpressure"]["queue_depth"] < data["backpressure"]["threshold"]

    @pytest.mark.asyncio
    async def test_backpressure_detail_fields_present(self) -> None:
        """backpressure_over_limit response includes queue_depth, threshold, mode."""
        store = MagicMock(spec=MemoryStore)
        bp = BackpressureInfo(queue_depth=2000, threshold=1000, over_limit=True, mode="enforced")
        store.send = AsyncMock(return_value=("msg-x", 0.0, 1, bp))
        resolver = PassthroughIdentityResolver()
        config = HttpConfig(host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5)
        app = create_app(store=store, identity=resolver, config=config)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
            resp = await ac.post(
                "/v1/ops/send",
                json={"channel": "busy-ch", "body": {}},
                headers=auth("agent-a"),
            )
        detail = resp.json()["detail"]
        assert "queue_depth" in detail
        assert "threshold" in detail
        assert "mode" in detail


# ===========================================================================
# FIX-4: list_agents from BackingStore (not LivenessStore)
# ===========================================================================


class TestListAgentsFromBackingStore:
    """op_list_agents delegates to BackingStore.list_agents(), not LivenessStore."""

    @pytest.mark.asyncio
    async def test_list_agents_uses_backing_store(self) -> None:
        """list_agents result comes from BackingStore.list_agents()."""
        store = MagicMock(spec=MemoryStore)
        expected = [{"agent_id": "store-agent", "presence_state": "online", "last_heartbeat_at": 0, "namespace": None}]
        store.list_agents = AsyncMock(return_value=expected)
        resolver = PassthroughIdentityResolver()
        config = HttpConfig(host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5)
        app = create_app(store=store, identity=resolver, config=config)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
            resp = await ac.post(
                "/v1/ops/list_agents",
                json={},
                headers=auth("caller"),
            )
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        agent_ids = [a["agent_id"] for a in agents]
        assert "store-agent" in agent_ids

    @pytest.mark.asyncio
    async def test_list_agents_store_called_with_filters(self) -> None:
        """op_list_agents passes status_filter and namespace to BackingStore."""
        store = MagicMock(spec=MemoryStore)
        store.list_agents = AsyncMock(return_value=[])
        resolver = PassthroughIdentityResolver()
        config = HttpConfig(host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5)
        app = create_app(store=store, identity=resolver, config=config)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
            await ac.post(
                "/v1/ops/list_agents",
                json={"status_filter": ["online"], "namespace": "default"},
                headers=auth("caller"),
            )
        store.list_agents.assert_called_once_with(["online"], "default")

    @pytest.mark.asyncio
    async def test_list_agents_after_heartbeat_uses_backing_store(self, store: MemoryStore) -> None:
        """After heartbeat, list_agents returns data from BackingStore."""
        resolver = PassthroughIdentityResolver()
        config = HttpConfig(host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5)
        app = create_app(store=store, identity=resolver, config=config)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
            await ac.post(
                "/v1/ops/channels_heartbeat",
                json={"status": "online"},
                headers=auth("agent-hb"),
            )
            resp = await ac.post(
                "/v1/ops/list_agents",
                json={},
                headers=auth("caller"),
            )
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        agent_ids = [a["agent_id"] for a in agents]
        # BackingStore.heartbeat persists agent; list_agents reads from it
        assert "agent-hb" in agent_ids
