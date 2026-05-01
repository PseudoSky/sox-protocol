# SPDX-License-Identifier: Apache-2.0
"""Tests for ``sox_protocol.tui.pump``.

Uses a fake McpStdioClient yielding scripted messages to assert that:
- RecvPump feeds messages into ChatStore
- Cancellation drains cleanly
- is_running() reflects actual state
- Errors in recv() do not kill the pump
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sox_protocol.tui.pump import RecvPump
from sox_protocol.tui.state import ChatStore


# ---------------------------------------------------------------------------
# Fake client helpers
# ---------------------------------------------------------------------------


def _make_client_with_messages(messages: list[dict[str, Any]]) -> Any:
    """Return a mock McpStdioClient that yields *messages* then empty responses."""
    client = MagicMock()
    call_count = 0

    async def fake_recv(**kwargs: Any) -> dict[str, Any]:
        nonlocal call_count
        if call_count < len(messages):
            msg = messages[call_count]
            call_count += 1
            return {"drained_at": time.time(), "messages": [msg]}
        return {"drained_at": time.time(), "messages": []}

    client.recv = fake_recv
    return client


def _make_error_client(error_count: int = 1) -> Any:
    """Return a mock that raises on the first *error_count* calls then returns empty."""
    client = MagicMock()
    call_count = 0

    async def fake_recv(**kwargs: Any) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count <= error_count:
            raise RuntimeError("transient error")
        return {"drained_at": time.time(), "messages": []}

    client.recv = fake_recv
    return client


def _sample_message(message_id: str = "1", channel: str = "#general") -> dict[str, Any]:
    return {
        "message_id": message_id,
        "channel": channel,
        "sender": "agent-a",
        "body": {"text": "hello"},
        "sent_at": time.time(),
        "seq": 1,
        "reply_to": None,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pump_feeds_messages_into_store() -> None:
    msg = _sample_message("m1")
    client = _make_client_with_messages([msg])
    store = ChatStore()

    pump = RecvPump(client=client, store=store, poll_interval=0.05)
    await pump.start()
    # Give the pump time to run at least one cycle
    await asyncio.sleep(0.15)
    await pump.stop()

    msgs = store.messages_for("#general")
    assert len(msgs) == 1
    assert msgs[0].message_id == "m1"


@pytest.mark.asyncio
async def test_pump_deduplicates_via_store() -> None:
    msg = _sample_message("dup")
    client = _make_client_with_messages([msg, msg])
    store = ChatStore()

    pump = RecvPump(client=client, store=store, poll_interval=0.05)
    await pump.start()
    await asyncio.sleep(0.2)
    await pump.stop()

    msgs = store.messages_for("#general")
    assert len(msgs) == 1


@pytest.mark.asyncio
async def test_pump_multiple_messages() -> None:
    msgs = [_sample_message(f"m{i}", "#general") for i in range(3)]
    # Patch seqs to be unique
    for i, m in enumerate(msgs):
        m["seq"] = i + 1

    client = _make_client_with_messages(msgs)
    store = ChatStore()

    pump = RecvPump(client=client, store=store, poll_interval=0.05)
    await pump.start()
    await asyncio.sleep(0.3)
    await pump.stop()

    assert len(store.messages_for("#general")) == 3


@pytest.mark.asyncio
async def test_pump_is_running_reflects_state() -> None:
    client = _make_client_with_messages([])
    store = ChatStore()
    pump = RecvPump(client=client, store=store, poll_interval=0.1)

    assert not pump.is_running()
    await pump.start()
    assert pump.is_running()
    await pump.stop()
    assert not pump.is_running()


@pytest.mark.asyncio
async def test_pump_start_twice_raises() -> None:
    client = _make_client_with_messages([])
    store = ChatStore()
    pump = RecvPump(client=client, store=store, poll_interval=0.1)

    await pump.start()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            await pump.start()
    finally:
        await pump.stop()


@pytest.mark.asyncio
async def test_pump_stop_noop_when_not_started() -> None:
    client = _make_client_with_messages([])
    store = ChatStore()
    pump = RecvPump(client=client, store=store)
    # Should not raise
    await pump.stop()


@pytest.mark.asyncio
async def test_pump_survives_transient_recv_error() -> None:
    """Transient errors in recv() should not kill the pump."""
    client = _make_error_client(error_count=2)
    store = ChatStore()

    pump = RecvPump(client=client, store=store, poll_interval=0.05)
    await pump.start()
    await asyncio.sleep(0.25)
    # Pump should still be running after transient errors
    assert pump.is_running()
    await pump.stop()


@pytest.mark.asyncio
async def test_pump_cancellation_is_clean() -> None:
    """Stopping pump while recv() is in-flight should not raise."""
    slow_client = MagicMock()

    async def slow_recv(**kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(10)
        return {"drained_at": 0.0, "messages": []}

    slow_client.recv = slow_recv
    store = ChatStore()

    pump = RecvPump(client=slow_client, store=store, poll_interval=0.05)
    await pump.start()
    await asyncio.sleep(0.05)
    # Should complete cleanly
    await pump.stop()
    assert not pump.is_running()


@pytest.mark.asyncio
async def test_pump_stop_when_task_already_done() -> None:
    """stop() should be a no-op when the task finished on its own."""
    call_count = 0

    async def one_shot_recv(**kwargs: Any) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"drained_at": 0.0, "messages": []}
        # Raise to simulate the loop exiting naturally after one iteration
        raise asyncio.CancelledError()

    client = MagicMock()
    client.recv = one_shot_recv
    store = ChatStore()
    pump = RecvPump(client=client, store=store, poll_interval=0.01)
    await pump.start()
    # Wait for the task to finish due to CancelledError propagation
    await asyncio.sleep(0.15)
    # Task should now be done — stop() should not raise
    await pump.stop()
    assert not pump.is_running()


@pytest.mark.asyncio
async def test_pump_default_poll_interval() -> None:
    """Default poll_interval should be 0.25."""
    from sox_protocol.tui.pump import _POLL_INTERVAL

    assert _POLL_INTERVAL == 0.25
    client = _make_client_with_messages([])
    store = ChatStore()
    pump = RecvPump(client=client, store=store)
    assert pump._poll_interval == 0.25
