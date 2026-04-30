# SPDX-License-Identifier: Apache-2.0
"""Async SQLite backing-store adapter.

Uses ``aiosqlite`` with WAL journal mode for concurrent-read / single-writer
safety.  This is the v0 default backing store for the SOX MCP server.

Spec reference: ``spec/ports/backing-store.md``
Contract binding: ``sox_protocol.core.ports.backing_store.BackingStore``

Limitations (documented per §7.5 of CONTRACTS.md):
- Maximum message body size is constrained by SQLite's default page / row
  limits (~1 GB per row in practice; not an operational concern for LLM
  payloads).
- ``watch()`` is implemented via async polling (configurable interval,
  default 50 ms).  It is not a true push mechanism; latency is bounded by
  the poll interval.
- The ``delivered_to`` column stores a JSON array of agent IDs that have
  drained a given message.  Messages are never hard-deleted; operators
  should run ``VACUUM`` periodically for long-lived stores.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import time
from importlib.resources import files
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

from sox_protocol.core.ports.backing_store import BackingStore

# Poll interval for the watch() loop (seconds).
_WATCH_POLL_INTERVAL: float = 0.05


def _load_schema() -> str:
    """Return the SQL schema string from the sibling schema.sql file."""
    schema_path = Path(__file__).parent / "schema.sql"
    return schema_path.read_text(encoding="utf-8")


def _matches_pattern(channel: str, pattern: str) -> bool:
    """Return True if *channel* matches *pattern* using Unix glob semantics."""
    return fnmatch.fnmatchcase(channel, pattern)


def _build_message(row: aiosqlite.Row) -> dict[str, object]:
    """Convert a ``messages`` table row into a spec-conformant message dict."""
    return {
        "message_id": str(row["id"]),
        "channel": row["channel"],
        "sender": row["sender"],
        "body": json.loads(row["body"]),
        "correlation_id": row["correlation_id"],
        "sent_at": row["sent_at"],
    }


class SqliteStore(BackingStore):
    """Async SQLite implementation of the ``BackingStore`` port.

    Args:
        db_path: Path to the SQLite database file, or ``":memory:"`` for an
            in-process ephemeral store (useful for testing; does NOT survive
            restart).
        watch_poll_interval: Seconds between poll iterations in ``watch()``.
            Lower values reduce latency at the cost of more I/O.

    Usage::

        store = SqliteStore("sox.db")
        await store.initialize()
        msg_id, sent_at = await store.send("ticket:X", "agent-a", {"text": "hi"})
    """

    schema_version: str = "1.0"

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        watch_poll_interval: float = _WATCH_POLL_INTERVAL,
    ) -> None:
        self._db_path = str(db_path)
        self._watch_poll_interval = watch_poll_interval
        self._conn: aiosqlite.Connection | None = None
        # Condition variable that watch() loops wait on.  Signalled by send().
        self._new_message_event: asyncio.Event = asyncio.Event()
        # Serialises concurrent recv() calls (SELECT + UPDATE must be atomic
        # per-agent; an asyncio.Lock prevents interleaving across coroutines).
        self._recv_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open the database connection and apply the schema.

        Must be called before any other method.  Idempotent — safe to call
        multiple times (schema uses ``CREATE TABLE IF NOT EXISTS``).
        """
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        # Enable WAL mode for concurrent reads alongside a single writer.
        await self._conn.execute("PRAGMA journal_mode=WAL")
        # Enforce foreign-key constraints (not strictly required here but
        # good practice for future schema additions).
        await self._conn.execute("PRAGMA foreign_keys=ON")
        # Apply the schema (idempotent via IF NOT EXISTS).
        schema_sql = _load_schema()
        await self._conn.executescript(schema_sql)
        await self._conn.commit()

    async def close(self) -> None:
        """Close the database connection cleanly."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> "SqliteStore":
        await self.initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError(
                "SqliteStore.initialize() must be called before using the store."
            )
        return self._conn

    async def _get_patterns_for_agent(self, agent_id: str) -> list[str]:
        """Return all channel patterns registered by *agent_id*."""
        conn = self._require_conn()
        async with conn.execute(
            "SELECT channel_pattern FROM subscriptions WHERE agent_id = ?",
            (agent_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [row["channel_pattern"] for row in rows]

    def _agent_matches_channel(self, patterns: list[str], channel: str) -> bool:
        """Return True if any of *patterns* matches *channel*."""
        return any(_matches_pattern(channel, p) for p in patterns)

    # ------------------------------------------------------------------
    # BackingStore interface
    # ------------------------------------------------------------------

    async def send(
        self,
        channel: str,
        sender: str,
        body: dict[str, object],
        correlation_id: str | None = None,
    ) -> tuple[str, float]:
        """Persist a message and return ``(message_id, sent_at)``.

        Spec: ``spec/ports/backing-store.md §2.1``, ``§3.1``
        """
        conn = self._require_conn()
        sent_at = time.time()
        body_json = json.dumps(body)
        async with conn.execute(
            """
            INSERT INTO messages (channel, sender, body, correlation_id, sent_at, delivered_to)
            VALUES (?, ?, ?, ?, ?, '[]')
            """,
            (channel, sender, body_json, correlation_id, sent_at),
        ) as cur:
            row_id = cur.lastrowid
        await conn.commit()
        # Wake any watch() loops that are sleeping.
        self._new_message_event.set()
        return (str(row_id), sent_at)

    async def recv(
        self,
        agent_id: str,
        channels: list[str] | None = None,
        max_messages: int = 50,
    ) -> list[dict[str, object]]:
        """Drain and atomically mark messages delivered for *agent_id*.

        Spec: ``spec/ports/backing-store.md §2.2``, ``§3.2``

        Atomicity is enforced with ``_recv_lock`` so that the SELECT and UPDATE
        sequence for one coroutine completes before another coroutine's SELECT
        runs.  This is necessary because aiosqlite suspends at every ``await``,
        allowing other coroutines to interleave between our SELECT and UPDATE.
        """
        async with self._recv_lock:
            return await self._recv_locked(agent_id, channels, max_messages)

    async def _recv_locked(
        self,
        agent_id: str,
        channels: list[str] | None,
        max_messages: int,
    ) -> list[dict[str, object]]:
        conn = self._require_conn()

        # Determine which channels to drain.
        if channels is None:
            patterns = await self._get_patterns_for_agent(agent_id)
            if not patterns:
                return []
        else:
            patterns = []

        # Fetch candidates: messages not yet delivered to this agent.
        # We load them in bulk and filter in Python for glob matching.
        #
        # Atomicity: the _recv_lock ensures no other concurrent recv() can
        # interleave between our SELECT and UPDATE within this process.
        async with conn.execute(
            """
            SELECT id, channel, sender, body, correlation_id, sent_at, delivered_to
            FROM messages
            ORDER BY channel, sent_at ASC, id ASC
            """
        ) as cur:
            all_rows = await cur.fetchall()

        # Filter to messages not yet delivered to this agent, on subscribed
        # channels (or explicitly requested channels).
        eligible: list[aiosqlite.Row] = []
        for row in all_rows:
            delivered_to: list[str] = json.loads(row["delivered_to"])
            if agent_id in delivered_to:
                continue
            ch: str = row["channel"]
            if channels is not None:
                if ch not in channels:
                    continue
            else:
                if not self._agent_matches_channel(patterns, ch):
                    continue
            eligible.append(row)
            if len(eligible) >= max_messages:
                break

        if not eligible:
            return []

        # Atomically mark all eligible messages as delivered to this agent.
        for row in eligible:
            delivered_to = json.loads(row["delivered_to"])
            delivered_to.append(agent_id)
            await conn.execute(
                "UPDATE messages SET delivered_to = ? WHERE id = ?",
                (json.dumps(delivered_to), row["id"]),
            )
        await conn.commit()

        return [_build_message(r) for r in eligible]

    async def subscribe(self, agent_id: str, pattern: str) -> list[str]:
        """Register a subscription and return currently matching channels.

        Spec: ``spec/ports/backing-store.md §2.3``
        """
        conn = self._require_conn()
        # Idempotent upsert.
        await conn.execute(
            """
            INSERT OR IGNORE INTO subscriptions (agent_id, channel_pattern)
            VALUES (?, ?)
            """,
            (agent_id, pattern),
        )
        await conn.commit()

        # Return currently-known channels matching the pattern.
        async with conn.execute(
            "SELECT DISTINCT channel FROM messages"
        ) as cur:
            rows = await cur.fetchall()
        return [row["channel"] for row in rows if _matches_pattern(row["channel"], pattern)]

    async def list_channels(self, since: float | None = None) -> list[dict[str, object]]:
        """Return known channels with subscriber counts.

        Spec: ``spec/ports/backing-store.md §2.4``
        """
        conn = self._require_conn()

        # Collect channels from messages table (with optional time filter).
        if since is not None:
            async with conn.execute(
                "SELECT DISTINCT channel FROM messages WHERE sent_at >= ?",
                (since,),
            ) as cur:
                msg_rows = await cur.fetchall()
        else:
            cutoff = time.time() - 86400.0  # last 24 hours
            async with conn.execute(
                "SELECT DISTINCT channel FROM messages WHERE sent_at >= ?",
                (cutoff,),
            ) as cur:
                msg_rows = await cur.fetchall()

        # Collect channels from subscriptions table.
        async with conn.execute(
            "SELECT DISTINCT channel_pattern FROM subscriptions"
        ) as cur:
            sub_rows = await cur.fetchall()

        # Union both sets.
        channels: set[str] = set()
        for row in msg_rows:
            channels.add(row["channel"])
        # Subscription patterns that are exact names (no glob) count too.
        for row in sub_rows:
            p: str = row["channel_pattern"]
            if "*" not in p and "?" not in p and "[" not in p:
                channels.add(p)

        # Count subscribers per channel.
        async with conn.execute(
            "SELECT agent_id, channel_pattern FROM subscriptions"
        ) as cur:
            all_subs = await cur.fetchall()

        result: list[dict[str, object]] = []
        for ch in sorted(channels):
            count = sum(
                1
                for sub in all_subs
                if _matches_pattern(ch, sub["channel_pattern"])
            )
            result.append({"name": ch, "subscriber_count": count})
        return result

    async def watch(self, agent_id: str) -> AsyncIterator[dict[str, object]]:
        """Async generator yielding new messages for *agent_id*.

        Implemented as a polling loop with a configurable interval (default
        50 ms).  The loop wakes early when ``send()`` signals
        ``_new_message_event``, keeping latency low under active traffic.

        Spec: ``spec/ports/backing-store.md §2.5``, ``§6``
        """
        # Track the highest message id already yielded so we never re-yield.
        last_seen_id: int = await self._get_max_delivered_id(agent_id)

        while True:
            # Wait for signal or poll timeout — whichever comes first.
            try:
                await asyncio.wait_for(
                    self._new_message_event.wait(),
                    timeout=self._watch_poll_interval,
                )
            except asyncio.TimeoutError:
                pass
            finally:
                self._new_message_event.clear()

            # Fetch messages this agent hasn't seen yet.
            messages = await self._fetch_new_for_agent(agent_id, last_seen_id)
            for msg in messages:
                row_id = int(str(msg["message_id"]))
                if row_id > last_seen_id:
                    last_seen_id = row_id
                yield msg

    async def _get_max_delivered_id(self, agent_id: str) -> int:
        """Return the highest message id already delivered to *agent_id*.

        This is used by ``watch()`` to skip messages that were delivered
        before the current watch invocation started, honouring the
        "non-duplicating across watch calls" guarantee
        (``spec/ports/backing-store.md §2.5``).
        """
        conn = self._require_conn()
        async with conn.execute(
            "SELECT id, delivered_to FROM messages ORDER BY id ASC"
        ) as cur:
            rows = await cur.fetchall()
        max_id = 0
        for row in rows:
            delivered_to: list[str] = json.loads(row["delivered_to"])
            if agent_id in delivered_to:
                max_id = max(max_id, row["id"])
        return max_id

    async def _fetch_new_for_agent(
        self, agent_id: str, after_id: int
    ) -> list[dict[str, object]]:
        """Return messages with id > *after_id* that match *agent_id*'s subs.

        Messages already in ``delivered_to`` for this agent are excluded
        (they were drained by a ``recv`` call).
        """
        conn = self._require_conn()
        patterns = await self._get_patterns_for_agent(agent_id)
        if not patterns:
            return []

        async with conn.execute(
            """
            SELECT id, channel, sender, body, correlation_id, sent_at, delivered_to
            FROM messages
            WHERE id > ?
            ORDER BY channel, sent_at ASC, id ASC
            """,
            (after_id,),
        ) as cur:
            rows = await cur.fetchall()

        result: list[dict[str, object]] = []
        for row in rows:
            delivered_to: list[str] = json.loads(row["delivered_to"])
            if agent_id in delivered_to:
                continue
            if not self._agent_matches_channel(patterns, row["channel"]):
                continue
            result.append(_build_message(row))
        return result

    # ------------------------------------------------------------------
    # SQLite-specific extras (not part of the BackingStore port)
    # ------------------------------------------------------------------

    async def vacuum(self) -> None:
        """Run ``VACUUM`` to reclaim disk space.

        Not part of the ``BackingStore`` port; SQLite-specific maintenance.
        """
        conn = self._require_conn()
        await conn.execute("VACUUM")

    async def wal_checkpoint(self) -> None:
        """Issue a WAL checkpoint to merge the write-ahead log.

        Not part of the ``BackingStore`` port; SQLite-specific.
        """
        conn = self._require_conn()
        await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
