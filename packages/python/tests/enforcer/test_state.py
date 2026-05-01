# SPDX-License-Identifier: Apache-2.0
"""Unit tests for core/enforcer/state.py — State, StateStore, _resolve_db_path."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sox_protocol.core.enforcer.events import EventType
from sox_protocol.core.enforcer.state import State, StateStore, _resolve_db_path

# ---------------------------------------------------------------------------
# State dataclass
# ---------------------------------------------------------------------------


def test_state_repr_contains_agent_id() -> None:
    """State.__repr__ includes agent_id."""
    s = State(agent_id="test-agent")
    r = repr(s)
    assert "test-agent" in r
    assert "tool_calls_since_drain" in r


def test_state_eq_same_values() -> None:
    """Two States with identical values are equal."""
    a = State(agent_id="x", tool_calls_since_drain=3)
    b = State(agent_id="x", tool_calls_since_drain=3)
    assert a == b


def test_state_eq_different_values() -> None:
    """States with different values are not equal."""
    a = State(agent_id="x", tool_calls_since_drain=1)
    b = State(agent_id="x", tool_calls_since_drain=2)
    assert a != b


def test_state_eq_not_implemented_for_other_types() -> None:
    """State.__eq__ returns NotImplemented for non-State objects."""
    s = State(agent_id="x")
    result = s.__eq__("not a state")
    assert result is NotImplemented


def test_state_default_values() -> None:
    """State defaults are zeroed."""
    s = State(agent_id="agent-zero")
    assert s.tool_calls_since_drain == 0
    assert s.last_drain_ts is None
    assert s.last_send_ts is None
    assert s.sends_since_last_drain == 0
    assert s.turns_since_last_drain == 0
    assert s.schema_version == "1.0"


# ---------------------------------------------------------------------------
# _resolve_db_path
# ---------------------------------------------------------------------------


def test_resolve_db_path_uses_sox_state_dir(tmp_path: Path) -> None:
    """_resolve_db_path uses SOX_STATE_DIR env var when set."""
    with patch.dict(os.environ, {"SOX_STATE_DIR": str(tmp_path)}):
        path = _resolve_db_path()
    assert path == tmp_path / "state.db"


def test_resolve_db_path_default_when_unset() -> None:
    """_resolve_db_path returns ~/.sox/state.db when SOX_STATE_DIR is unset."""
    env = {k: v for k, v in os.environ.items() if k != "SOX_STATE_DIR"}
    with patch.dict(os.environ, env, clear=True):
        path = _resolve_db_path()
    assert path == Path.home() / ".sox" / "state.db"


# ---------------------------------------------------------------------------
# StateStore lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_store_open_and_close(tmp_path: Path) -> None:
    """StateStore.open() creates the DB and close() closes it cleanly."""
    store = StateStore(db_path=tmp_path / "state.db")
    await store.open()
    assert store._conn is not None
    await store.close()
    assert store._conn is None


@pytest.mark.asyncio
async def test_state_store_close_when_not_open() -> None:
    """StateStore.close() is safe to call when not open."""
    store = StateStore(db_path=Path(":memory:"))
    # Should not raise
    await store.close()


@pytest.mark.asyncio
async def test_state_store_async_context_manager(tmp_path: Path) -> None:
    """StateStore works as async context manager."""
    async with StateStore(db_path=tmp_path / "state.db") as store:
        assert store._conn is not None
    assert store._conn is None


@pytest.mark.asyncio
async def test_state_store_require_conn_raises_when_not_open(tmp_path: Path) -> None:
    """_require_conn raises RuntimeError when store is not open."""
    store = StateStore(db_path=tmp_path / "state.db")
    with pytest.raises(RuntimeError, match="not open"):
        store._require_conn()


# ---------------------------------------------------------------------------
# StateStore load / save
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_store_load_new_agent_returns_default(tmp_path: Path) -> None:
    """load() returns a zeroed State for an unknown agent."""
    async with StateStore(db_path=tmp_path / "state.db") as store:
        state = await store.load("brand-new-agent")
    assert state.agent_id == "brand-new-agent"
    assert state.tool_calls_since_drain == 0
    assert state.last_drain_ts is None


@pytest.mark.asyncio
async def test_state_store_save_and_reload(tmp_path: Path) -> None:
    """save() persists state; load() retrieves it on the next open."""
    db = tmp_path / "state.db"
    async with StateStore(db_path=db) as store:
        state = State(
            agent_id="persist-agent",
            tool_calls_since_drain=5,
            last_drain_ts=1_000_000.0,
            sends_since_last_drain=2,
            turns_since_last_drain=3,
        )
        await store.save(state)

    # Re-open
    async with StateStore(db_path=db) as store2:
        loaded = await store2.load("persist-agent")

    assert loaded.tool_calls_since_drain == 5
    assert loaded.last_drain_ts == 1_000_000.0
    assert loaded.sends_since_last_drain == 2
    assert loaded.turns_since_last_drain == 3


@pytest.mark.asyncio
async def test_state_store_save_upsert(tmp_path: Path) -> None:
    """save() is idempotent — saving twice updates the record."""
    db = tmp_path / "state.db"
    async with StateStore(db_path=db) as store:
        s1 = State(agent_id="upsert-agent", tool_calls_since_drain=1)
        await store.save(s1)
        s2 = State(agent_id="upsert-agent", tool_calls_since_drain=7)
        await store.save(s2)
        loaded = await store.load("upsert-agent")

    assert loaded.tool_calls_since_drain == 7


# ---------------------------------------------------------------------------
# StateStore apply_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_event_channel_recv_resets_counters(tmp_path: Path) -> None:
    """apply_event(channel_recv) resets all counters."""
    async with StateStore(db_path=tmp_path / "state.db") as store:
        # Pre-load with non-zero counters
        s = State(
            agent_id="ev-agent",
            tool_calls_since_drain=10,
            sends_since_last_drain=5,
            turns_since_last_drain=3,
        )
        await store.save(s)

        updated = await store.apply_event("ev-agent", EventType.channel_recv, 1_500_000.0)

    assert updated.tool_calls_since_drain == 0
    assert updated.sends_since_last_drain == 0
    assert updated.turns_since_last_drain == 0
    assert updated.last_drain_ts == 1_500_000.0


@pytest.mark.asyncio
async def test_apply_event_tool_used_increments_counter(tmp_path: Path) -> None:
    """apply_event(tool_used) increments tool_calls_since_drain."""
    async with StateStore(db_path=tmp_path / "state.db") as store:
        s = State(agent_id="tool-agent", tool_calls_since_drain=2)
        await store.save(s)
        updated = await store.apply_event("tool-agent", EventType.tool_used, 0.0)

    assert updated.tool_calls_since_drain == 3


@pytest.mark.asyncio
async def test_apply_event_channel_send_updates_send_ts(tmp_path: Path) -> None:
    """apply_event(channel_send) sets last_send_ts and increments sends counter."""
    async with StateStore(db_path=tmp_path / "state.db") as store:
        updated = await store.apply_event("send-agent", EventType.channel_send, 9_999.0)

    assert updated.last_send_ts == 9_999.0
    assert updated.sends_since_last_drain == 1


@pytest.mark.asyncio
async def test_apply_event_turn_started_increments_turns(tmp_path: Path) -> None:
    """apply_event(turn_started) increments turns_since_last_drain."""
    async with StateStore(db_path=tmp_path / "state.db") as store:
        await store.apply_event("turn-agent", EventType.turn_started, 0.0)
        updated = await store.apply_event("turn-agent", EventType.turn_started, 1.0)

    assert updated.turns_since_last_drain == 2


@pytest.mark.asyncio
async def test_apply_event_stop_requested_no_mutation(tmp_path: Path) -> None:
    """apply_event(stop_requested) does not mutate any counter."""
    async with StateStore(db_path=tmp_path / "state.db") as store:
        s = State(agent_id="stop-agent", tool_calls_since_drain=7)
        await store.save(s)
        updated = await store.apply_event("stop-agent", EventType.stop_requested, 0.0)

    assert updated.tool_calls_since_drain == 7


@pytest.mark.asyncio
async def test_apply_event_new_agent_creates_record(tmp_path: Path) -> None:
    """apply_event on an unknown agent creates a new zeroed record first."""
    async with StateStore(db_path=tmp_path / "state.db") as store:
        updated = await store.apply_event("new-agent-ev", EventType.tool_used, 0.0)

    assert updated.agent_id == "new-agent-ev"
    assert updated.tool_calls_since_drain == 1


@pytest.mark.asyncio
async def test_apply_event_rollback_on_exception(tmp_path: Path) -> None:
    """apply_event rolls back on exception (conn.commit raises)."""

    db = tmp_path / "state.db"
    async with StateStore(db_path=db) as store:
        # Patch conn.commit to raise after the first real commit (open/DDL)
        original_commit = store._conn.commit

        call_count = 0

        async def _fail_commit() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated commit failure")
            await original_commit()

        store._conn.commit = _fail_commit  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="Simulated commit failure"):
            await store.apply_event("rb-agent", EventType.tool_used, 0.0)
