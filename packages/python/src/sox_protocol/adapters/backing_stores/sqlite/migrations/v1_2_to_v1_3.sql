-- SOX Protocol — SQLite schema migration v1.2 → v1.3
-- Adds the `liveness` table so heartbeat state survives across MCP server
-- processes.  Prior to v1.3, ``SqliteStore.heartbeat()`` wrote to an
-- in-process dict (``self._liveness``) which meant a chat TUI session
-- couldn't see heartbeats from a Claude Code agent's separate MCP server
-- process — the agent roster was always empty in cross-process scenarios.
--
-- Safe to apply to existing databases: CREATE TABLE IF NOT EXISTS is
-- non-destructive; pre-existing in-memory liveness state is forfeit on
-- next restart but that was the bug we're fixing anyway.

CREATE TABLE IF NOT EXISTS liveness (
    agent_id     TEXT    PRIMARY KEY,
    status       TEXT    NOT NULL,        -- 'online' | 'busy' | 'offline'
    recorded_at  REAL    NOT NULL,        -- Unix epoch seconds (float)
    expires_at   REAL    NOT NULL,        -- Unix epoch seconds (float); > now ⇒ live
    namespace    TEXT
);

CREATE INDEX IF NOT EXISTS idx_liveness_expires_at ON liveness(expires_at);
