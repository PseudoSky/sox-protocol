# SPDX-License-Identifier: Apache-2.0
"""Integration tests: reference agent + partner agent end-to-end exchange.

These tests spin up two in-process FastMCP servers sharing a MemoryStore,
then drive a scripted exchange via SOX to verify the full protocol lifecycle:

Scenarios:
1. Clarification request/reply round-trip with ACK lifecycle.
2. DM round-trip (direct message between two agents).
3. Group fan-out: create group, invite+join, broadcast, verify receipt.
4. Kill-and-recover via replay (simulated crash mid-conversation).
5. graceful_stop refuses to exit while a message is pending.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

_REF_AGENT_DIR = Path(__file__).parents[4] / "examples" / "reference-agent"
if str(_REF_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_REF_AGENT_DIR))

from agent import ReferenceAgent, ACK_DONE, ACK_NACK, ACK_RECEIVED
from tests.reference_agent.helpers import build_server
from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from state import SeqState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_body_type(
    messages: list[dict[str, Any]], msg_type: str
) -> dict[str, Any] | None:
    """Return the first message whose body['type'] == msg_type."""
    for m in messages:
        if isinstance(m.get("body"), dict) and m["body"].get("type") == msg_type:
            return m
    return None


# ---------------------------------------------------------------------------
# Scenario 1: Clarification request → reply round-trip with ACK lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clarification_round_trip(tmp_path: Path) -> None:
    """Reference agent sends clarification_request; partner replies; agent reconciles.

    Full ACK lifecycle verified:
    - reference agent: received → processing → done for the reply
    - partner agent: received → processing → done for the request
    """
    store = MemoryStore()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    mcp_ref = await build_server(store, "ref-agent")
    mcp_partner = await build_server(store, "partner-agent")

    async with Client(mcp_ref) as ref_client, Client(mcp_partner) as partner_client:
        # Build the reference agent.
        ref_agent = ReferenceAgent(
            ref_client,
            agent_id="ref-agent",
            namespace="reference",
            state_dir=state_dir,
        )
        # Bootstrap both agents (subscribes to ticket:* and sox/presence).
        await ref_agent.bootstrap()
        # Partner subscribes to the ticket channel directly.
        await partner_client.call_tool("channels__subscribe", {"pattern": "ticket:*"})

        # Ref agent sends a clarification_request.
        send_result = await ref_client.call_tool(
            "channels__send",
            {
                "channel": "ticket:integration-001",
                "body": {
                    "type": "clarification_request",
                    "subject": "Integration test clarification",
                    "question": "15 min or 24 h for token TTL?",
                    "urgency": "normal",
                },
                "correlation_id": "integ-001",
            },
        )
        assert "message_id" in send_result.data
        request_msg_id: str = str(send_result.data["message_id"])

        # Let the listener push the message to the partner.
        await asyncio.sleep(0.15)

        # Partner drains and finds the request.
        drain = await partner_client.call_tool("channels__recv", {})
        messages: list[dict[str, Any]] = drain.data.get("messages", [])
        req = _find_body_type(messages, "clarification_request")
        assert req is not None, f"Partner expected clarification_request, got: {messages}"
        assert req["correlation_id"] == "integ-001"
        assert req["sender"] == "ref-agent"

        # Partner ACKs the request through the full lifecycle.
        partner_msg_id = str(req["message_id"])
        await partner_client.call_tool(
            "channels__ack", {"message_id": partner_msg_id, "status": "received"}
        )
        await partner_client.call_tool(
            "channels__ack", {"message_id": partner_msg_id, "status": "processing"}
        )

        # Partner sends the reply on the SAME channel.
        # reply_to is embedded in body._reply_to since the v1 send tool
        # does not expose reply_to as a top-level parameter.
        await partner_client.call_tool(
            "channels__send",
            {
                "channel": "ticket:integration-001",
                "body": {
                    "type": "clarification_reply",
                    "subject": "Integration test clarification",
                    "answer": "15 minutes (900 s) confirmed by security policy.",
                    "_reply_to": partner_msg_id,
                },
                "correlation_id": "integ-001",
            },
        )
        await partner_client.call_tool(
            "channels__ack", {"message_id": partner_msg_id, "status": "done"}
        )

        # Let the listener push the reply to the ref agent.
        await asyncio.sleep(0.15)

        # Ref agent drains and reconciles.
        drain2 = await ref_client.call_tool("channels__recv", {})
        msgs2: list[dict[str, Any]] = drain2.data.get("messages", [])
        reply = _find_body_type(msgs2, "clarification_reply")
        assert reply is not None, f"Ref expected clarification_reply, got: {msgs2}"
        assert reply["correlation_id"] == "integ-001"
        assert "900" in str(reply["body"].get("answer", ""))

        # Ref agent processes the reply through handle_message.
        await ref_agent.handle_message(reply)

        # Verify ACK record for the reply is terminal.
        reply_ack = store._ack_records.get(str(reply["message_id"]))
        assert reply_ack is not None
        assert reply_ack["status"] == ACK_DONE


# ---------------------------------------------------------------------------
# Scenario 2: DM round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dm_round_trip(tmp_path: Path) -> None:
    """Direct message from partner to ref-agent is received and processed."""
    store = MemoryStore()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    mcp_ref = await build_server(store, "dm-ref")
    mcp_partner = await build_server(store, "dm-partner")

    async with Client(mcp_ref) as ref_client, Client(mcp_partner) as partner_client:
        ref_agent = ReferenceAgent(
            ref_client,
            agent_id="dm-ref",
            namespace="reference",
            state_dir=state_dir,
        )
        await ref_agent.bootstrap()

        # DM channel name: dm/<sorted-pair> — dm-partner < dm-ref alphabetically.
        # Per spec/primitives/dms.md, the two agent IDs are sorted lexicographically.
        dm_channel = "dm/dm-partner~dm-ref"

        # Subscribe to the exact DM channel name — wildcards on dm/ are forbidden.
        await ref_client.call_tool(
            "channels__subscribe", {"pattern": dm_channel}
        )
        # Partner also subscribes to the exact DM channel for send/recv.
        await partner_client.call_tool(
            "channels__subscribe", {"pattern": dm_channel}
        )
        await partner_client.call_tool(
            "channels__send",
            {
                "channel": dm_channel,
                "body": {
                    "type": "clarification_request",
                    "subject": "Private query",
                    "question": "Are you available?",
                },
            },
        )
        await asyncio.sleep(0.15)

        # Ref agent drains — DM should appear because it subscribed to dm/*~dm-ref.
        drain = await ref_client.call_tool("channels__recv", {})
        dm_msgs: list[dict[str, Any]] = drain.data.get("messages", [])
        dm_msg = _find_body_type(dm_msgs, "clarification_request")
        assert dm_msg is not None, f"Ref expected DM, got: {dm_msgs}"
        assert dm_msg["channel"] == dm_channel

        # Process the DM through the agent's handler.
        await ref_agent.handle_message(dm_msg)

        # Verify the reply was sent on the same DM channel.
        replies = [
            m for m in store._messages
            if m.channel == dm_channel and m.sender == "dm-ref"
        ]
        assert len(replies) >= 1


# ---------------------------------------------------------------------------
# Scenario 3: Group fan-out and ACK count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_fanout_and_ack(tmp_path: Path) -> None:
    """Group create → invite → join → broadcast → individual ACKs per recipient."""
    store = MemoryStore()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    mcp_creator = await build_server(store, "group-creator")
    mcp_member = await build_server(store, "group-member")

    async with Client(mcp_creator) as creator_client, Client(mcp_member) as member_client:
        creator = ReferenceAgent(
            creator_client,
            agent_id="group-creator",
            namespace="reference",
            state_dir=state_dir,
        )
        member = ReferenceAgent(
            member_client,
            agent_id="group-member",
            namespace="reference",
            state_dir=state_dir / "member",
        )
        (state_dir / "member").mkdir()

        await creator.bootstrap()
        await member.bootstrap()

        # Step 1: creator creates the group.
        group_result = await creator.group_create("test-group")
        group_id: str = str(group_result["group_id"])
        assert group_id == "group/test-group"

        # Step 2: creator invites group-member.
        invite_result = await creator.group_invite(group_id, "group-member")
        assert invite_result["invited"] is True

        # Step 3: member accepts the invitation.
        join_result = await member.group_join(group_id)
        assert join_result["joined"] is True

        # Step 4: verify membership via group_list_members.
        members = await creator.group_list_members(group_id)
        agent_ids = {m["agent_id"] for m in members}
        assert "group-creator" in agent_ids
        assert "group-member" in agent_ids

        # Step 5: creator broadcasts to the group.
        send_result = await creator_client.call_tool(
            "channels__send",
            {
                "channel": group_id,
                "body": {
                    "type": "status_update",
                    "subject": "Group broadcast test",
                },
            },
        )
        assert "message_id" in send_result.data

        # Let the listener push the message.
        await asyncio.sleep(0.15)

        # Step 6: member drains and receives the broadcast.
        drain = await member_client.call_tool("channels__recv", {})
        group_msgs: list[dict[str, Any]] = drain.data.get("messages", [])
        broadcast = _find_body_type(group_msgs, "status_update")
        assert broadcast is not None, f"Member expected status_update, got: {group_msgs}"

        # Step 7: member ACKs done — individual ACK per recipient (spec §8).
        broadcast_id = str(broadcast["message_id"])
        await member.ack(broadcast_id, ACK_RECEIVED)
        await member.ack(broadcast_id, ACK_DONE)
        rec = store._ack_records.get(broadcast_id)
        assert rec is not None
        assert rec["status"] == ACK_DONE

        # Step 8: member leaves the group.
        leave_result = await member.group_leave(group_id)
        assert leave_result["left"] is True


# ---------------------------------------------------------------------------
# Scenario 4: Kill-and-recover via replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kill_and_recover_via_replay(tmp_path: Path) -> None:
    """Agent restart replays missed messages; no duplicates delivered."""
    store = MemoryStore()
    await store.initialize()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # "First run": agent sees msg at seq=1 but crashes before seeing seq=2.
    await store.send("ticket:crash-test", "sender", {"type": "status_update", "run": 1})
    await store.send("ticket:crash-test", "sender", {"type": "status_update", "run": 2})

    # Simulate: first run processed seq=1 and persisted it.
    seq_state = SeqState(state_dir / "seq.json")
    seq_state.save({"ticket:crash-test": 1})

    mcp = await build_server(store, "crash-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="crash-agent",
            namespace="reference",
            state_dir=state_dir,
        )
        await agent.bootstrap()

        # Track which seqs were processed during recovery.
        processed_seqs: list[int] = []
        original_handle = agent.handle_message

        async def _track(envelope: dict[str, Any]) -> None:
            processed_seqs.append(int(envelope.get("seq", 0)))
            await original_handle(envelope)

        agent.handle_message = _track  # type: ignore[method-assign]
        await agent.recover_from_state()

        # Only seq=2 should be replayed (since=1 is exclusive, seq > 1).
        assert 2 in processed_seqs, f"seq=2 not replayed; got {processed_seqs}"
        assert 1 not in processed_seqs, f"seq=1 duplicated; got {processed_seqs}"

        # After recovery, cursor is updated.
        saved = seq_state.load()
        assert saved.get("ticket:crash-test", 0) >= 2


# ---------------------------------------------------------------------------
# Scenario 5: graceful_stop refuses while pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_stop_blocks_on_pending(tmp_path: Path) -> None:
    """graceful_stop does not exit while a message is in processing state."""
    store = MemoryStore()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    mcp = await build_server(store, "stop-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="stop-agent",
            namespace="reference",
            state_dir=state_dir,
        )
        await agent.bootstrap()

        # Manually put a message in pending state (simulates mid-processing).
        agent._pending.add("blocked-msg")

        # graceful_stop should block — resolve after 0.3s.
        async def _resolve_pending() -> None:
            await asyncio.sleep(0.3)
            agent._pending.discard("blocked-msg")

        resolve_task = asyncio.create_task(_resolve_pending())

        # Should complete within 2s once the pending is cleared.
        await asyncio.wait_for(agent.graceful_stop(), timeout=2.0)
        await resolve_task

        # Offline heartbeat must have been emitted.
        liveness = store._liveness.get("stop-agent")
        assert liveness is not None
        assert liveness["status"] == "offline"
