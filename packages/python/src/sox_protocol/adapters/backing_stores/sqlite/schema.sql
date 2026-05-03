-- SOX Protocol — SQLite backing-store schema
-- Version: 1.0
-- Applied at adapter startup; idempotent (uses IF NOT EXISTS throughout).

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel       TEXT    NOT NULL,
    sender        TEXT    NOT NULL,
    body          TEXT    NOT NULL,           -- JSON-encoded object
    correlation_id TEXT,                      -- NULL when not supplied
    sent_at       REAL    NOT NULL,           -- Unix epoch seconds (float)
    delivered_to  TEXT    NOT NULL DEFAULT '[]',  -- JSON array of agent_ids that have drained
    seq           INTEGER NOT NULL DEFAULT 0, -- per-channel monotone sequence number (>=1)
    reply_to      TEXT    DEFAULT NULL        -- parent message_id for threading (NULL = top-level)
);

CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel);
CREATE INDEX IF NOT EXISTS idx_messages_sent_at  ON messages(sent_at);

CREATE TABLE IF NOT EXISTS subscriptions (
    agent_id        TEXT NOT NULL,
    channel_pattern TEXT NOT NULL,
    PRIMARY KEY (agent_id, channel_pattern)
);
