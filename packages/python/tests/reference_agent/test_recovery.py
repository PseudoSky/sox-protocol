# SPDX-License-Identifier: Apache-2.0
"""Tests for the recovery lifecycle step.

Covers:
- recover_from_state calls replay(since=last_seq) for each channel in state
- Replayed messages are processed without duplicates
- Seq state file is updated after each replayed message
- Empty state file results in no replay calls (nothing to recover)
- Corrupt state file is treated as empty (safe fallback)
- state.py: atomic save and corrupt-file recovery
"""

from __future__ import annotations

import json
import sys
import tempfile
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
from state import SeqState


# ---------------------------------------------------------------------------
# SeqState unit tests (state.py)
# ---------------------------------------------------------------------------


def test_seq_state_atomic_save_and_load(tmp_path: Path) -> None:
    """SeqState.save writes atomically and load returns the same data."""
    state = SeqState(tmp_path / "seq.json")
    data = {"ticket:ENGI-001": 42, "ticket:ENGI-002": 7}
    state.save(data)
    loaded = state.load()
    assert loaded == data


def test_seq_state_load_returns_empty_when_file_missing(tmp_path: Path) -> None:
    """SeqState.load returns {} when the file does not exist."""
    state = SeqState(tmp_path / "nonexistent.json")
    assert state.load() == {}


def test_seq_state_corrupt_file_returns_empty(tmp_path: Path) -> None:
    """SeqState.load returns {} on a corrupt file (safe fallback)."""
    p = tmp_path / "corrupt.json"
    p.write_text("NOT VALID JSON {{{", encoding="utf-8")
    state = SeqState(p)
    # Should not raise — corrupt file is treated as empty state.
    result = state.load()
    assert result == {}


def test_seq_state_update_persists_single_channel(tmp_path: Path) -> None:
    """SeqState.update writes the new seq for one channel."""
    state = SeqState(tmp_path / "seq.json")
    state.update("ticket:ENGI-001", 10)
    loaded = state.load()
    assert loaded["ticket:ENGI-001"] == 10


def test_seq_state_update_merges_with_existing(tmp_path: Path) -> None:
    """SeqState.update preserves existing channels when updating one."""
    state = SeqState(tmp_path / "seq.json")
    state.save({"ticket:A": 1, "ticket:B": 5})
    state.update("ticket:A", 3)
    loaded = state.load()
    # ticket:A updated, ticket:B preserved.
    assert loaded["ticket:A"] == 3
    assert loaded["ticket:B"] == 5


def test_seq_state_save_creates_parent_dirs(tmp_path: Path) -> None:
    """SeqState.save creates parent directories if they don't exist."""
    nested = tmp_path / "a" / "b" / "c" / "seq.json"
    state = SeqState(nested)
    state.save({"ch": 1})
    assert nested.exists()
    assert state.load() == {"ch": 1}


# ---------------------------------------------------------------------------
# Recovery integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_replays_missed_messages(tmp_state_dir: Path) -> None:
    """recover_from_state replays messages after the saved seq cursor."""
    store = MemoryStore()
    await store.initialize()

    # Pre-seed messages in the store before the agent starts.
    await store.send("ticket:recovery-test", "sender", {"type": "status_update", "n": 1})
    await store.send("ticket:recovery-test", "sender", {"type": "status_update", "n": 2})
    await store.send("ticket:recovery-test", "sender", {"type": "status_update", "n": 3})

    # Write a state file indicating the agent has seen seq=1 (missed 2 and 3).
    seq_state = SeqState(tmp_state_dir / "seq.json")
    seq_state.save({"ticket:recovery-test": 1})

    mcp = await build_server(store, "recovery-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="recovery-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        # Track which messages were processed during recovery.
        processed_seqs: list[int] = []
        original_handle = agent.handle_message

        async def _tracking_handle(envelope: dict[str, Any]) -> None:
            processed_seqs.append(int(envelope.get("seq", 0)))
            await original_handle(envelope)

        agent.handle_message = _tracking_handle  # type: ignore[method-assign]
        await agent.recover_from_state()

        # Should have replayed seq=2 and seq=3 (since=1 is exclusive, i.e. seq > 1).
        assert 2 in processed_seqs, f"seq=2 not replayed; got {processed_seqs}"
        assert 3 in processed_seqs, f"seq=3 not replayed; got {processed_seqs}"
        # Should NOT have replayed seq=1 (already processed before restart).
        assert 1 not in processed_seqs, f"seq=1 was re-replayed (duplicate!)"


@pytest.mark.asyncio
async def test_recovery_no_replay_when_state_empty(tmp_state_dir: Path) -> None:
    """recover_from_state does nothing when state file is empty/absent."""
    store = MemoryStore()
    mcp = await build_server(store, "fresh-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="fresh-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()
        # Should complete without error and without processing anything.
        await agent.recover_from_state()
        # No ACK records means no messages were replayed.
        assert store._ack_records == {}


@pytest.mark.asyncio
async def test_recovery_seq_cursor_advances_after_replay(tmp_state_dir: Path) -> None:
    """After replay, the seq cursor in state reflects the last replayed seq."""
    store = MemoryStore()
    await store.initialize()

    # Seed two messages.
    await store.send("ticket:cursor-test", "sender", {"type": "status_update"})
    await store.send("ticket:cursor-test", "sender", {"type": "status_update"})

    # Start from seq=0 (agent has never seen this channel).
    seq_state = SeqState(tmp_state_dir / "seq.json")
    seq_state.save({"ticket:cursor-test": 0})

    mcp = await build_server(store, "cursor-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="cursor-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()
        await agent.recover_from_state()

        # The cursor should have advanced to at least seq=2.
        saved = agent._seq_state.load()
        assert "ticket:cursor-test" in saved
        assert saved["ticket:cursor-test"] >= 2


@pytest.mark.asyncio
async def test_recovery_no_duplicates_across_restart(tmp_state_dir: Path) -> None:
    """Messages already processed before restart are not replayed again."""
    store = MemoryStore()
    await store.initialize()

    # Seed 3 messages; simulate agent having seen all 3.
    for i in range(3):
        await store.send(
            "ticket:no-dup-test", "sender", {"type": "status_update", "i": i}
        )
    # Save state showing all 3 were processed (seq=3 is the last).
    seq_state = SeqState(tmp_state_dir / "seq.json")
    seq_state.save({"ticket:no-dup-test": 3})

    mcp = await build_server(store, "no-dup-agent")
    async with Client(mcp) as client:
        agent = ReferenceAgent(
            client,
            agent_id="no-dup-agent",
            namespace="reference",
            state_dir=tmp_state_dir,
        )
        await agent.bootstrap()

        processed: list[int] = []
        original_handle = agent.handle_message

        async def _track(envelope: dict[str, Any]) -> None:
            processed.append(int(envelope.get("seq", 0)))
            await original_handle(envelope)

        agent.handle_message = _track  # type: ignore[method-assign]
        await agent.recover_from_state()

        # Nothing should have been replayed — all seqs were already seen.
        assert processed == [], f"Unexpected replay of already-seen messages: {processed}"
