# SPDX-License-Identifier: Apache-2.0
"""Final coverage gap tests for backing store adapters.

Covers:
- filesystem/store.py lines 414-415 (delivered-set branch in recv generator)
- filesystem/store.py lines 534, 536 ("offline" and "stale" presence states)
- memory/store.py line 361 ("stale" presence state in list_agents)
- sqlite/store.py lines 569, 571 ("offline" and "stale" presence states)
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path

import pytest
import pytest_asyncio

from sox_protocol.adapters.backing_stores.filesystem.store import FilesystemStore
from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

# ---------------------------------------------------------------------------
# Filesystem store — lines 414-415: delivered-set branch
# When recv has already delivered a message, fname goes into `seen` via
# the delivered-set branch (fname in delivered → seen.add(fname); continue).
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fs_store(tmp_path: Path) -> FilesystemStore:
    store = FilesystemStore(root=tmp_path / "fsstore")
    await store.initialize()
    return store


@pytest.mark.asyncio
async def test_filesystem_watch_skips_delivered_mid_iteration(
    tmp_path: Path,
) -> None:
    """Lines 414-415: watch() hits 'fname in delivered' branch.

    Scenario: start watch(), send a message so it gets yielded and added to
    seen. Then separately recv() it to mark it delivered in a *fresh* watch()
    call. In the new watch() call, the message is in delivered but NOT in
    seen (seen starts empty), so lines 413-415 execute.

    We use a short watch_poll_interval to make this fast.
    """
    store2 = FilesystemStore(root=tmp_path / "watch_test", watch_poll_interval=0.05)
    await store2.initialize()

    await store2.subscribe("agent-c", "ch/*")
    # Send a message and mark it as delivered via recv()
    await store2.send("ch/test", "sender", {"delivered_msg": True})
    msgs = await store2.recv("agent-c", max_messages=50)
    assert len(msgs) == 1

    # Now start a *new* watch() — seen starts empty, but delivered set has
    # the file. The first loop iteration will see fname in delivered (414-415).
    # Then send a second message so watch() yields something and we can break.
    collected: list[dict[str, object]] = []

    async def _watch_once() -> None:
        async for msg in store2.watch("agent-c"):
            collected.append(msg)
            break

    # Send the new message before starting watch so the event fires
    await store2.send("ch/test", "sender", {"new_msg": True})

    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(_watch_once(), timeout=1.0)

    # Only the new (non-delivered) message should appear
    for msg in collected:
        assert msg.get("delivered_msg") is not True


# ---------------------------------------------------------------------------
# Filesystem store — lines 534, 536: "offline" and "stale" presence states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filesystem_list_agents_offline_status(
    fs_store: FilesystemStore,
) -> None:
    """Line 534: list_agents returns 'offline' when reported status is 'offline'."""
    await fs_store.heartbeat("agent-offline", "offline", ttl=300)

    agents = await fs_store.list_agents()
    statuses = {a["agent_id"]: a["presence_state"] for a in agents}
    assert statuses.get("agent-offline") == "offline"


@pytest.mark.asyncio
async def test_filesystem_list_agents_stale_status(
    fs_store: FilesystemStore,
) -> None:
    """Line 536: list_agents returns 'stale' when expires_at is in the past."""
    # Heartbeat first to initialise the record, then backdate expires_at
    await fs_store.heartbeat("agent-stale", "online", ttl=60)
    # Directly set expires_at to a past timestamp so expires_at <= now
    fs_store._liveness["agent-stale"]["expires_at"] = time.time() - 1.0

    agents = await fs_store.list_agents()
    statuses = {a["agent_id"]: a["presence_state"] for a in agents}
    assert statuses.get("agent-stale") == "stale"


# ---------------------------------------------------------------------------
# Memory store — line 361: "stale" presence state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_list_agents_stale_status() -> None:
    """Line 361: list_agents returns 'stale' when expires_at is in the past."""
    store = MemoryStore()
    await store.initialize()

    # Heartbeat first, then backdate expires_at directly
    await store.heartbeat("agent-stale", "online", ttl=60)
    store._liveness["agent-stale"]["expires_at"] = time.time() - 1.0

    agents = await store.list_agents()
    statuses = {a["agent_id"]: a["presence_state"] for a in agents}
    assert statuses.get("agent-stale") == "stale"


@pytest.mark.asyncio
async def test_memory_list_agents_offline_status() -> None:
    """Confirm offline branch also covered (line 360-361 complement)."""
    store = MemoryStore()
    await store.initialize()

    await store.heartbeat("agent-offline", "offline", ttl=300)

    agents = await store.list_agents()
    statuses = {a["agent_id"]: a["presence_state"] for a in agents}
    assert statuses.get("agent-offline") == "offline"


# ---------------------------------------------------------------------------
# SQLite store — lines 569, 571: "offline" and "stale" presence states
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sqlite_store(tmp_path: Path) -> SqliteStore:
    store = SqliteStore(db_path=tmp_path / "final_cov.db")
    await store.initialize()
    yield store  # type: ignore[misc]
    await store.close()


@pytest.mark.asyncio
async def test_sqlite_list_agents_offline_status(sqlite_store: SqliteStore) -> None:
    """Line 569: list_agents returns 'offline' when reported status is 'offline'."""
    await sqlite_store.heartbeat("agent-offline", "offline", ttl=300)

    agents = await sqlite_store.list_agents()
    statuses = {a["agent_id"]: a["presence_state"] for a in agents}
    assert statuses.get("agent-offline") == "offline"


@pytest.mark.asyncio
async def test_sqlite_list_agents_stale_status(sqlite_store: SqliteStore) -> None:
    """Line 571: list_agents returns 'stale' when expires_at is in the past."""
    await sqlite_store.heartbeat("agent-stale", "online", ttl=60)
    # Backdate expires_at directly so expires_at <= now
    sqlite_store._liveness["agent-stale"]["expires_at"] = time.time() - 1.0

    agents = await sqlite_store.list_agents()
    statuses = {a["agent_id"]: a["presence_state"] for a in agents}
    assert statuses.get("agent-stale") == "stale"
