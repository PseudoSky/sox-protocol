# SPDX-License-Identifier: Apache-2.0
"""Tests for new BackingStore methods (ack, heartbeat, list_agents, replay,
group_create/invite/join/leave/list_members) across all three adapters,
plus uncovered branches in memory/store.py.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sox_protocol.adapters.backing_stores.filesystem.store import FilesystemStore
from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
async def mem() -> MemoryStore:
    store = MemoryStore()
    await store.initialize()
    return store


@pytest.fixture()
async def sqlite_mem() -> SqliteStore:
    store = SqliteStore(":memory:")
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture()
def tmp_fs(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
async def fs(tmp_fs: Path) -> FilesystemStore:
    store = FilesystemStore(root=tmp_fs)
    await store.initialize()
    return store


# ===========================================================================
# memory/store.py — uncovered branches
# ===========================================================================


class TestMemoryStoreUncoveredBranches:
    """Cover lines 96-97, 100, 110, 281-288, 341."""

    @pytest.mark.asyncio
    async def test_async_context_manager_enter_exit(self) -> None:
        """Lines 96-97, 100: __aenter__ / __aexit__."""
        async with MemoryStore() as store:
            assert store is not None
            # send something to confirm store is usable
            await store.subscribe("a", "ch/*")
            msg_id, *_ = await store.send("ch/1", "a", {"x": 1})
            assert msg_id is not None

    @pytest.mark.asyncio
    async def test_matches_agent_true(self, mem: MemoryStore) -> None:
        """Line 110: _matches_agent returns True when pattern matches."""
        await mem.subscribe("agent-x", "ch/*")
        assert mem._matches_agent("ch/hello", "agent-x") is True

    @pytest.mark.asyncio
    async def test_matches_agent_false(self, mem: MemoryStore) -> None:
        """Line 110: _matches_agent returns False when no pattern matches."""
        await mem.subscribe("agent-x", "other/*")
        assert mem._matches_agent("ch/hello", "agent-x") is False

    @pytest.mark.asyncio
    async def test_matches_agent_no_subscriptions(self, mem: MemoryStore) -> None:
        """Line 110: _matches_agent returns False when agent has no subs."""
        assert mem._matches_agent("ch/hello", "no-subs-agent") is False

    @pytest.mark.asyncio
    async def test_unsubscribe_clears_pending_messages(self, mem: MemoryStore) -> None:
        """Lines 281-288: unsubscribe marks unread messages as delivered."""
        await mem.subscribe("agent-u", "ch/*")
        await mem.send("ch/1", "sender", {"k": "v"})
        await mem.send("ch/2", "sender", {"k": "v2"})

        removed, pending_cleared = await mem.unsubscribe("agent-u", ["ch/*"])
        assert "ch/*" in removed
        assert pending_cleared == 2

    @pytest.mark.asyncio
    async def test_unsubscribe_partial_patterns(self, mem: MemoryStore) -> None:
        """Lines 281-288: unsubscribe only clears messages for removed patterns."""
        await mem.subscribe("agent-u2", "ch/*")
        await mem.subscribe("agent-u2", "other/*")
        await mem.send("ch/1", "s", {"x": 1})
        await mem.send("other/1", "s", {"x": 2})

        removed, pending_cleared = await mem.unsubscribe("agent-u2", ["ch/*"])
        assert removed == ["ch/*"]
        assert pending_cleared == 1

    @pytest.mark.asyncio
    async def test_list_agents_status_filter_stale(self, mem: MemoryStore) -> None:
        """Line 341: list_agents filters out non-matching status."""
        # Record heartbeat with expires_at in the past
        now = time.time()
        mem._liveness["stale-agent"] = {
            "status": "online",
            "recorded_at": now - 100,
            "expires_at": now - 50,  # already expired
        }
        mem._liveness["online-agent"] = {
            "status": "online",
            "recorded_at": now,
            "expires_at": now + 30,
        }

        result = await mem.list_agents(status_filter=["online"])
        agent_ids = [r["agent_id"] for r in result]
        assert "online-agent" in agent_ids
        assert "stale-agent" not in agent_ids

    @pytest.mark.asyncio
    async def test_list_agents_namespace_filter(self, mem: MemoryStore) -> None:
        """list_agents filters by namespace field in the liveness record."""
        now = time.time()
        mem._liveness["agent-1"] = {
            "status": "online",
            "recorded_at": now,
            "expires_at": now + 30,
            "namespace": "ns1",
        }
        mem._liveness["agent-2"] = {
            "status": "online",
            "recorded_at": now,
            "expires_at": now + 30,
            "namespace": "other",
        }

        result = await mem.list_agents(namespace="ns1")
        agent_ids = [r["agent_id"] for r in result]
        assert "agent-1" in agent_ids
        assert "agent-2" not in agent_ids


# ===========================================================================
# memory/store.py — new BackingStore methods
# ===========================================================================


class TestMemoryStoreNewMethods:

    @pytest.mark.asyncio
    async def test_ack_returns_correct_shape(self, mem: MemoryStore) -> None:
        result = await mem.ack("agent-a", "msg-1", "received")
        assert result["message_id"] == "msg-1"
        assert result["status"] == "received"
        assert "acked_at" in result

    @pytest.mark.asyncio
    async def test_ack_with_reason(self, mem: MemoryStore) -> None:
        result = await mem.ack("agent-a", "msg-2", "nack", reason="bad data")
        assert result["status"] == "nack"

    @pytest.mark.asyncio
    async def test_heartbeat_returns_correct_shape(self, mem: MemoryStore) -> None:
        result = await mem.heartbeat("agent-a", "online")
        assert result["agent_id"] == "agent-a"
        assert result["status"] == "online"
        assert "recorded_at" in result
        assert "expires_at" in result

    @pytest.mark.asyncio
    async def test_heartbeat_custom_ttl(self, mem: MemoryStore) -> None:
        result = await mem.heartbeat("agent-b", "busy", ttl=60)
        assert result["expires_at"] > result["recorded_at"] + 50

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, mem: MemoryStore) -> None:
        result = await mem.list_agents()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_agents_after_heartbeat(self, mem: MemoryStore) -> None:
        await mem.heartbeat("agent-c", "online")
        result = await mem.list_agents()
        assert any(r["agent_id"] == "agent-c" for r in result)

    @pytest.mark.asyncio
    async def test_replay_basic(self, mem: MemoryStore) -> None:
        await mem.subscribe("a", "replay-ch")
        await mem.send("replay-ch", "a", {"n": 1})
        await mem.send("replay-ch", "a", {"n": 2})
        msgs, has_more = await mem.replay("replay-ch", since=0)
        assert len(msgs) == 2
        assert has_more is False

    @pytest.mark.asyncio
    async def test_replay_with_limit(self, mem: MemoryStore) -> None:
        await mem.subscribe("a", "lim-ch")
        for i in range(5):
            await mem.send("lim-ch", "a", {"n": i})
        msgs, has_more = await mem.replay("lim-ch", since=0, limit=3)
        assert len(msgs) == 3
        assert has_more is True

    @pytest.mark.asyncio
    async def test_replay_with_until(self, mem: MemoryStore) -> None:
        await mem.subscribe("a", "until-ch")
        for i in range(4):
            await mem.send("until-ch", "a", {"n": i})
        msgs, _ = await mem.replay("until-ch", since=1, until=2)
        seqs = [m["seq"] for m in msgs]
        assert all(1 <= s <= 2 for s in seqs)

    @pytest.mark.asyncio
    async def test_group_create(self, mem: MemoryStore) -> None:
        result = await mem.group_create("creator-a", "mygroup")
        assert result["group_id"] == "group/mygroup"
        assert "created_at" in result

    @pytest.mark.asyncio
    async def test_group_create_auto_id(self, mem: MemoryStore) -> None:
        result = await mem.group_create("creator-b")
        assert result["group_id"].startswith("group/grp-")

    @pytest.mark.asyncio
    async def test_group_invite(self, mem: MemoryStore) -> None:
        await mem.group_create("creator-c", "grp1")
        result = await mem.group_invite("creator-c", "group/grp1", "invitee-x")
        assert result["invited"] is True
        assert result["agent_id"] == "invitee-x"

    @pytest.mark.asyncio
    async def test_group_invite_non_member_raises(self, mem: MemoryStore) -> None:
        await mem.group_create("creator-d", "grp2")
        with pytest.raises(ValueError, match="not an active member"):
            await mem.group_invite("not-a-member", "group/grp2", "invitee-y")

    @pytest.mark.asyncio
    async def test_group_join(self, mem: MemoryStore) -> None:
        await mem.group_create("c", "grp3")
        await mem.group_invite("c", "group/grp3", "joiner")
        result = await mem.group_join("joiner", "group/grp3")
        assert result["joined"] is True
        assert result["member_count"] == 2

    @pytest.mark.asyncio
    async def test_group_leave(self, mem: MemoryStore) -> None:
        await mem.group_create("c", "grp4")
        result = await mem.group_leave("c", "group/grp4")
        assert result["left"] is True
        assert result["group_id"] == "group/grp4"

    @pytest.mark.asyncio
    async def test_group_list_members(self, mem: MemoryStore) -> None:
        await mem.group_create("c", "grp5")
        result = await mem.group_list_members("c", "group/grp5")
        assert result["group_id"] == "group/grp5"
        assert isinstance(result["members"], list)
        assert len(result["members"]) == 1


# ===========================================================================
# sqlite/store.py — new BackingStore methods
# ===========================================================================


class TestSqliteStoreNewMethods:

    @pytest.mark.asyncio
    async def test_ack_returns_correct_shape(self, sqlite_mem: SqliteStore) -> None:
        result = await sqlite_mem.ack("agent-a", "msg-1", "received")
        assert result["message_id"] == "msg-1"
        assert result["status"] == "received"
        assert "acked_at" in result

    @pytest.mark.asyncio
    async def test_ack_with_reason(self, sqlite_mem: SqliteStore) -> None:
        result = await sqlite_mem.ack("agent-a", "msg-2", "nack", reason="bad data")
        assert result["status"] == "nack"

    @pytest.mark.asyncio
    async def test_heartbeat_returns_correct_shape(self, sqlite_mem: SqliteStore) -> None:
        result = await sqlite_mem.heartbeat("agent-a", "online")
        assert result["agent_id"] == "agent-a"
        assert result["status"] == "online"
        assert "expires_at" in result

    @pytest.mark.asyncio
    async def test_heartbeat_custom_ttl(self, sqlite_mem: SqliteStore) -> None:
        result = await sqlite_mem.heartbeat("agent-b", "busy", ttl=60)
        assert result["expires_at"] > result["recorded_at"] + 50

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, sqlite_mem: SqliteStore) -> None:
        result = await sqlite_mem.list_agents()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_agents_after_heartbeat(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.heartbeat("agent-c", "online")
        result = await sqlite_mem.list_agents()
        assert any(r["agent_id"] == "agent-c" for r in result)

    @pytest.mark.asyncio
    async def test_list_agents_status_filter(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.heartbeat("agent-d", "online")
        result = await sqlite_mem.list_agents(status_filter=["online"])
        assert any(r["agent_id"] == "agent-d" for r in result)

    @pytest.mark.asyncio
    async def test_list_agents_namespace_filter(self, sqlite_mem: SqliteStore) -> None:
        """list_agents namespace filter matches the namespace column in the liveness table.

        Schema v1.3 moved liveness from in-process dict to a SQLite table;
        namespace is settable via direct INSERT until a public namespace-set
        method lands.
        """
        import time as _time
        now = _time.time()
        conn = sqlite_mem._require_conn()
        await conn.execute(
            "INSERT INTO liveness(agent_id, status, recorded_at, expires_at, namespace) "
            "VALUES (?, ?, ?, ?, ?)",
            ("agent-e", "online", now, now + 30, "ns1"),
        )
        await conn.execute(
            "INSERT INTO liveness(agent_id, status, recorded_at, expires_at, namespace) "
            "VALUES (?, ?, ?, ?, ?)",
            ("agent-f", "online", now, now + 30, "other"),
        )
        await conn.commit()

        result = await sqlite_mem.list_agents(namespace="ns1")
        agent_ids = [r["agent_id"] for r in result]
        assert "agent-e" in agent_ids
        assert "agent-f" not in agent_ids

    @pytest.mark.asyncio
    async def test_replay_basic(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.subscribe("a", "replay-ch")
        await sqlite_mem.send("replay-ch", "a", {"n": 1})
        await sqlite_mem.send("replay-ch", "a", {"n": 2})
        msgs, has_more = await sqlite_mem.replay("replay-ch", since=0)
        assert len(msgs) == 2
        assert has_more is False

    @pytest.mark.asyncio
    async def test_replay_with_limit(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.subscribe("a", "lim-ch")
        for i in range(5):
            await sqlite_mem.send("lim-ch", "a", {"n": i})
        msgs, has_more = await sqlite_mem.replay("lim-ch", since=0, limit=3)
        assert len(msgs) == 3
        assert has_more is True

    @pytest.mark.asyncio
    async def test_replay_with_until(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.subscribe("a", "until-ch")
        for i in range(4):
            await sqlite_mem.send("until-ch", "a", {"n": i})
        msgs, _ = await sqlite_mem.replay("until-ch", since=1, until=2)
        seqs = [m["seq"] for m in msgs]
        assert all(1 <= s <= 2 for s in seqs)

    @pytest.mark.asyncio
    async def test_unsubscribe_clears_pending(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.subscribe("agent-u", "ch/*")
        await sqlite_mem.send("ch/1", "sender", {"k": "v"})
        removed, pending = await sqlite_mem.unsubscribe("agent-u", ["ch/*"])
        assert "ch/*" in removed
        assert pending == 1

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_pattern(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.subscribe("agent-v", "ch/*")
        removed, pending = await sqlite_mem.unsubscribe("agent-v", ["does-not-exist"])
        assert removed == []
        assert pending == 0

    @pytest.mark.asyncio
    async def test_group_create(self, sqlite_mem: SqliteStore) -> None:
        result = await sqlite_mem.group_create("creator-a", "mygroup")
        assert result["group_id"] == "group/mygroup"

    @pytest.mark.asyncio
    async def test_group_create_auto_id(self, sqlite_mem: SqliteStore) -> None:
        result = await sqlite_mem.group_create("creator-b")
        assert result["group_id"].startswith("group/grp-")

    @pytest.mark.asyncio
    async def test_group_invite(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.group_create("creator-c", "grp1")
        result = await sqlite_mem.group_invite("creator-c", "group/grp1", "invitee-x")
        assert result["invited"] is True

    @pytest.mark.asyncio
    async def test_group_invite_non_member_raises(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.group_create("creator-d", "grp2")
        with pytest.raises(ValueError, match="not an active member"):
            await sqlite_mem.group_invite("not-a-member", "group/grp2", "invitee-y")

    @pytest.mark.asyncio
    async def test_group_join(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.group_create("c", "grp3")
        await sqlite_mem.group_invite("c", "group/grp3", "joiner")
        result = await sqlite_mem.group_join("joiner", "group/grp3")
        assert result["joined"] is True

    @pytest.mark.asyncio
    async def test_group_leave(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.group_create("c", "grp4")
        result = await sqlite_mem.group_leave("c", "group/grp4")
        assert result["left"] is True

    @pytest.mark.asyncio
    async def test_group_list_members(self, sqlite_mem: SqliteStore) -> None:
        await sqlite_mem.group_create("c", "grp5")
        result = await sqlite_mem.group_list_members("c", "group/grp5")
        assert result["group_id"] == "group/grp5"
        assert isinstance(result["members"], list)

    @pytest.mark.asyncio
    async def test_require_conn_raises_when_not_initialized(self) -> None:
        """Line 148: _require_conn raises RuntimeError before initialize()."""
        store = SqliteStore(":memory:")
        with pytest.raises(RuntimeError, match="initialize"):
            store._require_conn()


# ===========================================================================
# filesystem/store.py — new BackingStore methods
# ===========================================================================


class TestFilesystemStoreNewMethods:

    @pytest.mark.asyncio
    async def test_ack_returns_correct_shape(self, fs: FilesystemStore) -> None:
        result = await fs.ack("agent-a", "msg-1", "received")
        assert result["message_id"] == "msg-1"
        assert result["status"] == "received"
        assert "acked_at" in result

    @pytest.mark.asyncio
    async def test_ack_with_reason(self, fs: FilesystemStore) -> None:
        result = await fs.ack("agent-a", "msg-2", "nack", reason="bad")
        assert result["status"] == "nack"

    @pytest.mark.asyncio
    async def test_heartbeat_returns_correct_shape(self, fs: FilesystemStore) -> None:
        result = await fs.heartbeat("agent-a", "online")
        assert result["agent_id"] == "agent-a"
        assert result["status"] == "online"

    @pytest.mark.asyncio
    async def test_heartbeat_custom_ttl(self, fs: FilesystemStore) -> None:
        result = await fs.heartbeat("agent-b", "busy", ttl=60)
        assert result["expires_at"] > result["recorded_at"] + 50

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, fs: FilesystemStore) -> None:
        result = await fs.list_agents()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_agents_after_heartbeat(self, fs: FilesystemStore) -> None:
        await fs.heartbeat("agent-c", "online")
        result = await fs.list_agents()
        assert any(r["agent_id"] == "agent-c" for r in result)

    @pytest.mark.asyncio
    async def test_list_agents_status_filter(self, fs: FilesystemStore) -> None:
        await fs.heartbeat("agent-d", "online")
        result = await fs.list_agents(status_filter=["online"])
        assert any(r["agent_id"] == "agent-d" for r in result)

    @pytest.mark.asyncio
    async def test_list_agents_namespace_filter(self, fs: FilesystemStore) -> None:
        """list_agents namespace filter matches the namespace field in the liveness record."""
        import time as _time
        # Trigger _liveness initialization via heartbeat, then overwrite with namespace records.
        await fs.heartbeat("_init_trigger", "online")
        now = _time.time()
        fs._liveness["agent-e"] = {  # type: ignore[attr-defined]
            "status": "online",
            "recorded_at": now,
            "expires_at": now + 30,
            "namespace": "ns1",
        }
        fs._liveness["agent-f"] = {  # type: ignore[attr-defined]
            "status": "online",
            "recorded_at": now,
            "expires_at": now + 30,
            "namespace": "other",
        }
        result = await fs.list_agents(namespace="ns1")
        agent_ids = [r["agent_id"] for r in result]
        assert "agent-e" in agent_ids
        assert "agent-f" not in agent_ids

    @pytest.mark.asyncio
    async def test_replay_basic(self, fs: FilesystemStore) -> None:
        await fs.subscribe("a", "replay-ch")
        await fs.send("replay-ch", "a", {"n": 1})
        await fs.send("replay-ch", "a", {"n": 2})
        msgs, has_more = await fs.replay("replay-ch", since=0)
        assert len(msgs) == 2
        assert has_more is False

    @pytest.mark.asyncio
    async def test_replay_with_limit(self, fs: FilesystemStore) -> None:
        await fs.subscribe("a", "lim-ch")
        for i in range(5):
            await fs.send("lim-ch", "a", {"n": i})
        msgs, has_more = await fs.replay("lim-ch", since=0, limit=3)
        assert len(msgs) == 3
        assert has_more is True

    @pytest.mark.asyncio
    async def test_replay_with_until(self, fs: FilesystemStore) -> None:
        await fs.subscribe("a", "until-ch")
        for i in range(4):
            await fs.send("until-ch", "a", {"n": i})
        msgs, _ = await fs.replay("until-ch", since=2, until=3)
        seqs = [int(str(m.get("seq", 0))) for m in msgs]
        assert all(2 <= s <= 3 for s in seqs)

    @pytest.mark.asyncio
    async def test_group_create(self, fs: FilesystemStore) -> None:
        result = await fs.group_create("creator-a", "mygroup")
        assert result["group_id"] == "group/mygroup"

    @pytest.mark.asyncio
    async def test_group_create_auto_id(self, fs: FilesystemStore) -> None:
        result = await fs.group_create("creator-b")
        assert result["group_id"].startswith("group/grp-")

    @pytest.mark.asyncio
    async def test_group_invite(self, fs: FilesystemStore) -> None:
        await fs.group_create("creator-c", "grp1")
        result = await fs.group_invite("creator-c", "group/grp1", "invitee-x")
        assert result["invited"] is True

    @pytest.mark.asyncio
    async def test_group_invite_non_member_raises(self, fs: FilesystemStore) -> None:
        await fs.group_create("creator-d", "grp2")
        with pytest.raises(ValueError, match="not an active member"):
            await fs.group_invite("not-a-member", "group/grp2", "invitee-y")

    @pytest.mark.asyncio
    async def test_group_join(self, fs: FilesystemStore) -> None:
        await fs.group_create("c", "grp3")
        await fs.group_invite("c", "group/grp3", "joiner")
        result = await fs.group_join("joiner", "group/grp3")
        assert result["joined"] is True

    @pytest.mark.asyncio
    async def test_group_leave(self, fs: FilesystemStore) -> None:
        await fs.group_create("c", "grp4")
        result = await fs.group_leave("c", "group/grp4")
        assert result["left"] is True

    @pytest.mark.asyncio
    async def test_group_list_members(self, fs: FilesystemStore) -> None:
        await fs.group_create("c", "grp5")
        result = await fs.group_list_members("c", "group/grp5")
        assert result["group_id"] == "group/grp5"
        assert isinstance(result["members"], list)

    @pytest.mark.asyncio
    async def test_unsubscribe_clears_pending(self, fs: FilesystemStore) -> None:
        await fs.subscribe("agent-u", "ch/*")
        await fs.send("ch/1", "sender", {"k": "v"})
        removed, pending = await fs.unsubscribe("agent-u", ["ch/*"])
        assert "ch/*" in removed
        assert pending == 1

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_pattern(self, fs: FilesystemStore) -> None:
        await fs.subscribe("agent-v", "ch/*")
        removed, pending = await fs.unsubscribe("agent-v", ["does-not-exist"])
        assert removed == []
        assert pending == 0
