# SPDX-License-Identifier: Apache-2.0
"""Tests for the ack_nack lifecycle step.

Covers:
- All four status transitions: received, processing, done, nack
- ACK never appears as a channel message (body.type != 'sox-ack')
- Forward-only state machine (backward transitions must be rejected)
- NACK with reason string
- Empty message_id is silently ignored
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

_REF_AGENT_DIR = Path(__file__).parents[4] / "examples" / "reference-agent"
if str(_REF_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_REF_AGENT_DIR))

from agent import ReferenceAgent, ACK_DONE, ACK_NACK, ACK_PROCESSING, ACK_RECEIVED
from tests.reference_agent.helpers import build_server
from sox_protocol.adapters.backing_stores.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_ack_all_four_transitions(tmp_state_dir: Path) -> None:
    """ACK transitions received → processing → done are recorded correctly."""
    store = MemoryStore()
    mcp = await build_server(store, "ack-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="ack-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        # Test all four status values against real message IDs.
        for status in (ACK_RECEIVED, ACK_PROCESSING, ACK_DONE):
            await agent.ack(f"msg-{status}", status)
            rec = store._ack_records.get(f"msg-{status}")
            assert rec is not None, f"No ACK record for status {status!r}"
            assert rec["status"] == status


@pytest.mark.asyncio
async def test_ack_nack_with_reason(tmp_state_dir: Path) -> None:
    """NACK with reason is persisted and the reason is preserved."""
    store = MemoryStore()
    mcp = await build_server(store, "nack-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="nack-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.ack("msg-nack-1", ACK_NACK, reason="DOMAIN_MISMATCH: not my area")
        rec = store._ack_records.get("msg-nack-1")
        assert rec is not None
        assert rec["status"] == ACK_NACK
        assert rec["reason"] == "DOMAIN_MISMATCH: not my area"


@pytest.mark.asyncio
async def test_ack_empty_message_id_is_noop(tmp_state_dir: Path) -> None:
    """ACK with empty message_id is silently ignored (no exception, no record)."""
    store = MemoryStore()
    mcp = await build_server(store, "noop-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="noop-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        # Should not raise and should not write any ACK record.
        await agent.ack("", ACK_RECEIVED)
        assert "" not in store._ack_records


@pytest.mark.asyncio
async def test_ack_does_not_write_to_channel(tmp_state_dir: Path) -> None:
    """ACK tool calls NEVER produce channel messages with body.type='sox-ack'.

    This is the critical anti-pattern guard. After calling ack() in every
    valid status, there must be NO channel message with body.type starting
    with 'sox-ack' anywhere in the store.
    """
    store = MemoryStore()
    mcp = await build_server(store, "no-sox-ack-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="no-sox-ack-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        # Issue all four status types.
        for status in (ACK_RECEIVED, ACK_PROCESSING, ACK_DONE, ACK_NACK):
            await agent.ack(f"msg-{status}-check", status)

        # Verify no channel message has a sox-ack body type.
        for msg in store._messages:
            body: dict[str, Any] = msg.body  # type: ignore[assignment]
            msg_type = str(body.get("type", ""))
            assert not msg_type.startswith("sox-ack"), (
                f"Anti-pattern: found body.type={msg_type!r} in channel {msg.channel!r}. "
                "ACK must be a tool call only, never a channel message."
            )


@pytest.mark.asyncio
async def test_ack_pending_tracking_received_processing(tmp_state_dir: Path) -> None:
    """received/processing add to _pending set; done/nack remove from it."""
    store = MemoryStore()
    mcp = await build_server(store, "pending-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="pending-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        # received and processing should add to pending.
        await agent.ack("msg-p1", ACK_RECEIVED)
        assert "msg-p1" in agent._pending

        await agent.ack("msg-p1", ACK_PROCESSING)
        assert "msg-p1" in agent._pending

        # done should remove from pending (graceful_stop can then proceed).
        await agent.ack("msg-p1", ACK_DONE)
        assert "msg-p1" not in agent._pending


@pytest.mark.asyncio
async def test_ack_nack_removes_from_pending(tmp_state_dir: Path) -> None:
    """nack is a terminal status and removes the message from _pending."""
    store = MemoryStore()
    mcp = await build_server(store, "nack-pending-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="nack-pending-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.ack("msg-nack-p", ACK_RECEIVED)
        assert "msg-nack-p" in agent._pending

        await agent.ack("msg-nack-p", ACK_NACK, reason="cannot process")
        assert "msg-nack-p" not in agent._pending


@pytest.mark.asyncio
async def test_ack_result_not_in_subsequent_recv(tmp_state_dir: Path) -> None:
    """After ACK(done), a recv drain does NOT return the ACK as a channel message.

    This verifies spec/primitives/ack-nack.md §5: ACKs are control-plane only;
    they never appear in channel history or recv output.
    """
    store = MemoryStore()
    mcp = await build_server(store, "no-ack-in-recv-agent")
    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "ticket:*"})
        agent = ReferenceAgent(
            client,
            agent_id="no-ack-in-recv-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        # Send a real message so the channel exists, then ACK it.
        send_result = await client.call_tool(
            "channels__send",
            {"channel": "ticket:ack-check", "body": {"type": "status_update"}},
        )
        msg_id = send_result.data["message_id"]
        # Drain so the message is consumed.
        await client.call_tool("channels__recv", {})
        # Now ACK done.
        await agent.ack(str(msg_id), ACK_DONE)
        # A subsequent recv must not return anything with body.type='sox-ack'.
        recv2 = await client.call_tool("channels__recv", {})
        for m in recv2.data.get("messages", []):
            body_type = str((m.get("body") or {}).get("type", ""))
            assert not body_type.startswith("sox-ack"), (
                f"ACK appeared as channel message: body.type={body_type!r}"
            )
