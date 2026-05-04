# SPDX-License-Identifier: Apache-2.0
"""Schema-migration tests for the SQLite backing store.

Covers the v1.0 → v1.1 ``seq`` column migration. Future migrations should
add a parallel test class here. Each test creates a v1.0-shaped database
on disk (no ``seq`` column, no ``_sox_meta`` row) and verifies the runner
upgrades it correctly.
"""

from __future__ import annotations

import time
from pathlib import Path

import aiosqlite
import pytest

from sox_protocol.adapters.backing_stores.sqlite.migration_runner import (
    _MIGRATION_CHAIN,
    _column_exists,
    get_persisted_version,
    migrate,
)
from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

# ---------------------------------------------------------------------------
# v1.0 fixture: a database file in the pre-migration shape
# ---------------------------------------------------------------------------


_V1_0_SCHEMA = """
CREATE TABLE messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel       TEXT    NOT NULL,
    sender        TEXT    NOT NULL,
    body          TEXT    NOT NULL,
    correlation_id TEXT,
    sent_at       REAL    NOT NULL,
    delivered_to  TEXT    NOT NULL DEFAULT '[]'
);
CREATE INDEX idx_messages_channel ON messages(channel);
CREATE INDEX idx_messages_sent_at  ON messages(sent_at);
CREATE TABLE subscriptions (
    agent_id        TEXT NOT NULL,
    channel_pattern TEXT NOT NULL,
    PRIMARY KEY (agent_id, channel_pattern)
);
"""


async def _build_v1_0_db(path: Path, *, with_data: bool = True) -> None:
    """Create a v1.0-shaped database at *path*.

    No ``seq`` column, no ``_sox_meta`` row — exactly what shipped before
    the schema bump.
    """
    conn = await aiosqlite.connect(str(path))
    try:
        await conn.executescript(_V1_0_SCHEMA)
        if with_data:
            now = time.time()
            await conn.execute(
                "INSERT INTO messages (channel, sender, body, sent_at) "
                "VALUES (?, ?, ?, ?)",
                ("ch:a", "agent-1", '{"x": 1}', now),
            )
            await conn.execute(
                "INSERT INTO messages (channel, sender, body, sent_at) "
                "VALUES (?, ?, ?, ?)",
                ("ch:a", "agent-1", '{"x": 2}', now + 1.0),
            )
            await conn.execute(
                "INSERT INTO messages (channel, sender, body, sent_at) "
                "VALUES (?, ?, ?, ?)",
                ("ch:b", "agent-2", '{"y": 1}', now + 2.0),
            )
        await conn.commit()
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Migration runner unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_persisted_version_returns_zero_zero_on_empty(tmp_path: Path) -> None:
    """A bare database with no _sox_meta returns the sentinel '0.0'."""
    db = tmp_path / "fresh.db"
    await _build_v1_0_db(db, with_data=False)
    conn = await aiosqlite.connect(str(db))
    conn.row_factory = aiosqlite.Row
    try:
        v = await get_persisted_version(conn)
        assert v == "0.0"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_v1_0_db_gets_seq_column_after_initialize(tmp_path: Path) -> None:
    """End-to-end: v1.0 db → SqliteStore.initialize() → seq + reply_to columns exist."""
    db = tmp_path / "v1_0.db"
    await _build_v1_0_db(db, with_data=True)

    store = SqliteStore(str(db))
    await store.initialize()
    try:
        assert store._conn is not None
        assert await _column_exists(store._conn, "messages", "seq")
        assert await _column_exists(store._conn, "messages", "reply_to")
        v = await get_persisted_version(store._conn)
        assert v == "1.2"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_v1_0_to_v1_1_backfills_seq_per_channel(tmp_path: Path) -> None:
    """After migration, seq is per-channel monotone, ordered by sent_at."""
    db = tmp_path / "v1_0_with_data.db"
    await _build_v1_0_db(db, with_data=True)

    store = SqliteStore(str(db))
    await store.initialize()
    try:
        assert store._conn is not None
        async with store._conn.execute(
            "SELECT channel, seq, body FROM messages ORDER BY channel, seq"
        ) as cur:
            rows = list(await cur.fetchall())

        # Two messages on ch:a (seq 1, 2) and one on ch:b (seq 1).
        # Per-channel monotone; cross-channel independence preserved.
        ch_a = [r for r in rows if r["channel"] == "ch:a"]
        ch_b = [r for r in rows if r["channel"] == "ch:b"]
        assert [r["seq"] for r in ch_a] == [1, 2]
        assert [r["seq"] for r in ch_b] == [1]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_initialize_is_idempotent_on_migrated_db(tmp_path: Path) -> None:
    """Calling initialize() twice on a migrated db is a no-op."""
    db = tmp_path / "idempotent.db"
    await _build_v1_0_db(db, with_data=True)

    s1 = SqliteStore(str(db))
    await s1.initialize()
    await s1.close()

    s2 = SqliteStore(str(db))
    await s2.initialize()
    try:
        assert s2._conn is not None
        v = await get_persisted_version(s2._conn)
        assert v == "1.2"
        # Existing rows still present and consistent.
        async with s2._conn.execute("SELECT COUNT(*) FROM messages") as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == 3
    finally:
        await s2.close()


@pytest.mark.asyncio
async def test_fresh_db_records_target_version_directly(tmp_path: Path) -> None:
    """A fresh database (built from schema.sql) records target version
    without iterating the migration chain."""
    db = tmp_path / "fresh.db"
    store = SqliteStore(str(db))
    await store.initialize()
    try:
        assert store._conn is not None
        v = await get_persisted_version(store._conn)
        assert v == "1.2"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_send_works_against_migrated_v1_0_db(tmp_path: Path) -> None:
    """Regression test for the production-db bug: send() and recv()
    succeed against a database that started life at v1.0."""
    db = tmp_path / "regress.db"
    await _build_v1_0_db(db, with_data=True)

    store = SqliteStore(str(db))
    await store.initialize()
    try:
        await store.subscribe("agent-recv", "ch:a")
        msg_id, sent_at, seq, bp = await store.send(
            "ch:a", "agent-snd", {"new": "payload"}
        )
        assert isinstance(msg_id, str)
        assert isinstance(seq, int)
        assert seq >= 1
        msgs = await store.recv("agent-recv", ["ch:a"], max_messages=10)
        bodies = [m["body"] for m in msgs]
        # Recv sees existing v1.0-era rows (now backfilled) AND the new
        # message; assertion is just that recv doesn't error.
        assert any(b.get("new") == "payload" for b in bodies)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_refuses_to_downgrade(tmp_path: Path) -> None:
    """A database persisted at a newer version than the adapter knows
    about MUST raise rather than silently corrupt data."""
    db = tmp_path / "future.db"
    # Build a "future" db: v1.0 schema + _sox_meta saying we're at 99.0.
    await _build_v1_0_db(db, with_data=False)
    conn = await aiosqlite.connect(str(db))
    try:
        await conn.execute(
            "CREATE TABLE _sox_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        await conn.execute(
            "INSERT INTO _sox_meta (key, value) VALUES ('schema_version', '99.0')"
        )
        await conn.commit()
    finally:
        await conn.close()

    conn = await aiosqlite.connect(str(db))
    conn.row_factory = aiosqlite.Row
    try:
        with pytest.raises(ValueError, match="newer than the adapter"):
            await migrate(conn, "1.2")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_no_op_when_already_at_target(tmp_path: Path) -> None:
    """Migrate is a no-op when persisted == target; returns empty applied list."""
    db = tmp_path / "current.db"
    store = SqliteStore(str(db))
    await store.initialize()
    try:
        assert store._conn is not None
        starting, applied = await migrate(store._conn, "1.2")
        assert starting == "1.2"
        assert applied == []
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_apply_migration_skips_when_column_already_present(tmp_path: Path) -> None:
    """If the structural change is already in place (e.g. a v1.0 db that
    was hand-patched to add seq), _apply_migration must record the version
    bump without re-running the SQL — preventing a second ALTER TABLE
    from erroring out.
    """
    from sox_protocol.adapters.backing_stores.sqlite.migration_runner import (
        _apply_migration,
    )

    db = tmp_path / "hand_patched.db"
    # Build a v1.0 db, then manually add the seq column WITHOUT recording
    # the version bump in _sox_meta. Apply migration: should skip the
    # ALTER, just bump the version.
    await _build_v1_0_db(db, with_data=False)
    conn = await aiosqlite.connect(str(db))
    conn.row_factory = aiosqlite.Row
    try:
        await conn.execute(
            "ALTER TABLE messages ADD COLUMN seq INTEGER NOT NULL DEFAULT 0"
        )
        await conn.execute(
            "CREATE TABLE _sox_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        await conn.commit()

        await _apply_migration(conn, "1.0", "1.1")

        v = await get_persisted_version(conn)
        assert v == "1.1"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_chain_for_equal_versions_returns_empty(tmp_path: Path) -> None:
    """_chain_for must short-circuit when persisted == target."""
    from sox_protocol.adapters.backing_stores.sqlite.migration_runner import (
        _chain_for,
    )

    assert _chain_for("1.2", "1.2") == []


def test_migration_chain_is_contiguous() -> None:
    """The hard-coded migration chain must form an unbroken sequence."""
    if not _MIGRATION_CHAIN:
        return  # No migrations defined yet.
    for i in range(1, len(_MIGRATION_CHAIN)):
        prev_to = _MIGRATION_CHAIN[i - 1][1]
        next_from = _MIGRATION_CHAIN[i][0]
        assert prev_to == next_from, (
            f"Migration chain broken at step {i}: "
            f"{_MIGRATION_CHAIN[i - 1]!r} → {_MIGRATION_CHAIN[i]!r}"
        )
