-- Migration: 1.0 → 1.1
-- Adds the per-channel monotone sequence number column to messages.
-- Backfills existing rows from the AUTOINCREMENT id, partitioned by
-- channel and ordered by sent_at, so existing recv() calls on a migrated
-- database still see consistent sequence ordering.
--
-- Idempotent: ADD COLUMN with a DEFAULT is a no-op if the column already
-- exists (well, technically it errors — the runner checks
-- pragma_table_info before applying so we only run when needed).
--
-- Spec reference: spec/ports/backing-store.md §2.1, §3.1

-- 1. Add the column with default 0 so existing rows are valid.
ALTER TABLE messages ADD COLUMN seq INTEGER NOT NULL DEFAULT 0;

-- 2. Backfill seq for every existing row, partitioned by channel,
--    ordered by sent_at then id (matches the recv() ordering contract).
WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY channel
               ORDER BY sent_at ASC, id ASC
           ) AS rn
    FROM messages
)
UPDATE messages
SET    seq = (SELECT rn FROM ranked WHERE ranked.id = messages.id)
WHERE  seq = 0;
