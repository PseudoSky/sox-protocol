# SPDX-License-Identifier: Apache-2.0
"""Tests for thread_handling lifecycle step.

Covers:
- reply_to is set to parent message_id
- reply stays on the same channel (not a sub-channel)
- correlation_id is propagated from parent
- thread_depth=-1 accepted (full ancestor chain parameter)
- clarification_reply integrated non-destructively
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

from agent import ReferenceAgent
from tests.reference_agent.helpers import build_server
from sox_protocol.adapters.backing_stores.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_reply_to_set_to_parent_message_id(tmp_state_dir: Path) -> None:
    """reply_to_request sets reply_to = parent.message_id on same channel."""
    store = MemoryStore()
    mcp = await build_server(store, "thread-agent")
    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "ticket:*"})

        # Send the parent message via the store.
        parent_id, _, _, _ = await store.send(
            "ticket:thread-test",
            "parent-sender",
            {
                "type": "clarification_request",
                "subject": "Thread test",
                "question": "What should we do?",
            },
            correlation_id="corr-001",
        )

        agent = ReferenceAgent(
            client,
            agent_id="thread-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        # Build a fake parent envelope matching what recv would return.
        parent_envelope: dict[str, Any] = {
            "message_id": parent_id,
            "channel": "ticket:thread-test",
            "sender": "parent-sender",
            "body": {
                "type": "clarification_request",
                "subject": "Thread test",
                "question": "What should we do?",
            },
            "correlation_id": "corr-001",
            "seq": 1,
            "reply_to": None,
        }

        # Call reply_to_request directly — this is the threading primitive.
        reply_body: dict[str, Any] = {
            "type": "clarification_reply",
            "answer": "We should proceed with option A.",
        }
        await agent.reply_to_request(parent_envelope, reply_body)

        # Find the reply in the store and verify _reply_to is set in body.
        # (channels__send v1 does not expose reply_to as a tool parameter;
        #  the reference agent embeds it in body._reply_to for linking.)
        reply_msgs = [
            m for m in store._messages
            if m.channel == "ticket:thread-test" and m.sender == "thread-agent"
        ]
        assert len(reply_msgs) >= 1
        reply_msg = reply_msgs[-1]
        # _reply_to in the body links this reply to its parent message.
        assert reply_msg.body.get("_reply_to") == parent_id, (
            f"Expected body._reply_to={parent_id!r}, got {reply_msg.body.get('_reply_to')!r}"
        )


@pytest.mark.asyncio
async def test_reply_stays_on_same_channel(tmp_state_dir: Path) -> None:
    """Replies are sent to the SAME channel as the parent, not a sub-channel."""
    store = MemoryStore()
    mcp = await build_server(store, "channel-agent")
    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "ticket:*"})
        parent_id, _, _, _ = await store.send(
            "ticket:same-channel",
            "sender",
            {"type": "clarification_request", "subject": "s", "question": "q"},
        )
        agent = ReferenceAgent(
            client,
            agent_id="channel-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        parent_envelope: dict[str, Any] = {
            "message_id": parent_id,
            "channel": "ticket:same-channel",
            "sender": "sender",
            "body": {"type": "clarification_request"},
            "correlation_id": None,
            "seq": 1,
        }
        await agent.reply_to_request(parent_envelope, {"type": "clarification_reply", "answer": "a"})

        # Reply must be on ticket:same-channel, not thread:<parent_id>.
        reply_msgs = [
            m for m in store._messages
            if m.sender == "channel-agent"
        ]
        assert len(reply_msgs) >= 1
        for rm in reply_msgs:
            assert rm.channel == "ticket:same-channel", (
                f"Reply on wrong channel: {rm.channel!r} (should be ticket:same-channel)"
            )
            # Ensure no thread: sub-channel was created.
            assert not rm.channel.startswith("thread:"), (
                f"Anti-pattern: reply created a thread sub-channel {rm.channel!r}"
            )


@pytest.mark.asyncio
async def test_correlation_id_propagated(tmp_state_dir: Path) -> None:
    """reply_to_request propagates parent correlation_id to the reply."""
    store = MemoryStore()
    mcp = await build_server(store, "corr-agent")
    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "ticket:*"})
        parent_id, _, _, _ = await store.send(
            "ticket:corr-test",
            "sender",
            {"type": "clarification_request", "subject": "s", "question": "q"},
            correlation_id="my-corr-id",
        )
        agent = ReferenceAgent(
            client,
            agent_id="corr-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        parent_envelope: dict[str, Any] = {
            "message_id": parent_id,
            "channel": "ticket:corr-test",
            "sender": "sender",
            "body": {"type": "clarification_request"},
            "correlation_id": "my-corr-id",
            "seq": 1,
        }
        await agent.reply_to_request(parent_envelope, {"type": "clarification_reply", "answer": "a"})

        # Find the reply and check correlation_id was propagated.
        reply_msgs = [m for m in store._messages if m.sender == "corr-agent"]
        assert len(reply_msgs) >= 1
        assert reply_msgs[-1].correlation_id == "my-corr-id"


@pytest.mark.asyncio
async def test_handle_clarification_reply_acks_done(tmp_state_dir: Path) -> None:
    """Receiving a clarification_reply ACKs it done (non-destructive integration)."""
    store = MemoryStore()
    mcp = await build_server(store, "recv-reply-agent")
    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "ticket:*"})
        agent = ReferenceAgent(
            client,
            agent_id="recv-reply-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        reply_envelope: dict[str, Any] = {
            "message_id": "msg-reply-1",
            "channel": "ticket:thread-test",
            "sender": "peer",
            "body": {"type": "clarification_reply", "answer": "24 hours"},
            "correlation_id": "c-001",
            "reply_to": "msg-orig-1",
            "seq": 5,
        }
        # handle_message should process the reply without raising.
        await agent.handle_message(reply_envelope)

        # The message must be terminal (done or nack) — not stuck in processing.
        rec = store._ack_records.get("msg-reply-1")
        assert rec is not None
        assert rec["status"] == "done"


@pytest.mark.asyncio
async def test_thread_depth_parameter_accepted(tmp_state_dir: Path) -> None:
    """channels__recv with thread_depth=-1 is accepted without error."""
    store = MemoryStore()
    mcp = await build_server(store, "depth-agent")
    async with Client(mcp) as client:
        # thread_depth=-1 means "return full ancestor chain inline" per spec.
        result = await client.call_tool(
            "channels__recv", {"thread_depth": -1}
        )
        # Should return an empty messages list (no error).
        assert "messages" in result.data
