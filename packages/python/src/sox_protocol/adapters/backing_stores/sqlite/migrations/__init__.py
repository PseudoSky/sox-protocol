# SPDX-License-Identifier: Apache-2.0
"""SQLite backing-store schema migrations.

Each migration is a pair (from_version, to_version) implemented as either a
``.sql`` file in this directory or a Python callable.  The runner in
:mod:`sox_protocol.adapters.backing_stores.sqlite.migration_runner`
discovers and applies them in order.

Migration discipline
--------------------
1. ``schema.sql`` is the *current target* schema and MUST always be the
   newest version.  It is applied verbatim to fresh databases via
   ``CREATE TABLE IF NOT EXISTS``.
2. Existing databases are migrated forward via the migration files in this
   directory: ``v<from>_to_<to>.sql`` (dots in versions become underscores).
3. Migrations MUST be idempotent at the SQL level — i.e. they should
   tolerate being applied to a database that has already been migrated
   (using ``ADD COLUMN`` with ``DEFAULT`` clauses, ``IF NOT EXISTS``, etc.)
   so a partial-write recovery does not corrupt data.
4. Each migration runs in a single transaction; on error the transaction
   is rolled back and the persisted ``schema_version`` is unchanged.
5. Migrations MUST NOT remove columns or rename tables in v1.x — additive
   only.  Destructive migrations are deferred to v2 with a major-version
   bump and an explicit operator-run upgrade tool.

Spec reference
--------------
``spec/ports/backing-store.md §2.3 — schema versioning``
"""

from __future__ import annotations  # pragma: no cover
