# SPDX-License-Identifier: Apache-2.0
"""SQLite-backed BackingStore adapter (WAL mode, aiosqlite)."""

from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

__all__ = ["SqliteStore"]
