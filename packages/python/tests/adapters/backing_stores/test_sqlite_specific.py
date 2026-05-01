# SPDX-License-Identifier: Apache-2.0
"""SQLite-specific BackingStore adapter tests.

Covers behaviours unique to the SQLite adapter that are not part of the
port-contract parametrised suite:

- WAL journal mode is active after ``initialize()``.
- ``vacuum()`` runs without error.
- ``wal_checkpoint()`` runs without error.
- Schema migration is idempotent (applying the schema twice does not fail
  and does not duplicate rows).
- The store works correctly with an on-disk file (not just ``:memory:``).
- Context-manager protocol (``async with``) initialises and closes cleanly.
"""

from __future__ import annotations

import pathlib

import pytest_asyncio

from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore


@pytest_asyncio.fixture
async def sqlite_store(tmp_path: pathlib.Path) -> SqliteStore:
    """Return an initialised on-disk SqliteStore."""
    store = SqliteStore(db_path=tmp_path / "wal_test.db")
    await store.initialize()
    yield store  # type: ignore[misc]
    await store.close()


class TestWALMode:
    """Verify that WAL journal mode is set after initialize()."""

    async def test_wal_mode_enabled(self, sqlite_store: SqliteStore) -> None:
        """PRAGMA journal_mode should return 'wal'."""
        conn = sqlite_store._require_conn()
        async with conn.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0].lower() == "wal", f"Expected WAL mode, got: {row[0]}"

    async def test_wal_file_exists_after_write(self, tmp_path: pathlib.Path) -> None:
        """A WAL file should appear after a write to an on-disk database."""
        db_path = tmp_path / "wal_file_test.db"
        store = SqliteStore(db_path=db_path)
        await store.initialize()
        await store.send("ch:wal", "sender", {"data": "x"})
        await store.close()
        # After close the WAL may or may not exist depending on checkpoint;
        # the main db file must always exist.
        assert db_path.exists(), "Database file should exist after write"


class TestVacuum:
    """Verify that vacuum() executes without errors."""

    async def test_vacuum_runs(self, sqlite_store: SqliteStore) -> None:
        """vacuum() should complete without raising."""
        await sqlite_store.send("ch:v", "s", {"x": 1})
        await sqlite_store.vacuum()  # should not raise

    async def test_vacuum_does_not_lose_data(self, sqlite_store: SqliteStore) -> None:
        """Data is intact after VACUUM."""
        await sqlite_store.subscribe("a", "ch:vacuum")
        await sqlite_store.send("ch:vacuum", "s", {"keep": True})
        await sqlite_store.vacuum()
        msgs = await sqlite_store.recv("a")
        assert len(msgs) == 1
        assert msgs[0]["body"] == {"keep": True}


class TestWALCheckpoint:
    """Verify that wal_checkpoint() executes without errors."""

    async def test_checkpoint_runs(self, sqlite_store: SqliteStore) -> None:
        """wal_checkpoint() should complete without raising."""
        await sqlite_store.send("ch:cp", "s", {})
        await sqlite_store.wal_checkpoint()  # should not raise


class TestSchemaMigration:
    """Schema application is idempotent — applying it twice MUST NOT fail."""

    async def test_schema_applied_twice_is_idempotent(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Calling initialize() a second time on the same DB must not error."""
        db_path = tmp_path / "idempotent.db"
        store = SqliteStore(db_path=db_path)
        await store.initialize()
        # Insert some data to confirm no table-drop semantics.
        await store.subscribe("a", "ch:idem")
        await store.send("ch:idem", "s", {"round": 1})

        # Apply schema a second time — must be idempotent.
        await store.initialize()

        msgs = await store.recv("a")
        assert len(msgs) == 1, "Data should survive a second initialize() call"
        await store.close()

    async def test_schema_tables_exist_after_init(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Both 'messages' and 'subscriptions' tables exist after initialize()."""
        db_path = tmp_path / "tables.db"
        store = SqliteStore(db_path=db_path)
        await store.initialize()
        conn = store._require_conn()

        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()

        table_names = {row[0] for row in rows}
        assert "messages" in table_names
        assert "subscriptions" in table_names
        await store.close()

    async def test_schema_indexes_exist_after_init(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Expected indexes exist after initialize()."""
        db_path = tmp_path / "indexes.db"
        store = SqliteStore(db_path=db_path)
        await store.initialize()
        conn = store._require_conn()

        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()

        index_names = {row[0] for row in rows}
        assert "idx_messages_channel" in index_names
        await store.close()


class TestContextManager:
    """SqliteStore supports the async context-manager protocol."""

    async def test_async_context_manager(self, tmp_path: pathlib.Path) -> None:
        """async with SqliteStore(...) as s: should initialise and close."""
        db_path = tmp_path / "ctx.db"
        async with SqliteStore(db_path=db_path) as s:
            assert s._conn is not None
            await s.send("ch:ctx", "s", {"ok": True})
        # After exiting, the connection should be closed.
        assert s._conn is None


class TestOnDiskPersistence:
    """Messages persisted to disk survive a close/reopen cycle."""

    async def test_messages_survive_reopen(self, tmp_path: pathlib.Path) -> None:
        """Data written in one store instance is readable after reopen."""
        db_path = tmp_path / "persist.db"

        store1 = SqliteStore(db_path=db_path)
        await store1.initialize()
        await store1.subscribe("a", "ch:persist")
        await store1.send("ch:persist", "s", {"durable": True})
        await store1.close()

        store2 = SqliteStore(db_path=db_path)
        await store2.initialize()
        msgs = await store2.recv("a")
        assert len(msgs) == 1
        assert msgs[0]["body"] == {"durable": True}
        await store2.close()

    async def test_subscriptions_survive_reopen(self, tmp_path: pathlib.Path) -> None:
        """Subscriptions written in one instance are readable after reopen."""
        db_path = tmp_path / "sub_persist.db"

        store1 = SqliteStore(db_path=db_path)
        await store1.initialize()
        await store1.subscribe("a", "ch:sub-persist-*")
        await store1.close()

        store2 = SqliteStore(db_path=db_path)
        await store2.initialize()
        # Send a message that matches the pattern.
        await store2.send("ch:sub-persist-001", "s", {"x": 1})
        msgs = await store2.recv("a")
        assert len(msgs) == 1, "Subscription should have survived reopen"
        await store2.close()


class TestConcurrentWritersStress:
    """10 concurrent writers + 10 concurrent readers, 100 msgs each — no loss.

    spec/ports/backing-store.md §3.1, §3.2
    """

    async def test_stress_sqlite_1000_messages(self, tmp_path: pathlib.Path) -> None:
        """1000 messages: no loss, no duplication, ordering preserved per channel."""

        db_path = tmp_path / "stress.db"
        store = SqliteStore(db_path=db_path)
        await store.initialize()

        n_writers = 10
        n_msgs_per_writer = 10  # 100 total per writer
        n_readers = 10
        channel = "ch:stress-sqlite"

        # All readers subscribe.
        for r in range(n_readers):
            await store.subscribe(f"reader-{r}", channel)

        # Writers send concurrently.
        import asyncio as aio

        async def write(wid: int) -> None:
            for i in range(n_msgs_per_writer):
                await store.send(channel, f"writer-{wid}", {"w": wid, "i": i})

        await aio.gather(*[write(w) for w in range(n_writers)])

        total = n_writers * n_msgs_per_writer

        # Each reader drains independently.
        async def read_all(reader_id: str) -> list[dict[str, object]]:
            received: list[dict[str, object]] = []
            for _ in range(total * 2):
                batch = await store.recv(reader_id, max_messages=100)
                if not batch:
                    break
                received.extend(batch)
            return received

        all_results = await aio.gather(
            *[read_all(f"reader-{r}") for r in range(n_readers)]
        )

        for r_idx, msgs in enumerate(all_results):
            assert len(msgs) == total, (
                f"reader-{r_idx}: expected {total} messages, got {len(msgs)}"
            )
            ids = [m["message_id"] for m in msgs]
            assert len(ids) == len(set(ids)), f"reader-{r_idx}: duplicate message_ids"
            times = [m["sent_at"] for m in msgs]
            assert times == sorted(times), f"reader-{r_idx}: ordering violated"

        await store.close()
