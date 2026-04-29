"""Async SQLite-backed enforcer state store.

Persists per-agent counters across hook invocations.  Every read-modify-write
is wrapped in a serialised ``BEGIN IMMEDIATE`` transaction so concurrent hook
processes cannot interleave.

Database location:
    ``${SOX_STATE_DIR}/state.db``  (default: ``~/.sox/state.db``).

WAL mode is enabled on first open so multiple readers can proceed concurrently
while a single writer holds the write lock.

Spec reference: ``spec/schemas/state.schema.json`` and CONTRACTS.md §3.2.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import aiosqlite

from sox_protocol.core.enforcer.events import EventType

# ---------------------------------------------------------------------------
# State dataclass  (mirrors spec/schemas/state.schema.json)
# ---------------------------------------------------------------------------


class State:
    """Per-agent cadence-enforcer state.

    Mutable (not frozen) because ``StateStore`` mutates fields in-place inside
    a transaction before persisting.

    Attributes:
        schema_version: Always ``"1.0"``.
        agent_id: Unique identifier of the agent this record belongs to.
        tool_calls_since_drain: Tool calls completed since last ``channel_recv``.
        last_drain_ts: Unix epoch of last ``channel_recv``, or ``None``.
        last_send_ts: Unix epoch of last ``channel_send``, or ``None``.
        sends_since_last_drain: ``channel_send`` calls since last ``channel_recv``.
        turns_since_last_drain: ``turn_started`` events since last ``channel_recv``.
    """

    __slots__ = (
        "schema_version",
        "agent_id",
        "tool_calls_since_drain",
        "last_drain_ts",
        "last_send_ts",
        "sends_since_last_drain",
        "turns_since_last_drain",
    )

    def __init__(
        self,
        agent_id: str,
        schema_version: Literal["1.0"] = "1.0",
        tool_calls_since_drain: int = 0,
        last_drain_ts: float | None = None,
        last_send_ts: float | None = None,
        sends_since_last_drain: int = 0,
        turns_since_last_drain: int = 0,
    ) -> None:
        self.schema_version: Literal["1.0"] = schema_version
        self.agent_id = agent_id
        self.tool_calls_since_drain = tool_calls_since_drain
        self.last_drain_ts = last_drain_ts
        self.last_send_ts = last_send_ts
        self.sends_since_last_drain = sends_since_last_drain
        self.turns_since_last_drain = turns_since_last_drain

    def __repr__(self) -> str:
        return (
            f"State(agent_id={self.agent_id!r}, "
            f"tool_calls_since_drain={self.tool_calls_since_drain}, "
            f"turns_since_last_drain={self.turns_since_last_drain}, "
            f"sends_since_last_drain={self.sends_since_last_drain}, "
            f"last_drain_ts={self.last_drain_ts}, "
            f"last_send_ts={self.last_send_ts})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, State):
            return NotImplemented
        return (
            self.agent_id == other.agent_id
            and self.tool_calls_since_drain == other.tool_calls_since_drain
            and self.last_drain_ts == other.last_drain_ts
            and self.last_send_ts == other.last_send_ts
            and self.sends_since_last_drain == other.sends_since_last_drain
            and self.turns_since_last_drain == other.turns_since_last_drain
        )


# ---------------------------------------------------------------------------
# Default DB path
# ---------------------------------------------------------------------------

_DEFAULT_DB_DIR = Path.home() / ".sox"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "state.db"


def _resolve_db_path() -> Path:
    """Return the state.db path from ``$SOX_STATE_DIR`` or the default."""
    env_dir = os.environ.get("SOX_STATE_DIR")
    if env_dir:
        return Path(env_dir) / "state.db"
    return _DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS enforcer_state (
    agent_id                TEXT PRIMARY KEY,
    schema_version          TEXT NOT NULL DEFAULT '1.0',
    tool_calls_since_drain  INTEGER NOT NULL DEFAULT 0,
    last_drain_ts           REAL,
    last_send_ts            REAL,
    sends_since_last_drain  INTEGER NOT NULL DEFAULT 0,
    turns_since_last_drain  INTEGER NOT NULL DEFAULT 0
);
"""


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------


class StateStore:
    """Async, concurrent-safe store for per-agent enforcer state.

    Uses SQLite in WAL mode so multiple readers proceed concurrently while the
    single writer holds the lock.  Every mutating operation uses
    ``BEGIN IMMEDIATE`` to serialise concurrent hook processes.

    Usage::

        store = StateStore()
        await store.open()
        state = await store.load("agent-alpha")
        state.tool_calls_since_drain += 1
        await store.save(state)
        await store.close()

    Or as an async context manager::

        async with StateStore() as store:
            state = await store.load("agent-alpha")
            ...
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _resolve_db_path()
        self._conn: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def open(self) -> None:
        """Open (and initialise if necessary) the SQLite database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(self._db_path))
        self._conn = conn
        # WAL for concurrent-safe reads alongside writes
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.executescript(_DDL)
        await conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> "StateStore":
        await self.open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("StateStore is not open; call open() or use as async context manager.")
        return self._conn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def load(self, agent_id: str) -> State:
        """Load state for *agent_id*, returning a cold-start default if absent.

        Args:
            agent_id: The agent whose state to load.

        Returns:
            The persisted :class:`State`, or a zeroed default if this is the
            first time the agent has been seen.
        """
        conn = self._require_conn()
        async with conn.execute(
            "SELECT schema_version, tool_calls_since_drain, last_drain_ts, "
            "last_send_ts, sends_since_last_drain, turns_since_last_drain "
            "FROM enforcer_state WHERE agent_id = ?",
            (agent_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return State(agent_id=agent_id)

        return State(
            agent_id=agent_id,
            schema_version=row[0],
            tool_calls_since_drain=row[1],
            last_drain_ts=row[2],
            last_send_ts=row[3],
            sends_since_last_drain=row[4],
            turns_since_last_drain=row[5],
        )

    async def save(self, state: State) -> None:
        """Persist *state* atomically using ``INSERT OR REPLACE``.

        Args:
            state: The :class:`State` instance to persist.
        """
        conn = self._require_conn()
        await conn.execute(
            """
            INSERT INTO enforcer_state
                (agent_id, schema_version, tool_calls_since_drain,
                 last_drain_ts, last_send_ts, sends_since_last_drain,
                 turns_since_last_drain)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                schema_version          = excluded.schema_version,
                tool_calls_since_drain  = excluded.tool_calls_since_drain,
                last_drain_ts           = excluded.last_drain_ts,
                last_send_ts            = excluded.last_send_ts,
                sends_since_last_drain  = excluded.sends_since_last_drain,
                turns_since_last_drain  = excluded.turns_since_last_drain
            """,
            (
                state.agent_id,
                state.schema_version,
                state.tool_calls_since_drain,
                state.last_drain_ts,
                state.last_send_ts,
                state.sends_since_last_drain,
                state.turns_since_last_drain,
            ),
        )
        await conn.commit()

    async def apply_event(self, agent_id: str, event_type: EventType, timestamp: float) -> State:
        """Atomically load, mutate, save, and return state for *event_type*.

        This is the idiomatic helper used by runtime adapters that call
        ``decide()`` via a two-step load→decide→save pattern.  The mutation
        here is *state only*; ``decide()`` itself is a pure function that
        never touches the store.

        Note:
            This method does NOT call ``decide()``.  The caller is responsible
            for calling ``decide(event, state, policy)`` on the returned state
            before or after calling this method depending on its flow.

        Args:
            agent_id: Agent to update.
            event_type: The event that occurred.
            timestamp: Unix epoch seconds of the event.

        Returns:
            The *updated* :class:`State` after applying event-specific mutations.
        """
        conn = self._require_conn()
        # Serialise concurrent writers with BEGIN IMMEDIATE
        await conn.execute("BEGIN IMMEDIATE")
        try:
            async with conn.execute(
                "SELECT schema_version, tool_calls_since_drain, last_drain_ts, "
                "last_send_ts, sends_since_last_drain, turns_since_last_drain "
                "FROM enforcer_state WHERE agent_id = ?",
                (agent_id,),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:
                state = State(agent_id=agent_id)
            else:
                state = State(
                    agent_id=agent_id,
                    schema_version=row[0],
                    tool_calls_since_drain=row[1],
                    last_drain_ts=row[2],
                    last_send_ts=row[3],
                    sends_since_last_drain=row[4],
                    turns_since_last_drain=row[5],
                )

            # Apply mutation
            if event_type == EventType.channel_recv:
                state.tool_calls_since_drain = 0
                state.sends_since_last_drain = 0
                state.turns_since_last_drain = 0
                state.last_drain_ts = timestamp
            elif event_type == EventType.tool_used:
                state.tool_calls_since_drain += 1
            elif event_type == EventType.channel_send:
                state.last_send_ts = timestamp
                state.sends_since_last_drain += 1
            elif event_type == EventType.turn_started:
                state.turns_since_last_drain += 1
            # stop_requested: no state mutation required

            await conn.execute(
                """
                INSERT INTO enforcer_state
                    (agent_id, schema_version, tool_calls_since_drain,
                     last_drain_ts, last_send_ts, sends_since_last_drain,
                     turns_since_last_drain)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    schema_version          = excluded.schema_version,
                    tool_calls_since_drain  = excluded.tool_calls_since_drain,
                    last_drain_ts           = excluded.last_drain_ts,
                    last_send_ts            = excluded.last_send_ts,
                    sends_since_last_drain  = excluded.sends_since_last_drain,
                    turns_since_last_drain  = excluded.turns_since_last_drain
                """,
                (
                    state.agent_id,
                    state.schema_version,
                    state.tool_calls_since_drain,
                    state.last_drain_ts,
                    state.last_send_ts,
                    state.sends_since_last_drain,
                    state.turns_since_last_drain,
                ),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

        return state
