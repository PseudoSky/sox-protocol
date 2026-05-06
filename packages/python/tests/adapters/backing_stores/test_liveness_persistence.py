# SPDX-License-Identifier: Apache-2.0
"""Cross-process heartbeat persistence (schema v1.3+).

Pre-v1.3, ``SqliteStore.heartbeat()`` wrote to an in-process dict
(``self._liveness``).  Two SqliteStore instances pointing at the same
SQLite file (the cross-process scenario the project actually runs:
Claude Code agent's MCP server + ``sox-protocol chat`` TUI's separate MCP
server) couldn't see each other's heartbeats — the agent roster was
always empty.

Schema v1.3 adds a ``liveness`` table; these tests pin the cross-process
visibility behaviour.
"""

from __future__ import annotations

import pathlib

import pytest

from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore


@pytest.mark.asyncio
async def test_heartbeat_visible_to_separate_store_instance(
    tmp_path: pathlib.Path,
) -> None:
    """Heartbeat from store A is visible from store B opened on the same DB."""
    db_path = tmp_path / "shared.db"

    store_a = SqliteStore(db_path=db_path)
    await store_a.initialize()
    await store_a.heartbeat("agent-alpha", "online", ttl=120)
    await store_a.close()

    store_b = SqliteStore(db_path=db_path)
    await store_b.initialize()
    agents = await store_b.list_agents()
    await store_b.close()

    assert len(agents) == 1
    assert agents[0]["agent_id"] == "agent-alpha"
    assert agents[0]["presence_state"] == "online"
    assert agents[0]["last_heartbeat_at"] > 0


@pytest.mark.asyncio
async def test_heartbeat_concurrent_stores_share_liveness(
    tmp_path: pathlib.Path,
) -> None:
    """Two simultaneously-open SqliteStores share liveness via the table."""
    db_path = tmp_path / "concurrent.db"

    store_a = SqliteStore(db_path=db_path)
    store_b = SqliteStore(db_path=db_path)
    await store_a.initialize()
    await store_b.initialize()

    try:
        await store_a.heartbeat("alice", "online", ttl=60)
        await store_b.heartbeat("bob", "busy", ttl=60)

        agents_via_a = await store_a.list_agents()
        agents_via_b = await store_b.list_agents()
    finally:
        await store_a.close()
        await store_b.close()

    ids_a = {a["agent_id"] for a in agents_via_a}
    ids_b = {a["agent_id"] for a in agents_via_b}
    assert ids_a == {"alice", "bob"}
    assert ids_b == {"alice", "bob"}


@pytest.mark.asyncio
async def test_heartbeat_upserts_existing_row(tmp_path: pathlib.Path) -> None:
    """A second heartbeat from the same agent UPDATES — never duplicates."""
    db_path = tmp_path / "upsert.db"
    store = SqliteStore(db_path=db_path)
    await store.initialize()

    try:
        first = await store.heartbeat("agent-x", "online", ttl=30)
        second = await store.heartbeat("agent-x", "busy", ttl=30)

        agents = await store.list_agents()
    finally:
        await store.close()

    assert len(agents) == 1
    assert agents[0]["agent_id"] == "agent-x"
    assert agents[0]["presence_state"] == "busy"
    assert second["recorded_at"] >= first["recorded_at"]


@pytest.mark.asyncio
async def test_list_agents_marks_stale_when_ttl_expired(
    tmp_path: pathlib.Path,
) -> None:
    """An expired TTL flips presence_state to 'stale', not 'online'."""
    import time as _time

    db_path = tmp_path / "stale.db"
    store = SqliteStore(db_path=db_path)
    await store.initialize()
    try:
        # Heartbeat with TTL=1; sleep slightly longer to expire.
        await store.heartbeat("expiring", "online", ttl=1)
        # Sleep just over the TTL — stale boundary uses time.time().
        _time.sleep(1.1)
        agents = await store.list_agents()
    finally:
        await store.close()

    assert len(agents) == 1
    assert agents[0]["agent_id"] == "expiring"
    assert agents[0]["presence_state"] == "stale"


@pytest.mark.asyncio
async def test_list_agents_status_filter(tmp_path: pathlib.Path) -> None:
    """status_filter narrows the result set."""
    db_path = tmp_path / "filter.db"
    store = SqliteStore(db_path=db_path)
    await store.initialize()
    try:
        await store.heartbeat("a", "online", ttl=60)
        await store.heartbeat("b", "busy", ttl=60)

        online_only = await store.list_agents(status_filter=["online"])
        busy_only = await store.list_agents(status_filter=["busy"])
        both = await store.list_agents(status_filter=["online", "busy"])
    finally:
        await store.close()

    assert {a["agent_id"] for a in online_only} == {"a"}
    assert {a["agent_id"] for a in busy_only} == {"b"}
    assert {a["agent_id"] for a in both} == {"a", "b"}


@pytest.mark.asyncio
async def test_offline_status_persists_explicitly(tmp_path: pathlib.Path) -> None:
    """Explicit status='offline' persists as offline (not stale)."""
    db_path = tmp_path / "offline.db"
    store = SqliteStore(db_path=db_path)
    await store.initialize()
    try:
        await store.heartbeat("agent-offline", "offline", ttl=60)
        agents = await store.list_agents()
    finally:
        await store.close()

    assert len(agents) == 1
    assert agents[0]["presence_state"] == "offline"


@pytest.mark.asyncio
async def test_migration_v1_2_to_v1_3_preserves_existing_data(
    tmp_path: pathlib.Path,
) -> None:
    """Upgrading a v1.2 DB with messages to v1.3 doesn't lose data."""
    db_path = tmp_path / "upgrade.db"

    # Simulate a v1.2 database by initializing one and downgrading the
    # recorded schema_version, then re-initializing — the migration runner
    # should walk forward from 1.2 → 1.3.
    import aiosqlite

    # Bootstrap a v1.2-shaped database directly (no liveness table).
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.executescript(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                sender TEXT NOT NULL,
                body TEXT NOT NULL,
                correlation_id TEXT,
                sent_at REAL NOT NULL,
                delivered_to TEXT NOT NULL DEFAULT '[]',
                seq INTEGER NOT NULL DEFAULT 0,
                reply_to TEXT DEFAULT NULL
            );
            CREATE TABLE subscriptions (
                agent_id TEXT NOT NULL,
                channel_pattern TEXT NOT NULL,
                PRIMARY KEY (agent_id, channel_pattern)
            );
            CREATE TABLE _sox_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO _sox_meta(key, value) VALUES ('schema_version', '1.2');
            INSERT INTO messages(channel, sender, body, sent_at, seq)
                VALUES ('legacy/channel', 'legacy-agent', '{"text":"old"}', 1000.0, 1);
            """
        )
        await conn.commit()

    # Open with the current SqliteStore — should auto-migrate to v1.3.
    store = SqliteStore(db_path=db_path)
    await store.initialize()
    try:
        # Pre-existing message survived.
        msgs, _ = await store.replay("legacy/channel")
        assert len(msgs) == 1
        # Liveness table is now usable.
        await store.heartbeat("post-migrate-agent", "online", ttl=60)
        agents = await store.list_agents()
    finally:
        await store.close()

    assert {a["agent_id"] for a in agents} == {"post-migrate-agent"}
