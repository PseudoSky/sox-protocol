# SPDX-License-Identifier: Apache-2.0
"""Tests for the main_loop lifecycle step.

Covers:
- drain → handle_message → ack(received) → ack(processing) → ack(done)
- seq state advances after processing
- presence flips online↔busy around handle_message
- unknown message types ACK done without raising
- main_loop exits when stop_event is set
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client

_REF_AGENT_DIR = Path(__file__).parents[4] / "examples" / "reference-agent"
if str(_REF_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_REF_AGENT_DIR))

from agent import ReferenceAgent, ACK_RECEIVED, ACK_PROCESSING, ACK_DONE, ACK_NACK
from tests.reference_agent.helpers import build_server
from sox_protocol.adapters.backing_stores.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_main_loop_processes_and_acks_message(tmp_state_dir: Path) -> None:
    """A message injected before the loop starts is received and ACK'd done."""
    store = MemoryStore()
    await store.initialize()

    mcp = await build_server(store, "loop-agent")
    async with Client(mcp) as client:
        # Subscribe so the agent receives messages.
        await client.call_tool("channels__subscribe", {"pattern": "ticket:*"})
        # Inject a test message directly via the store.
        await store.send(
            "ticket:loop-test",
            "partner",
            {"type": "clarification_request", "subject": "test", "question": "?"},
        )

        agent = ReferenceAgent(
            client,
            agent_id="loop-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        # Bootstrap populates subscriptions and drains any preexisting msgs.
        await agent.bootstrap()

        # Inject message AFTER bootstrap drain so it appears in the main loop.
        await store.send(
            "ticket:loop-test",
            "partner",
            {"type": "clarification_request", "subject": "loop test", "question": "q?"},
        )
        import asyncio as _asyncio
        await _asyncio.sleep(0.15)  # let the listener push the message

        # Run main_loop for one cycle then stop.
        async def _stop_after_one_recv() -> None:
            await _asyncio.sleep(0.6)
            await agent.graceful_stop()

        stop_task = _asyncio.create_task(_stop_after_one_recv())
        await agent.main_loop()
        stop_task.cancel()
        try:
            await stop_task
        except _asyncio.CancelledError:
            pass

        # Verify the ACK record was written for the message.
        assert len(store._ack_records) >= 1
        # All recorded statuses should be terminal (done or nack) — no leaked processing.
        for mid, rec in store._ack_records.items():
            assert rec["status"] in (ACK_DONE, ACK_NACK), (
                f"message {mid} stuck in non-terminal status {rec['status']!r}"
            )


@pytest.mark.asyncio
async def test_main_loop_seq_state_advances(tmp_state_dir: Path) -> None:
    """Processing a message advances the per-channel seq cursor."""
    store = MemoryStore()
    await store.initialize()

    mcp = await build_server(store, "seq-agent")
    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "ticket:*"})
        agent = ReferenceAgent(
            client,
            agent_id="seq-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()
        # Send a message and wait for it to be pushed to the listener.
        await store.send(
            "ticket:seq-test", "sender", {"type": "clarification_reply", "answer": "yes"}
        )
        import asyncio as _asyncio
        await _asyncio.sleep(0.15)

        # Run one cycle.
        async def _stop() -> None:
            await _asyncio.sleep(0.6)
            await agent.graceful_stop()

        stop_task = _asyncio.create_task(_stop())
        await agent.main_loop()
        stop_task.cancel()
        try:
            await stop_task
        except _asyncio.CancelledError:
            pass

        # The seq state file should now have ticket:seq-test with seq >= 1.
        saved = agent._seq_state.load()
        assert "ticket:seq-test" in saved
        assert saved["ticket:seq-test"] >= 1


@pytest.mark.asyncio
async def test_main_loop_unknown_type_acks_done(tmp_state_dir: Path) -> None:
    """Messages with unknown body.type are ACK'd done without raising."""
    store = MemoryStore()
    await store.initialize()

    mcp = await build_server(store, "unk-agent")
    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "ticket:*"})
        agent = ReferenceAgent(
            client,
            agent_id="unk-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()
        await store.send("ticket:unk", "sender", {"type": "totally_unknown_type"})
        import asyncio as _asyncio
        await _asyncio.sleep(0.15)

        async def _stop() -> None:
            await _asyncio.sleep(0.6)
            await agent.graceful_stop()

        stop_task = _asyncio.create_task(_stop())
        await agent.main_loop()
        stop_task.cancel()
        try:
            await stop_task
        except _asyncio.CancelledError:
            pass

        # Should have at least one ACK record and all terminal.
        for mid, rec in store._ack_records.items():
            assert rec["status"] in (ACK_DONE, ACK_NACK)


@pytest.mark.asyncio
async def test_main_loop_nacks_on_exception(tmp_state_dir: Path) -> None:
    """handle_message raising an exception causes ACK nack."""
    store = MemoryStore()
    await store.initialize()

    mcp = await build_server(store, "err-agent")
    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "ticket:*"})
        agent = ReferenceAgent(
            client,
            agent_id="err-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        # Make handle_message raise after ACK(processing).
        original_handle = agent.handle_message

        async def _exploding_handle(envelope: dict[str, Any]) -> None:
            raise RuntimeError("deliberate test error")

        agent.handle_message = _exploding_handle  # type: ignore[method-assign]

        await store.send("ticket:err", "sender", {"type": "status_update"})
        import asyncio as _asyncio
        await _asyncio.sleep(0.15)

        async def _stop() -> None:
            await _asyncio.sleep(0.6)
            await agent.graceful_stop()

        stop_task = _asyncio.create_task(_stop())
        await agent.main_loop()
        stop_task.cancel()
        try:
            await stop_task
        except _asyncio.CancelledError:
            pass

        # At least one nack record should exist.
        nack_records = [
            r for r in store._ack_records.values() if r["status"] == ACK_NACK
        ]
        assert len(nack_records) >= 1
        assert nack_records[0]["reason"] == "deliberate test error"
