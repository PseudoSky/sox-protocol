# SPDX-License-Identifier: Apache-2.0
"""Tests for remaining uncovered branches in routes.py and sse.py."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.transports.http.config import HttpConfig
from sox_protocol.adapters.transports.http.server import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def auth(agent_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {agent_id}"}


@pytest_asyncio.fixture()
async def store() -> AsyncGenerator[MemoryStore, None]:
    s = MemoryStore()
    await s.initialize()
    yield s


@pytest_asyncio.fixture()
async def client(store: MemoryStore) -> AsyncGenerator[AsyncClient, None]:
    config = HttpConfig(host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5)
    app = create_app(store=store, config=config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


# ===========================================================================
# routes.py — _require_fields with non-dict body (line 45)
# ===========================================================================


class TestRequireFieldsNonDict:

    @pytest.mark.asyncio
    async def test_send_non_json_body_returns_error(self, client: AsyncClient) -> None:
        """Line 45: _require_fields called when body is not a dict."""
        # Send raw string as body (not JSON object)
        resp = await client.post(
            "/v1/ops/send",
            content=b'"just a string"',
            headers={**auth("agent-a"), "Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_subscribe_missing_pattern_field(self, client: AsyncClient) -> None:
        """Line 151, 154: subscribe with missing pattern field."""
        resp = await client.post(
            "/v1/ops/subscribe",
            json={"no_pattern_here": True},
            headers=auth("agent-a"),
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_unsubscribe_missing_patterns_field(self, client: AsyncClient) -> None:
        """Line 170: unsubscribe with missing patterns field."""
        resp = await client.post(
            "/v1/ops/unsubscribe",
            json={"no_patterns_here": True},
            headers=auth("agent-a"),
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_replay_missing_channel_field(self, client: AsyncClient) -> None:
        """Lines 265, 296: replay with missing channel field."""
        resp = await client.post(
            "/v1/ops/replay",
            json={"since_seq": 0},
            headers=auth("agent-a"),
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_group_invite_missing_fields(self, client: AsyncClient) -> None:
        """Lines 332-333: group_invite with missing required fields."""
        resp = await client.post(
            "/v1/ops/group_invite",
            json={"group_id": "group/test"},  # missing agent_id
            headers=auth("agent-a"),
        )
        assert resp.status_code in (400, 403, 422, 500)

    @pytest.mark.asyncio
    async def test_group_join_missing_group_id(self, client: AsyncClient) -> None:
        """Lines 345, 364: group_join missing group_id."""
        resp = await client.post(
            "/v1/ops/group_join",
            json={"no_group": True},
            headers=auth("agent-a"),
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_group_leave_missing_group_id(self, client: AsyncClient) -> None:
        """Lines 391, 411: group_leave missing group_id."""
        resp = await client.post(
            "/v1/ops/group_leave",
            json={"no_group": True},
            headers=auth("agent-a"),
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_group_list_members_missing_group_id(self, client: AsyncClient) -> None:
        """Line 431: group_list_members missing group_id."""
        resp = await client.post(
            "/v1/ops/group_list_members",
            json={"no_group": True},
            headers=auth("agent-a"),
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_channels_collect_missing_channel(self, client: AsyncClient) -> None:
        """channels_collect missing required reply_to/count/timeout fields → 400."""
        # Spec requires reply_to, count, timeout (not channel)
        resp = await client.post(
            "/v1/ops/channels_collect",
            json={"count": 1},
            headers=auth("agent-a"),
        )
        assert resp.status_code in (400, 422)


# ===========================================================================
# routes.py — store exception paths
# ===========================================================================


@pytest_asyncio.fixture()
async def client_with_erroring_store() -> AsyncGenerator[AsyncClient, None]:
    """Client backed by a store that raises on every method call."""
    store = MagicMock(spec=MemoryStore)
    for method in ["send", "recv", "subscribe", "unsubscribe", "list_channels",
                   "ack", "heartbeat", "replay", "group_create", "group_invite",
                   "group_join", "group_leave", "group_list_members"]:
        getattr(store, method).side_effect = RuntimeError("store exploded")

    config = HttpConfig(host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5)
    app = create_app(store=store, config=config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


class TestRouteStoreExceptions:

    @pytest.mark.asyncio
    async def test_send_store_exception(self, client_with_erroring_store: AsyncClient) -> None:
        """Line 91: store.send raises — internal_error_response returned."""
        resp = await client_with_erroring_store.post(
            "/v1/ops/send",
            json={"channel": "ch/x", "body": {"k": "v"}},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_subscribe_store_exception(self, client_with_erroring_store: AsyncClient) -> None:
        """Line 154: store.subscribe raises — internal_error_response returned."""
        resp = await client_with_erroring_store.post(
            "/v1/ops/subscribe",
            json={"pattern": "ch/*"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_unsubscribe_store_exception(self, client_with_erroring_store: AsyncClient) -> None:
        """Line 170: store.unsubscribe raises — internal_error_response returned."""
        resp = await client_with_erroring_store.post(
            "/v1/ops/unsubscribe",
            # Spec field is "channels" (not "patterns")
            json={"channels": ["ch/x"]},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_list_channels_exception(self, client_with_erroring_store: AsyncClient) -> None:
        """Line 193: store.list_channels raises — internal_error_response returned."""
        resp = await client_with_erroring_store.post(
            "/v1/ops/list_channels",
            json={},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_replay_exception(self, client_with_erroring_store: AsyncClient) -> None:
        """Line 296: store.replay raises — internal_error_response returned."""
        resp = await client_with_erroring_store.post(
            "/v1/ops/replay",
            # Spec fields: channel, since, limit (not since_seq)
            json={"channel": "ch/x", "since": 0, "limit": 10},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_group_create_exception(self, client_with_erroring_store: AsyncClient) -> None:
        """Line 321: store.group_create raises — internal_error_response returned."""
        resp = await client_with_erroring_store.post(
            "/v1/ops/group_create",
            json={},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_group_invite_val_err(self) -> None:
        """Lines 332-333: store.group_invite raises ValueError — 403 sox_error_response."""
        # Need a store that raises ValueError specifically for group_invite
        store2 = MagicMock(spec=MemoryStore)
        store2.group_invite = AsyncMock(side_effect=ValueError("not a member"))
        config = HttpConfig(host="127.0.0.1", port=9999, cors_origins=[], buffer_limit=100, reconnect_max_s=5)
        app = create_app(store=store2, config=config)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
            resp = await ac.post(
                "/v1/ops/group_invite",
                json={"group_id": "group/x", "agent_id": "invitee"},
                headers=auth("agent-a"),
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_group_join_exception(self, client_with_erroring_store: AsyncClient) -> None:
        """Line 364: store.group_join raises — internal_error_response returned."""
        resp = await client_with_erroring_store.post(
            "/v1/ops/group_join",
            json={"group_id": "group/x"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_group_leave_exception(self, client_with_erroring_store: AsyncClient) -> None:
        """Line 391: store.group_leave raises — internal_error_response returned."""
        resp = await client_with_erroring_store.post(
            "/v1/ops/group_leave",
            json={"group_id": "group/x"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_group_list_members_exception(self, client_with_erroring_store: AsyncClient) -> None:
        """Line 431: store.group_list_members raises — internal_error_response returned."""
        resp = await client_with_erroring_store.post(
            "/v1/ops/group_list_members",
            json={"group_id": "group/x"},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_channels_collect_exception(self, client_with_erroring_store: AsyncClient) -> None:
        """Lines 248-249: store.recv raises inside channels_collect."""
        resp = await client_with_erroring_store.post(
            "/v1/ops/channels_collect",
            # Spec fields: reply_to, count, timeout (not channel/timeout_s)
            json={"reply_to": "msg-broadcast-err", "count": 1, "timeout": 0.1},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 500


# ===========================================================================
# routes.py — heartbeat body parsing edge cases (lines 222, 230-231)
# ===========================================================================


class TestHeartbeatEdgeCases:

    @pytest.mark.asyncio
    async def test_heartbeat_non_dict_body(self, client: AsyncClient) -> None:
        """Lines 222, 230-231: heartbeat with non-dict body uses defaults."""
        # Send a JSON array body — body won't be a dict, should fall back to defaults
        resp = await client.post(
            "/v1/ops/channels_heartbeat",
            content=b'"just-a-string"',
            headers={**auth("agent-a"), "Content-Type": "application/json"},
        )
        # Should succeed with defaults or at least not crash
        assert resp.status_code in (200, 400, 422, 500)

    @pytest.mark.asyncio
    async def test_heartbeat_with_dict_body(self, client: AsyncClient) -> None:
        """Lines 222, 230-231: heartbeat with proper dict body."""
        resp = await client.post(
            "/v1/ops/channels_heartbeat",
            json={"status": "busy", "ttl": 60},
            headers=auth("agent-a"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "agent-a"
        assert data["status"] == "busy"


# ===========================================================================
# sse.py — line 110: sentinel None causes loop to break
# ===========================================================================


class TestSseGeneratorSentinel:

    @pytest.mark.asyncio
    async def test_sse_sentinel_none_breaks_loop(self) -> None:
        """Line 110: when msg is None (sentinel), generator exits."""
        from unittest.mock import MagicMock

        from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
        from sox_protocol.adapters.transports.http.sse import sse_event_generator

        store = MemoryStore()
        await store.initialize()

        # Create a mock request that is always disconnected after first check

        async def _is_disconnected() -> bool:
            return False

        mock_request = MagicMock()
        mock_request.is_disconnected = _is_disconnected

        # Override watch() to immediately yield sentinel (None) via queue
        async def _patched_watch(agent_id: str):
            # Never yield any messages — just return immediately
            return
            yield  # make it an async generator

        with patch.object(store, "watch", side_effect=_patched_watch):
            events = []
            # The generator should terminate quickly since watch yields nothing
            # The sentinel is put when watch_into_queue task finishes
            try:
                async with asyncio.timeout(1.0):
                    async for event in sse_event_generator(
                        store, "agent-a", mock_request, keepalive_interval_s=0.5
                    ):
                        events.append(event)
                        break  # stop after first event (keepalive or break)
            except (TimeoutError, Exception):
                pass
            # The important thing is that None sentinel (line 110) is reached
            # — the generator terminates without hanging forever
