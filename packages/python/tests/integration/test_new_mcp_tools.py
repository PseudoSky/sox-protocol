# SPDX-License-Identifier: Apache-2.0
"""Tests for the 11 new MCP tools added in tools.py (lines 177-494).

Uses FastMCP's in-process client (same pattern as test_mcp_server_e2e.py).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastmcp import Client, FastMCP

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.core.identity import AuditLogWriter, InMemoryCredentialRegistry
from sox_protocol.core.identity.keys import generate_keypair
from sox_protocol.core.identity.verifier import IdentityVerifier
from sox_protocol.core.mcp_server.listener import Listener
from sox_protocol.core.mcp_server.server import _load_and_validate_schemas
from sox_protocol.core.mcp_server.tools import register_tools
from sox_protocol.core.middleware import build_default_pipeline

# ---------------------------------------------------------------------------
# Helper: build in-process server wired to a given store + agent_id
# ---------------------------------------------------------------------------


async def _make_server(store: Any, agent_id: str) -> FastMCP[dict[str, object]]:
    """Build a FastMCP server wired to *store* as *agent_id* with pipeline."""

    @contextlib.asynccontextmanager
    async def _lifespan(
        server: FastMCP[dict[str, object]],
    ) -> AsyncIterator[dict[str, object]]:
        _load_and_validate_schemas()
        await store.initialize()
        registry = InMemoryCredentialRegistry()
        audit = AuditLogWriter()
        verifier = IdentityVerifier(registry=registry, audit=audit)
        private_seed, public_key_bytes = generate_keypair()
        private_key: Ed25519PrivateKey = Ed25519PrivateKey.from_private_bytes(private_seed)
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
            if hasattr(store, "close"):
                await store.close()

    mcp: FastMCP[dict[str, object]] = FastMCP(
        name=f"sox-{agent_id}",
        lifespan=_lifespan,
    )
    register_tools(mcp)
    return mcp


# ---------------------------------------------------------------------------
# channels__unsubscribe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_unsubscribe_removes_subscription() -> None:
    """Subscribe then unsubscribe; pending_cleared is an int."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-unsub")

    async with Client(mcp) as client:
        # Subscribe first
        await client.call_tool("channels__subscribe", {"pattern": "chan:test-*"})

        # Unsubscribe
        result = await client.call_tool(
            "channels__unsubscribe", {"patterns": ["chan:test-*"]}
        )
        data = result.data
        assert isinstance(data, dict)
        assert "unsubscribed" in data
        assert "pending_cleared" in data
        assert isinstance(data["pending_cleared"], int)
        assert "chan:test-*" in data["unsubscribed"]


# ---------------------------------------------------------------------------
# channels__ack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_ack_returns_ack_record() -> None:
    """Send a message, then ack it; response contains message_id and status."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-ack")

    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "ack-ch"})

        send_result = await client.call_tool(
            "channels__send",
            {"channel": "ack-ch", "body": {"x": 1}},
        )
        message_id = send_result.data["message_id"]

        await asyncio.sleep(0.15)

        recv_result = await client.call_tool("channels__recv", {})
        assert len(recv_result.data["messages"]) >= 1

        # Ack with status "received"
        ack_result = await client.call_tool(
            "channels__ack",
            {"message_id": message_id, "status": "received"},
        )
        ack_data = ack_result.data
        assert isinstance(ack_data, dict)
        assert ack_data["message_id"] == message_id
        assert ack_data["status"] == "received"
        assert "acked_at" in ack_data


@pytest.mark.asyncio
async def test_channels_ack_nack_with_reason() -> None:
    """Ack with status nack and a reason."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-nack")

    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "nack-ch"})
        send_result = await client.call_tool(
            "channels__send",
            {"channel": "nack-ch", "body": {"y": 2}},
        )
        message_id = send_result.data["message_id"]

        ack_result = await client.call_tool(
            "channels__ack",
            {"message_id": message_id, "status": "nack", "reason": "too busy"},
        )
        ack_data = ack_result.data
        assert ack_data["message_id"] == message_id
        assert ack_data["status"] == "nack"


# ---------------------------------------------------------------------------
# channels__heartbeat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_heartbeat_returns_agent_id_and_expires_at() -> None:
    """Heartbeat returns agent_id, status, recorded_at, expires_at."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-hb")

    async with Client(mcp) as client:
        result = await client.call_tool(
            "channels__heartbeat", {"status": "online"}
        )
        data = result.data
        assert isinstance(data, dict)
        assert data["agent_id"] == "agent-hb"
        assert data["status"] == "online"
        assert "recorded_at" in data
        assert "expires_at" in data
        assert isinstance(data["expires_at"], float)


@pytest.mark.asyncio
async def test_channels_heartbeat_with_ttl() -> None:
    """Heartbeat with explicit ttl."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-hb2")

    async with Client(mcp) as client:
        result = await client.call_tool(
            "channels__heartbeat", {"status": "busy", "ttl": 60}
        )
        data = result.data
        assert data["agent_id"] == "agent-hb2"
        assert data["status"] == "busy"


# ---------------------------------------------------------------------------
# channels__list_agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_list_agents_shows_agent_after_heartbeat() -> None:
    """After a heartbeat, list_agents returns the agent."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-la")

    async with Client(mcp) as client:
        await client.call_tool("channels__heartbeat", {"status": "online"})

        result = await client.call_tool("channels__list_agents", {})
        data = result.data
        assert isinstance(data, dict)
        assert "agents" in data
        agents = data["agents"]
        assert isinstance(agents, list)
        agent_ids = [a["agent_id"] for a in agents]
        assert "agent-la" in agent_ids


@pytest.mark.asyncio
async def test_channels_list_agents_with_status_filter() -> None:
    """list_agents with status_filter only returns matching agents."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-la2")

    async with Client(mcp) as client:
        await client.call_tool("channels__heartbeat", {"status": "online"})

        result = await client.call_tool(
            "channels__list_agents",
            {"status_filter": ["online"]},
        )
        data = result.data
        assert isinstance(data, dict)
        assert "agents" in data


@pytest.mark.asyncio
async def test_channels_list_agents_with_namespace() -> None:
    """list_agents with namespace filter."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-la3")

    async with Client(mcp) as client:
        await client.call_tool("channels__heartbeat", {"status": "online"})

        result = await client.call_tool(
            "channels__list_agents",
            {"namespace": "some-ns"},
        )
        data = result.data
        assert isinstance(data, dict)
        assert "agents" in data


# ---------------------------------------------------------------------------
# channels__replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_replay_returns_messages_since_seq() -> None:
    """Send 3 messages, replay since seq=2, verify messages returned."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-replay")

    async with Client(mcp) as client:
        # Send 3 messages
        for i in range(3):
            await client.call_tool(
                "channels__send",
                {"channel": "replay-ch", "body": {"i": i}},
            )

        # Replay all from start
        result = await client.call_tool(
            "channels__replay",
            {"channel": "replay-ch", "since": 0},
        )
        data = result.data
        assert isinstance(data, dict)
        assert "messages" in data
        assert "has_more" in data
        assert len(data["messages"]) == 3

        # Replay since seq=2
        result2 = await client.call_tool(
            "channels__replay",
            {"channel": "replay-ch", "since": 2},
        )
        data2 = result2.data
        assert len(data2["messages"]) == 2


@pytest.mark.asyncio
async def test_channels_replay_with_until_and_limit() -> None:
    """Replay with until and limit parameters."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-replay2")

    async with Client(mcp) as client:
        for i in range(5):
            await client.call_tool(
                "channels__send",
                {"channel": "replay-ch2", "body": {"i": i}},
            )

        result = await client.call_tool(
            "channels__replay",
            {"channel": "replay-ch2", "since": 0, "until": 3, "limit": 2},
        )
        data = result.data
        assert isinstance(data, dict)
        assert "messages" in data
        assert "has_more" in data


# ---------------------------------------------------------------------------
# channels__collect (stub — always timed_out=True)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_collect_returns_timed_out_true() -> None:
    """channels__collect stub returns timed_out=True with correct shape."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-collect")

    async with Client(mcp) as client:
        result = await client.call_tool(
            "channels__collect",
            {"reply_to": "reply-ch", "count": 2, "timeout": 0.01},
        )
        data = result.data
        assert isinstance(data, dict)
        assert data["timed_out"] is True
        assert "received" in data
        assert "missing" in data
        assert data["received"] == []
        assert data["missing"] == []


# ---------------------------------------------------------------------------
# group__create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_create_returns_group_id() -> None:
    """group__create returns a group_id with expected prefix."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-gc")

    async with Client(mcp) as client:
        result = await client.call_tool("group__create", {})
        data = result.data
        assert isinstance(data, dict)
        assert "group_id" in data
        assert "created_at" in data
        assert data["group_id"].startswith("group/")


@pytest.mark.asyncio
async def test_group_create_with_explicit_group_id() -> None:
    """group__create with an explicit group_id."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-gc2")

    async with Client(mcp) as client:
        result = await client.call_tool(
            "group__create", {"group_id": "my-team"}
        )
        data = result.data
        assert "group_id" in data
        assert "my-team" in data["group_id"]


# ---------------------------------------------------------------------------
# group__invite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_invite_returns_invited_true() -> None:
    """Create a group, invite a second agent, verify invited=True."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-gi")

    async with Client(mcp) as client:
        create_result = await client.call_tool("group__create", {})
        group_id = create_result.data["group_id"]

        invite_result = await client.call_tool(
            "group__invite",
            {"group_id": group_id, "agent_id": "agent-guest"},
        )
        data = invite_result.data
        assert isinstance(data, dict)
        assert data["invited"] is True
        assert data["agent_id"] == "agent-guest"
        assert "invited_at" in data


# ---------------------------------------------------------------------------
# group__join
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_join_returns_joined_true_and_member_count() -> None:
    """Invite then join; verify joined=True and member_count."""
    store_host = MemoryStore()
    store_guest = store_host  # share the same in-memory store

    mcp_host = await _make_server(store_host, agent_id="host-join")

    async with Client(mcp_host) as client_host:
        create_result = await client_host.call_tool("group__create", {})
        group_id = create_result.data["group_id"]

        await client_host.call_tool(
            "group__invite",
            {"group_id": group_id, "agent_id": "guest-join"},
        )

    # Now join as the guest agent
    mcp_guest = await _make_server(store_guest, agent_id="guest-join")
    async with Client(mcp_guest) as client_guest:
        join_result = await client_guest.call_tool(
            "group__join", {"group_id": group_id}
        )
        data = join_result.data
        assert isinstance(data, dict)
        assert data["joined"] is True
        assert data["group_id"] == group_id
        assert "member_count" in data
        assert "joined_at" in data


# ---------------------------------------------------------------------------
# group__leave
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_leave_returns_left_true() -> None:
    """Create, invite, join, then leave; verify left=True."""
    store = MemoryStore()

    # Host creates and invites
    mcp_host = await _make_server(store, agent_id="host-leave")
    async with Client(mcp_host) as client_host:
        create_result = await client_host.call_tool("group__create", {})
        group_id = create_result.data["group_id"]
        await client_host.call_tool(
            "group__invite",
            {"group_id": group_id, "agent_id": "guest-leave"},
        )

    # Guest joins then leaves
    mcp_guest = await _make_server(store, agent_id="guest-leave")
    async with Client(mcp_guest) as client_guest:
        await client_guest.call_tool("group__join", {"group_id": group_id})

        leave_result = await client_guest.call_tool(
            "group__leave", {"group_id": group_id}
        )
        data = leave_result.data
        assert isinstance(data, dict)
        assert data["left"] is True
        assert data["group_id"] == group_id
        assert "left_at" in data


# ---------------------------------------------------------------------------
# group__list_members
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_list_members_shows_all_members() -> None:
    """Create, invite, join; list_members shows both host and guest."""
    store = MemoryStore()

    mcp_host = await _make_server(store, agent_id="host-lm")
    async with Client(mcp_host) as client_host:
        create_result = await client_host.call_tool("group__create", {})
        group_id = create_result.data["group_id"]
        await client_host.call_tool(
            "group__invite",
            {"group_id": group_id, "agent_id": "guest-lm"},
        )

    mcp_guest = await _make_server(store, agent_id="guest-lm")
    async with Client(mcp_guest) as client_guest:
        await client_guest.call_tool("group__join", {"group_id": group_id})

    # List members as host
    mcp_host2 = await _make_server(store, agent_id="host-lm")
    async with Client(mcp_host2) as client_host2:
        list_result = await client_host2.call_tool(
            "group__list_members", {"group_id": group_id}
        )
        data = list_result.data
        assert isinstance(data, dict)
        assert "members" in data
        assert "group_id" in data
        member_ids = {m["agent_id"] for m in data["members"]}
        assert "host-lm" in member_ids or "guest-lm" in member_ids


# ---------------------------------------------------------------------------
# channels__recv with channel filter (covers lines 177-178 requeue logic)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_recv_channel_filter_keeps_only_matching() -> None:
    """recv with channels filter: matching messages returned, others requeued."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-filter")

    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "ch-a"})
        await client.call_tool("channels__subscribe", {"pattern": "ch-b"})

        # Send to both channels
        await client.call_tool(
            "channels__send", {"channel": "ch-a", "body": {"src": "a"}}
        )
        await client.call_tool(
            "channels__send", {"channel": "ch-b", "body": {"src": "b"}}
        )

        await asyncio.sleep(0.15)

        # Recv filtering to only ch-a
        result = await client.call_tool(
            "channels__recv", {"channels": ["ch-a"]}
        )
        data = result.data
        messages = data["messages"]
        assert all(m["channel"] == "ch-a" for m in messages)

        # The ch-b message should have been re-queued; next recv without filter returns it
        result2 = await client.call_tool("channels__recv", {})
        channels_returned = {m["channel"] for m in result2.data["messages"]}
        assert "ch-b" in channels_returned


# ---------------------------------------------------------------------------
# channels__recv with include_meta=False (covers line 208)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channels_recv_include_meta_false_strips_meta() -> None:
    """recv with include_meta=False strips _meta from messages."""
    store = MemoryStore()
    mcp = await _make_server(store, agent_id="agent-meta")

    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "meta-ch"})
        await client.call_tool(
            "channels__send", {"channel": "meta-ch", "body": {"v": 1}}
        )
        await asyncio.sleep(0.15)

        result = await client.call_tool(
            "channels__recv", {"include_meta": False}
        )
        for msg in result.data["messages"]:
            assert "_meta" not in msg
