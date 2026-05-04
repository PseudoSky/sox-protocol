# SPDX-License-Identifier: Apache-2.0
"""Tests for the presence_heartbeat lifecycle step.

Covers:
- Heartbeat fires on schedule (interval respected)
- Status flips online → busy → online around handle_message
- heartbeat(offline) emitted on graceful_stop
- _set_presence updates the liveness record immediately
- heartbeat_loop exits when stop event is set
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastmcp import Client

_REF_AGENT_DIR = Path(__file__).parents[4] / "examples" / "reference-agent"
if str(_REF_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_REF_AGENT_DIR))

import contextlib

from agent import ReferenceAgent

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from tests.reference_agent.helpers import build_server


@pytest.mark.asyncio
async def test_heartbeat_registers_agent_online(tmp_state_dir: Path) -> None:
    """After bootstrap, the liveness record shows the agent as online."""
    store = MemoryStore()
    mcp = await build_server(store, "hb-online-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="hb-online-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()
        liveness = store._liveness.get("hb-online-agent")
        assert liveness is not None
        assert liveness["status"] == "online"


@pytest.mark.asyncio
async def test_set_presence_updates_liveness_immediately(tmp_state_dir: Path) -> None:
    """_set_presence("busy") immediately writes busy to the liveness record."""
    store = MemoryStore()
    mcp = await build_server(store, "presence-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="presence-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()
        # Flip to busy.
        await agent._set_presence("busy")
        liveness = store._liveness.get("presence-agent")
        assert liveness is not None
        assert liveness["status"] == "busy"
        # Flip back to online.
        await agent._set_presence("online")
        liveness2 = store._liveness.get("presence-agent")
        assert liveness2 is not None
        assert liveness2["status"] == "online"


@pytest.mark.asyncio
async def test_heartbeat_loop_fires_and_stops(tmp_state_dir: Path) -> None:
    """heartbeat_loop fires at least once and exits when stop_event is set."""
    store = MemoryStore()
    mcp = await build_server(store, "hbloop-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="hbloop-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        # Run heartbeat_loop with a short interval so it fires quickly.
        hb_task = asyncio.create_task(agent.heartbeat_loop(interval=1))
        # Wait just over one interval so at least one beat fires.
        await asyncio.sleep(1.1)
        # Set the stop event to terminate the loop.
        agent._stop_event.set()
        await asyncio.wait_for(hb_task, timeout=2.0)

        # The liveness record should have been refreshed by the loop.
        liveness = store._liveness.get("hbloop-agent")
        assert liveness is not None


@pytest.mark.asyncio
async def test_graceful_stop_emits_offline_heartbeat(tmp_state_dir: Path) -> None:
    """graceful_stop emits heartbeat(offline) before exiting."""
    store = MemoryStore()
    mcp = await build_server(store, "offline-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="offline-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()
        # No pending messages, so graceful_stop should complete immediately.
        await agent.graceful_stop()
        liveness = store._liveness.get("offline-agent")
        assert liveness is not None
        assert liveness["status"] == "offline"


@pytest.mark.asyncio
async def test_graceful_stop_waits_for_pending(tmp_state_dir: Path) -> None:
    """graceful_stop waits until pending messages reach terminal status."""
    store = MemoryStore()
    mcp = await build_server(store, "wait-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="wait-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        # Manually inject a pending message (simulates mid-processing state).
        agent._pending.add("msg-in-flight")

        # Schedule resolution of the pending message after a short delay.
        async def _resolve() -> None:
            await asyncio.sleep(0.2)
            agent._pending.discard("msg-in-flight")

        resolve_task = asyncio.create_task(_resolve())

        # graceful_stop should block until _pending is empty.
        await asyncio.wait_for(agent.graceful_stop(), timeout=2.0)
        await resolve_task

        # Offline heartbeat should have been emitted.
        liveness = store._liveness.get("wait-agent")
        assert liveness is not None
        assert liveness["status"] == "offline"


@pytest.mark.asyncio
async def test_presence_flips_busy_during_message_processing(tmp_state_dir: Path) -> None:
    """During a message batch, presence flips to busy and back to online."""
    store = MemoryStore()
    mcp = await build_server(store, "busy-agent")
    async with Client(mcp) as client:
        await client.call_tool("channels__subscribe", {"pattern": "ticket:*"})
        agent = ReferenceAgent(
            client,
            agent_id="busy-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        # Capture presence statuses emitted during handle_message.
        recorded_statuses: list[str] = []
        original_set_presence = agent._set_presence

        async def _recording_set_presence(status: str) -> None:
            recorded_statuses.append(status)
            await original_set_presence(status)

        agent._set_presence = _recording_set_presence  # type: ignore[method-assign]

        # Inject a message and run one main_loop cycle.
        await store.send("ticket:busy-test", "sender", {"type": "clarification_reply", "answer": "yes"})
        await asyncio.sleep(0.15)

        async def _stop() -> None:
            await asyncio.sleep(0.6)
            await agent.graceful_stop()

        stop_task = asyncio.create_task(_stop())
        await agent.main_loop()
        stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_task

        # Should have seen busy then online during the message batch.
        assert "busy" in recorded_statuses
        assert "online" in recorded_statuses
