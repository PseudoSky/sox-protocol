# SPDX-License-Identifier: Apache-2.0
"""Schema-migration runner for the SQLite backing store.

Responsibilities
----------------
1. Ensure the ``_sox_meta`` table exists (it tracks the applied schema
   version of the database file).
2. Determine the chain of migrations needed to bring the database up to
   the adapter's target ``schema_version``.
3. Apply each migration in a single transaction, recording the new
   version on success.

The runner is designed to be safe against:

- A fresh, empty database (no ``_sox_meta`` row → version is "0.0",
  full chain runs).
- A database that already matches the target version (no migrations
  needed → no-op).
- A database newer than the adapter knows about (target version <
  persisted version → fail-fast with a clear error so a downgrade
  doesn't silently corrupt data).
- Mid-migration crash recovery (each migration runs in a transaction;
  the persisted version is only bumped after commit).

Spec reference: ``spec/ports/backing-store.md §2.3 — schema versioning``
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

_log = logging.getLogger(__name__)

# Directory containing the .sql migration files.
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# The ``_sox_meta`` table holds key/value rows describing the database state.
# Currently only ``schema_version`` is recorded but the table is structured
# as a generic kv store so future metadata (e.g. created_at, last_vacuum)
# can be added without further schema changes.
_META_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS _sox_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""


def _migration_filename(from_version: str, to_version: str) -> str:
    """Return the filename convention for a migration script."""
    f = from_version.replace(".", "_")
    t = to_version.replace(".", "_")
    return f"v{f}_to_v{t}.sql"


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a dotted version string into a comparable tuple of ints."""
    return tuple(int(p) for p in v.split("."))


# Ordered list of (from, to) migration steps that this adapter knows how to
# apply. The runner picks the contiguous chain starting at the persisted
# version and ending at the target.
#
# Adding a new schema version: append a (prev, new) tuple here AND drop a
# matching ``v<prev>_to_v<new>.sql`` in the migrations/ directory AND bump
# ``SqliteStore.schema_version`` AND update ``schema.sql`` to reflect the
# new shape for fresh databases.
_MIGRATION_CHAIN: list[tuple[str, str]] = [
    ("1.0", "1.1"),
]


async def get_persisted_version(conn: aiosqlite.Connection) -> str:
    """Return the ``schema_version`` recorded in ``_sox_meta``, or "0.0".

    A return of "0.0" means either the database is fresh or the
    ``_sox_meta`` table doesn't yet exist.  In both cases the caller
    should run the full migration chain from the earliest known version
    forward.
    """
    # Make sure the meta table exists so we can read from it.
    await conn.execute(_META_TABLE_DDL)
    await conn.commit()
    async with conn.execute(
        "SELECT value FROM _sox_meta WHERE key = 'schema_version'"
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return "0.0"
    return str(row[0])


async def _set_persisted_version(conn: aiosqlite.Connection, version: str) -> None:
    """Record *version* as the new persisted schema version."""
    await conn.execute(
        "INSERT INTO _sox_meta(key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (version,),
    )


async def _column_exists(
    conn: aiosqlite.Connection, table: str, column: str
) -> bool:
    """Return True if *table* has a *column* of the given name."""
    async with conn.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    return any(str(r[1]) == column for r in rows)


async def _apply_migration(
    conn: aiosqlite.Connection, from_version: str, to_version: str
) -> None:
    """Apply a single migration step ``from_version`` → ``to_version``.

    Runs the SQL script in a transaction.  If the migration's structural
    change has already been applied (e.g. column already exists from a
    fresh-schema install), the runner skips the script body and just
    records the version bump — this handles the case where ``schema.sql``
    has been kept up-to-date and a fresh database arrives at the latest
    shape directly without going through the migration chain.
    """
    sql_path = _MIGRATIONS_DIR / _migration_filename(from_version, to_version)
    if not sql_path.exists():  # pragma: no cover
        # Defensive: the chain in _MIGRATION_CHAIN should always have a
        # matching .sql file shipped in the migrations/ directory.  Reaching
        # this path means a packaging bug (chain entry without script).
        raise RuntimeError(
            f"Missing migration script: {sql_path} "
            f"(needed to upgrade {from_version} → {to_version})"
        )

    # Migration-specific structural-skip detection. For v1.0 → v1.1 we
    # skip if `seq` already exists (which it will on fresh databases that
    # got the latest schema.sql directly).
    needs_apply = True
    if (from_version, to_version) == ("1.0", "1.1"):
        if await _column_exists(conn, "messages", "seq"):
            needs_apply = False
            _log.info(
                "Migration %s → %s: structural change already present; "
                "recording version bump only.",
                from_version,
                to_version,
            )

    if needs_apply:
        sql = sql_path.read_text(encoding="utf-8")
        await conn.executescript(sql)

    await _set_persisted_version(conn, to_version)
    await conn.commit()
    _log.info("Applied schema migration: %s → %s", from_version, to_version)


def _chain_for(persisted: str, target: str) -> list[tuple[str, str]]:
    """Return the contiguous migration chain from *persisted* to *target*.

    Raises:
        ValueError: If *target* < *persisted*, or if *persisted* is not a
            recognised version, or if no chain links *persisted* to
            *target*.
    """
    if persisted == target:
        return []
    if _parse_version(persisted) > _parse_version(target):
        raise ValueError(
            f"Database schema version {persisted!r} is newer than the "
            f"adapter's target {target!r}; refusing to downgrade. "
            "Upgrade the sox-protocol package or restore from a snapshot."
        )

    # Walk the migration chain starting from `persisted`.
    if persisted == "0.0":  # pragma: no cover
        # Defensive: ``migrate()`` now always resolves "0.0" to either the
        # fresh-database short-circuit or the earliest known chain source
        # before invoking _chain_for.  This branch only fires if a caller
        # invokes _chain_for directly with persisted="0.0".
        return list(_MIGRATION_CHAIN)

    chain: list[tuple[str, str]] = []
    cursor = persisted
    while cursor != target:
        next_step = next(
            ((f, t) for (f, t) in _MIGRATION_CHAIN if f == cursor), None
        )
        if next_step is None:  # pragma: no cover
            # Defensive: a complete chain (validated by
            # test_migration_chain_is_contiguous) plus a known persisted
            # version means we can always walk forward.  This raises only
            # if the chain is misconfigured at packaging time.
            raise ValueError(
                f"No migration path from {cursor!r} to {target!r}; "
                f"known chain: {_MIGRATION_CHAIN!r}"
            )
        chain.append(next_step)
        cursor = next_step[1]
    return chain


async def migrate(
    conn: aiosqlite.Connection, target_version: str
) -> tuple[str, list[str]]:
    """Migrate *conn*'s database forward to *target_version*.

    Args:
        conn: An open ``aiosqlite.Connection`` with ``row_factory`` already
            configured by the caller.
        target_version: The schema version the adapter wants the database
            to be at when this returns.

    Returns:
        A 2-tuple ``(starting_version, applied_chain)`` where
        ``applied_chain`` is the list of ``"from→to"`` strings for each
        migration that ran.  Useful for logging and tests.

    Raises:
        ValueError: On unrecognised or down-revision target versions.
        RuntimeError: If a required migration script is missing.
    """
    starting = await get_persisted_version(conn)
    if starting == target_version:
        return starting, []

    if starting == "0.0":
        # Two possibilities:
        # (a) Fresh database — schema.sql just produced the latest shape.
        #     Detection: the latest-version structural marker column exists.
        # (b) Untracked existing database from a release predating the
        #     ``_sox_meta`` table.  schema.sql's ``IF NOT EXISTS`` saw the
        #     table and skipped, so the latest-version column is absent.
        #     Detection: the structural marker column is missing → treat
        #     the database as starting at the earliest known migration
        #     source so the chain runs in full.
        seq_column_present = await _column_exists(conn, "messages", "seq")
        if seq_column_present:
            await _set_persisted_version(conn, target_version)
            await conn.commit()
            return starting, []
        # Untracked v1.0 — fall through with starting bumped to the
        # earliest known migration source.
        if not _MIGRATION_CHAIN:  # pragma: no cover — defensive guard
            await _set_persisted_version(conn, target_version)
            await conn.commit()
            return starting, []
        starting = _MIGRATION_CHAIN[0][0]

    chain = _chain_for(starting, target_version)
    applied: list[str] = []
    for from_v, to_v in chain:
        await _apply_migration(conn, from_v, to_v)
        applied.append(f"{from_v}→{to_v}")

    return starting, applied
