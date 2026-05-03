-- SOX Protocol — SQLite schema migration v1.1 → v1.2
-- Adds the reply_to column to the messages table for threading support.
-- Safe to apply to existing databases: ALTER TABLE ADD COLUMN with DEFAULT NULL
-- is non-destructive and existing rows get NULL for the new column.

ALTER TABLE messages ADD COLUMN reply_to TEXT DEFAULT NULL;
