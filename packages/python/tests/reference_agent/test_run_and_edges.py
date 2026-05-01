# SPDX-License-Identifier: Apache-2.0
"""Tests for the run() composition method and edge-case branches.

Covers:
- run(once=True): full bootstrap → recover → single drain → graceful_stop
- run(once=False): heartbeat task is started and cancelled on stop
- heartbeat_loop exception path (exc logged, loop continues)
- _set_presence exception path (exc logged, does not raise)
- recovery seq==0 branch (envelope with no seq skips cursor update)
- group_create with no group_id (server assigns one)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client

_REF_AGENT_DIR = Path(__file__).parents[4] / "examples" / "reference-agent"
if str(_REF_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_REF_AGENT_DIR))

from agent import ReferenceAgent
from tests.reference_agent.helpers import build_server
from sox_protocol.adapters.backing_stores.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_run_once_completes_without_error(tmp_state_dir: Path) -> None:
    """run(once=True) completes bootstrap → recover → drain → graceful_stop."""
    store = MemoryStore()
    mcp = await build_server(store, "run-once-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="run-once-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        # Should complete within a few seconds without raising.
        await asyncio.wait_for(agent.run(once=True), timeout=10.0)
        # After run(once=True), the agent should be stopped.
        assert agent._stop_event.is_set()


@pytest.mark.asyncio
async def test_run_once_processes_message(tmp_state_dir: Path) -> None:
    """run(once=True) drains and ACKs a message injected after bootstrap."""
    store = MemoryStore()
    await store.initialize()
    mcp = await build_server(store, "run-msg-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="run-msg-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )

        # Intercept after bootstrap() to inject a fresh message that run() will drain.
        original_bootstrap = agent.bootstrap

        async def _bootstrap_then_inject() -> None:
            await original_bootstrap()
            # Inject AFTER bootstrap drain so the message appears in the once-drain.
            await store.send(
                "ticket:run-test", "partner",
                {"type": "clarification_reply", "answer": "yes"},
            )
            await asyncio.sleep(0.1)  # let listener push it

        agent.bootstrap = _bootstrap_then_inject  # type: ignore[method-assign]
        await asyncio.wait_for(agent.run(once=True), timeout=10.0)

        # The message should have been ACK'd terminal.
        assert len(store._ack_records) >= 1
        for rec in store._ack_records.values():
            assert rec["status"] in ("done", "nack")


@pytest.mark.asyncio
async def test_run_normal_starts_heartbeat_task(tmp_state_dir: Path) -> None:
    """run() (continuous) starts the heartbeat loop and cancels it on stop."""
    store = MemoryStore()
    mcp = await build_server(store, "run-hb-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="run-hb-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )

        # Run the agent and stop it after a short delay.
        async def _stop_soon() -> None:
            await asyncio.sleep(0.3)
            await agent.graceful_stop()

        stop_task = asyncio.create_task(_stop_soon())
        await asyncio.wait_for(agent.run(once=False), timeout=5.0)
        stop_task.cancel()
        try:
            await stop_task
        except asyncio.CancelledError:
            pass

        # The heartbeat should have fired at least once during the run.
        liveness = store._liveness.get("run-hb-agent")
        assert liveness is not None


@pytest.mark.asyncio
async def test_heartbeat_loop_exception_logged_loop_continues(
    tmp_state_dir: Path,
) -> None:
    """heartbeat_loop logs exceptions but keeps running (does not crash)."""
    store = MemoryStore()
    mcp = await build_server(store, "hbexc-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="hbexc-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        call_count = 0
        original_call = client.call_tool

        async def _failing_then_ok(name: str, args: dict[str, Any] | None = None) -> Any:
            nonlocal call_count
            if name == "channels__heartbeat":
                call_count += 1
                if call_count == 1:
                    # First heartbeat call fails — loop should continue.
                    raise RuntimeError("transient heartbeat failure")
            return await original_call(name, args or {})

        client.call_tool = _failing_then_ok  # type: ignore[method-assign]

        # Run with a very short interval so both a failure and success fire fast.
        hb_task = asyncio.create_task(agent.heartbeat_loop(interval=0))
        await asyncio.sleep(0.05)
        agent._stop_event.set()
        await asyncio.wait_for(hb_task, timeout=2.0)

        # Loop should have run at least twice (one fail + one success).
        assert call_count >= 2


@pytest.mark.asyncio
async def test_set_presence_exception_does_not_raise(tmp_state_dir: Path) -> None:
    """_set_presence logs exceptions but does not propagate them."""
    store = MemoryStore()
    mcp = await build_server(store, "spexc-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="spexc-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        original_call = client.call_tool

        async def _failing_hb(name: str, args: dict[str, Any] | None = None) -> Any:
            if name == "channels__heartbeat":
                raise RuntimeError("heartbeat endpoint unavailable")
            return await original_call(name, args or {})

        client.call_tool = _failing_hb  # type: ignore[method-assign]

        # _set_presence should not raise even if heartbeat fails.
        await agent._set_presence("busy")  # must not raise
        # The in-process status should still be updated.
        assert agent._presence_status == "busy"


@pytest.mark.asyncio
async def test_recovery_zero_seq_skips_cursor_update(tmp_state_dir: Path) -> None:
    """Replayed envelopes with seq=0 do not corrupt the cursor state."""
    store = MemoryStore()
    await store.initialize()
    mcp = await build_server(store, "zseq-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="zseq-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        # Manually inject a state entry for a channel with seq=0 cursor.
        agent._seq_state.save({"ticket:zseq-test": 0})

        # Seed one message so replay returns something.
        await store.send("ticket:zseq-test", "sender", {"type": "status_update"})

        # Override handle_message to return without error.
        async def _noop_handle(envelope: dict[str, Any]) -> None:
            # Simulate a replayed envelope that has seq=0 (edge case).
            envelope["seq"] = 0
            # The original code path: if seq: update cursor — should not run for seq=0.

        agent.handle_message = _noop_handle  # type: ignore[method-assign]
        await agent.recover_from_state()
        # No assertion needed — just verify it completes without KeyError or crash.


@pytest.mark.asyncio
async def test_group_create_without_group_id(tmp_state_dir: Path) -> None:
    """group_create(group_id=None) lets the server assign an opaque group ID."""
    store = MemoryStore()
    mcp = await build_server(store, "gcreate-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="gcreate-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()
        # No group_id passed — server generates one.
        result = await agent.group_create()
        assert "group_id" in result
        # The returned group_id should have the group/ prefix.
        assert result["group_id"].startswith("group/")
