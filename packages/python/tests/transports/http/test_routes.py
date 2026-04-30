# SPDX-License-Identifier: Apache-2.0
"""Per-operation contract tests for the HTTP transport routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.transports.http.conftest import auth_headers


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_basic(client: AsyncClient) -> None:
    """POST /v1/ops/send returns sent_at, message_id, seq, backpressure."""
    resp = await client.post(
        "/v1/ops/send",
        json={"channel": "test-ch", "body": {"text": "hello"}},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "sent_at" in data
    assert "message_id" in data
    assert isinstance(data["seq"], int)
    assert data["seq"] >= 1
    assert data["backpressure"]["state"] == "ok"


@pytest.mark.asyncio
async def test_send_missing_channel(client: AsyncClient) -> None:
    """POST /v1/ops/send without channel returns 400."""
    resp = await client.post(
        "/v1/ops/send",
        json={"body": {"text": "oops"}},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_send_seq_monotone(client: AsyncClient) -> None:
    """Send multiple messages and verify seq is monotonically increasing."""
    headers = auth_headers("agent-a")
    seqs = []
    for i in range(3):
        resp = await client.post(
            "/v1/ops/send",
            json={"channel": "mono-ch", "body": {"i": i}},
            headers=headers,
        )
        seqs.append(resp.json()["seq"])
    assert seqs == sorted(seqs)
    assert seqs[0] >= 1


# ---------------------------------------------------------------------------
# recv
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recv_empty(client: AsyncClient) -> None:
    """POST /v1/ops/recv returns empty messages list when nothing is queued."""
    await client.post(
        "/v1/ops/subscribe",
        json={"pattern": "empty-ch"},
        headers=auth_headers("agent-b"),
    )
    resp = await client.post(
        "/v1/ops/recv",
        json={},
        headers=auth_headers("agent-b"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["messages"] == []
    assert "drained_at" in data


@pytest.mark.asyncio
async def test_recv_returns_seq(client: AsyncClient) -> None:
    """recv response includes seq field on each message."""
    headers_a = auth_headers("agent-a")
    headers_b = auth_headers("agent-b")
    await client.post("/v1/ops/subscribe", json={"pattern": "seq-ch"}, headers=headers_b)
    await client.post("/v1/ops/send", json={"channel": "seq-ch", "body": {}}, headers=headers_a)
    resp = await client.post("/v1/ops/recv", json={}, headers=headers_b)
    msgs = resp.json()["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0]["seq"], int)
    assert msgs[0]["seq"] >= 1


@pytest.mark.asyncio
async def test_recv_channel_filter(client: AsyncClient) -> None:
    """recv with channels filter returns only messages from listed channels."""
    headers_a = auth_headers("agent-a")
    headers_b = auth_headers("agent-b")
    await client.post("/v1/ops/subscribe", json={"pattern": "ch-*"}, headers=headers_b)
    await client.post("/v1/ops/send", json={"channel": "ch-one", "body": {"x": 1}}, headers=headers_a)
    await client.post("/v1/ops/send", json={"channel": "ch-two", "body": {"x": 2}}, headers=headers_a)
    resp = await client.post(
        "/v1/ops/recv",
        json={"channels": ["ch-one"]},
        headers=headers_b,
    )
    msgs = resp.json()["messages"]
    assert all(m["channel"] == "ch-one" for m in msgs)


# ---------------------------------------------------------------------------
# subscribe / unsubscribe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_returns_matched_channels(client: AsyncClient) -> None:
    """subscribe returns currently matching channels."""
    # First send a message so a channel exists
    await client.post(
        "/v1/ops/send",
        json={"channel": "ticket:ENGI-001", "body": {}},
        headers=auth_headers("agent-x"),
    )
    resp = await client.post(
        "/v1/ops/subscribe",
        json={"pattern": "ticket:*"},
        headers=auth_headers("agent-b"),
    )
    assert resp.status_code == 200
    assert "subscribed" in resp.json()


@pytest.mark.asyncio
async def test_unsubscribe(client: AsyncClient) -> None:
    """unsubscribe removes the pattern."""
    headers = auth_headers("agent-c")
    await client.post("/v1/ops/subscribe", json={"pattern": "rm-ch"}, headers=headers)
    resp = await client.post(
        "/v1/ops/unsubscribe",
        json={"patterns": ["rm-ch"]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert "rm-ch" in resp.json()["unsubscribed"]


# ---------------------------------------------------------------------------
# list_channels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_channels(client: AsyncClient) -> None:
    """list_channels returns channels and protocol_version."""
    await client.post(
        "/v1/ops/send",
        json={"channel": "list-me", "body": {}},
        headers=auth_headers("agent-a"),
    )
    resp = await client.post(
        "/v1/ops/list_channels",
        json={},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "channels" in data
    assert data["protocol_version"] == "1.0"


# ---------------------------------------------------------------------------
# channels_ack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_ack(client: AsyncClient) -> None:
    """channels_ack returns acked_at and status."""
    resp = await client.post(
        "/v1/ops/channels_ack",
        json={"message_id": "msg-001", "status": "received"},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "acked_at" in data
    assert data["status"] == "received"


# ---------------------------------------------------------------------------
# channels_heartbeat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_heartbeat(client: AsyncClient, liveness) -> None:
    """channels_heartbeat updates liveness store and returns recorded_at."""
    resp = await client.post(
        "/v1/ops/channels_heartbeat",
        json={"status": "online"},
        headers=auth_headers("agent-hb"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "recorded_at" in data
    assert data["status"] == "online"
    # Liveness store should now know about agent-hb
    agents = liveness.list_agents()
    agent_ids = [a["agent_id"] for a in agents]
    assert "agent-hb" in agent_ids


# ---------------------------------------------------------------------------
# channels_collect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_collect_immediate(client: AsyncClient) -> None:
    """channels_collect returns immediately when messages are already available."""
    headers_a = auth_headers("agent-a")
    headers_b = auth_headers("agent-b")
    await client.post("/v1/ops/subscribe", json={"pattern": "collect-ch"}, headers=headers_b)
    await client.post("/v1/ops/send", json={"channel": "collect-ch", "body": {"n": 1}}, headers=headers_a)
    resp = await client.post(
        "/v1/ops/channels_collect",
        json={"channel": "collect-ch", "count": 1, "timeout_s": 5.0},
        headers=headers_b,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["messages"]) == 1
    assert data["timed_out"] is False


@pytest.mark.asyncio
async def test_channels_collect_missing_channel(client: AsyncClient) -> None:
    """channels_collect without channel returns 400."""
    resp = await client.post(
        "/v1/ops/channels_collect",
        json={"count": 1},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_since_seq(client: AsyncClient) -> None:
    """replay returns messages with seq >= since_seq."""
    headers = auth_headers("agent-r")
    # Send 3 messages
    for i in range(3):
        await client.post(
            "/v1/ops/send",
            json={"channel": "replay-ch", "body": {"i": i}},
            headers=headers,
        )
    # Replay since seq=2
    resp = await client.post(
        "/v1/ops/replay",
        json={"channel": "replay-ch", "since_seq": 2},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    assert "has_more" in data
    for msg in data["messages"]:
        assert msg["seq"] >= 2


@pytest.mark.asyncio
async def test_replay_missing_channel(client: AsyncClient) -> None:
    """replay without channel returns 400."""
    resp = await client.post(
        "/v1/ops/replay",
        json={"since_seq": 1},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_agents_empty(client: AsyncClient) -> None:
    """list_agents returns empty list when no heartbeats recorded."""
    resp = await client.post(
        "/v1/ops/list_agents",
        json={},
        headers=auth_headers("agent-a"),
    )
    assert resp.status_code == 200
    assert resp.json()["agents"] == []


@pytest.mark.asyncio
async def test_list_agents_after_heartbeat(client: AsyncClient, liveness) -> None:
    """list_agents reflects agents after heartbeat."""
    await client.post(
        "/v1/ops/channels_heartbeat",
        json={"status": "online"},
        headers=auth_headers("agent-x"),
    )
    resp = await client.post(
        "/v1/ops/list_agents",
        json={},
        headers=auth_headers("agent-a"),
    )
    agents = resp.json()["agents"]
    assert any(a["agent_id"] == "agent-x" for a in agents)


@pytest.mark.asyncio
async def test_list_agents_status_filter(client: AsyncClient, liveness) -> None:
    """list_agents with status_filter only returns matching agents."""
    await client.post(
        "/v1/ops/channels_heartbeat",
        json={"status": "busy"},
        headers=auth_headers("agent-busy"),
    )
    await client.post(
        "/v1/ops/channels_heartbeat",
        json={"status": "online"},
        headers=auth_headers("agent-online"),
    )
    resp = await client.post(
        "/v1/ops/list_agents",
        json={"status_filter": ["busy"]},
        headers=auth_headers("agent-a"),
    )
    agents = resp.json()["agents"]
    assert all(a["presence_state"] == "busy" for a in agents)


# ---------------------------------------------------------------------------
# DM channel naming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dm_sorted_pair_naming(client: AsyncClient) -> None:
    """DM channels use dm/<sorted-pair> naming convention."""
    headers_a = auth_headers("agent-alice")
    headers_b = auth_headers("agent-bob")
    # Subscribe bob to the DM channel
    dm_channel = "dm/agent-alice~agent-bob"
    await client.post("/v1/ops/subscribe", json={"pattern": dm_channel}, headers=headers_b)
    await client.post(
        "/v1/ops/send",
        json={"channel": dm_channel, "body": {"text": "hi bob"}},
        headers=headers_a,
    )
    resp = await client.post("/v1/ops/recv", json={}, headers=headers_b)
    msgs = resp.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["channel"] == dm_channel


# ---------------------------------------------------------------------------
# Group operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_create(client: AsyncClient) -> None:
    """group_create returns group_id and created_at."""
    resp = await client.post(
        "/v1/ops/group_create",
        json={"group_id": "my-group"},
        headers=auth_headers("agent-creator"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "group/" in data["group_id"]
    assert "created_at" in data


@pytest.mark.asyncio
async def test_group_invite_join_members(client: AsyncClient) -> None:
    """Full group lifecycle: create -> invite -> join -> list_members."""
    headers_a = auth_headers("agent-leader")
    headers_b = auth_headers("agent-member")

    create_resp = await client.post(
        "/v1/ops/group_create",
        json={"group_id": "team-alpha"},
        headers=headers_a,
    )
    group_id = create_resp.json()["group_id"]

    invite_resp = await client.post(
        "/v1/ops/group_invite",
        json={"group_id": group_id, "agent_id": "agent-member"},
        headers=headers_a,
    )
    assert invite_resp.status_code == 200

    join_resp = await client.post(
        "/v1/ops/group_join",
        json={"group_id": group_id},
        headers=headers_b,
    )
    assert join_resp.status_code == 200

    members_resp = await client.post(
        "/v1/ops/group_list_members",
        json={"group_id": group_id},
        headers=headers_a,
    )
    members = members_resp.json()["members"]
    agent_ids = [m["agent_id"] for m in members]
    assert "agent-leader" in agent_ids
    assert "agent-member" in agent_ids


@pytest.mark.asyncio
async def test_group_leave(client: AsyncClient) -> None:
    """group_leave removes member from group."""
    headers_a = auth_headers("agent-host")
    headers_b = auth_headers("agent-guest")

    create_resp = await client.post(
        "/v1/ops/group_create",
        json={"group_id": "leave-test"},
        headers=headers_a,
    )
    group_id = create_resp.json()["group_id"]

    await client.post(
        "/v1/ops/group_invite",
        json={"group_id": group_id, "agent_id": "agent-guest"},
        headers=headers_a,
    )
    await client.post("/v1/ops/group_join", json={"group_id": group_id}, headers=headers_b)

    leave_resp = await client.post(
        "/v1/ops/group_leave",
        json={"group_id": group_id},
        headers=headers_b,
    )
    assert leave_resp.status_code == 200

    members_resp = await client.post(
        "/v1/ops/group_list_members",
        json={"group_id": group_id},
        headers=headers_a,
    )
    members = members_resp.json()["members"]
    assert not any(m["agent_id"] == "agent-guest" for m in members)


@pytest.mark.asyncio
async def test_group_invite_not_member_rejected(client: AsyncClient) -> None:
    """group_invite by non-member returns 403."""
    headers_a = auth_headers("agent-owner")
    headers_b = auth_headers("agent-outsider")

    create_resp = await client.post(
        "/v1/ops/group_create",
        json={"group_id": "private-group"},
        headers=headers_a,
    )
    group_id = create_resp.json()["group_id"]

    resp = await client.post(
        "/v1/ops/group_invite",
        json={"group_id": group_id, "agent_id": "agent-target"},
        headers=headers_b,
    )
    assert resp.status_code == 403
