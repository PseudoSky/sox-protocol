# SPDX-License-Identifier: Apache-2.0
"""Additional edge-case tests for remaining coverage gaps in filesystem/store.py
and sqlite/store.py.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from unittest.mock import patch

import pytest

from sox_protocol.adapters.backing_stores.filesystem.store import (
    FilesystemStore,
    _atomic_write,
)
from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore

# ===========================================================================
# filesystem/store.py — _atomic_write exception cleanup (lines 79-84)
# ===========================================================================


class TestAtomicWriteException:

    def test_atomic_write_exception_unlinks_tmp_and_reraises(self, tmp_path: Path) -> None:
        """Lines 79-84: exception during os.replace cleans up temp file and re-raises."""
        dest = tmp_path / "output.json"

        with patch("os.replace", side_effect=OSError("replace failed")):
            with pytest.raises(OSError, match="replace failed"):
                _atomic_write(dest, '{"key": "value"}')

        # No temp files should remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_atomic_write_exception_unlink_fails_silently(self, tmp_path: Path) -> None:
        """Lines 82-83: OSError from os.unlink inside except is suppressed."""
        dest = tmp_path / "output.json"

        with patch("os.replace", side_effect=OSError("replace failed")):
            with patch("os.unlink", side_effect=OSError("unlink failed")):
                with pytest.raises(OSError, match="replace failed"):
                    _atomic_write(dest, '{"key": "value"}')


# ===========================================================================
# filesystem/store.py — _list_message_files empty dir (line 173)
# ===========================================================================


class TestListMessageFilesEmptyDir:

    @pytest.mark.asyncio
    async def test_list_message_files_no_dir_returns_empty(self, tmp_path: Path) -> None:
        """Line 173: _list_message_files returns [] when messages dir doesn't exist."""
        store = FilesystemStore(root=tmp_path)
        await store.initialize()
        result = store._list_message_files("nonexistent-channel")
        assert result == []


# ===========================================================================
# filesystem/store.py — _known_channels when channels dir missing (line 198)
# ===========================================================================


class TestKnownChannelsNoDir:

    @pytest.mark.asyncio
    async def test_known_channels_no_dir_returns_empty(self, tmp_path: Path) -> None:
        """Line 198: _known_channels returns [] when channels dir doesn't exist."""
        store = FilesystemStore(root=tmp_path)
        # Do NOT initialize — channels dir won't exist
        result = store._known_channels()
        assert result == []


# ===========================================================================
# filesystem/store.py — recv with explicit channels list (line 273)
# ===========================================================================


class TestFilesystemRecvExplicitChannels:

    @pytest.mark.asyncio
    async def test_recv_with_explicit_channels_list(self, tmp_path: Path) -> None:
        """Line 273: recv with explicit channels= list path."""
        store = FilesystemStore(root=tmp_path)
        await store.initialize()

        # Send messages to two channels
        await store.send("ch/1", "sender", {"n": 1})
        await store.send("ch/2", "sender", {"n": 2})

        # Subscribe to ch/* so agent is known
        await store.subscribe("agent-a", "ch/*")

        # Recv with explicit channel filter — covers the `target_channels = list(channels)` branch
        msgs = await store.recv("agent-a", channels=["ch/1"])
        assert len(msgs) == 1
        assert msgs[0]["channel"] == "ch/1"


# ===========================================================================
# filesystem/store.py — recv OSError/JSONDecodeError continue (lines 290-291)
# ===========================================================================


class TestFilesystemRecvCorruptMessage:

    @pytest.mark.asyncio
    async def test_recv_skips_corrupt_message_file(self, tmp_path: Path) -> None:
        """Lines 290-291: OSError/JSONDecodeError during recv causes continue."""
        store = FilesystemStore(root=tmp_path)
        await store.initialize()

        await store.subscribe("agent-b", "ch/*")
        await store.send("ch/1", "sender", {"n": 1})

        # Write a corrupt message file to the channel
        msgs_dir = store._messages_dir("ch/1")
        corrupt_file = msgs_dir / "0000000000.000000_corrupt.json"
        corrupt_file.write_text("not valid json{{{", encoding="utf-8")

        # recv should skip the corrupt file and return the valid one
        msgs = await store.recv("agent-b", channels=["ch/1"])
        assert len(msgs) == 1
        assert msgs[0]["channel"] == "ch/1"


# ===========================================================================
# filesystem/store.py — list_channels OSError/JSONDecodeError (lines 350-351)
# ===========================================================================


class TestFilesystemListChannelsCorrupt:

    @pytest.mark.asyncio
    async def test_list_channels_skips_corrupt_message_file(self, tmp_path: Path) -> None:
        """Lines 350-351: OSError/JSONDecodeError in _has_recent_message causes continue."""
        store = FilesystemStore(root=tmp_path)
        await store.initialize()

        await store.subscribe("agent-c", "ch/*")
        await store.send("ch/1", "sender", {"n": 1})

        # Write a corrupt message file
        msgs_dir = store._messages_dir("ch/1")
        corrupt_file = msgs_dir / "0000000000.000000_corrupt.json"
        corrupt_file.write_text("{corrupt json", encoding="utf-8")

        # list_channels should not crash
        result = await store.list_channels()
        assert isinstance(result, list)


# ===========================================================================
# filesystem/store.py — watch skips non-matching channel (line 399)
# ===========================================================================


class TestFilesystemWatchSkipsNonMatching:

    @pytest.mark.asyncio
    async def test_watch_skips_channel_not_matching_pattern(self, tmp_path: Path) -> None:
        """Line 399: watch skips channels not matching agent's patterns."""
        store = FilesystemStore(root=tmp_path, watch_poll_interval=0.02)
        await store.initialize()

        # Agent only subscribes to ch/*
        await store.subscribe("agent-d", "ch/*")

        # Send to a different channel (not matching ch/*)
        await store.send("other/1", "sender", {"n": 99})

        # Send to matching channel
        await store.send("ch/1", "sender", {"n": 1})

        collected = []
        async def _collect():
            async for msg in store.watch("agent-d"):
                collected.append(msg)
                break

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_collect(), timeout=0.5)

        # Should only see ch/1, not other/1
        channels = [m["channel"] for m in collected]
        assert "other/1" not in channels


# ===========================================================================
# filesystem/store.py — watch fname in delivered (lines 406-407)
# ===========================================================================


class TestFilesystemWatchAlreadyDelivered:

    @pytest.mark.asyncio
    async def test_watch_skips_already_delivered_message(self, tmp_path: Path) -> None:
        """Lines 406-407: watch skips filenames in delivered set."""
        store = FilesystemStore(root=tmp_path, watch_poll_interval=0.02)
        await store.initialize()

        await store.subscribe("agent-e", "ch/*")

        # Send a message and recv it (mark as delivered)
        await store.send("ch/1", "sender", {"n": 1})
        msgs = await store.recv("agent-e", channels=["ch/1"])
        assert len(msgs) == 1

        # Now send another message to trigger a watch iteration
        await store.send("ch/1", "sender", {"n": 2})

        collected = []
        async def _collect():
            async for msg in store.watch("agent-e"):
                collected.append(msg)
                if len(collected) >= 1:
                    break

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_collect(), timeout=0.5)

        # Should only get the second message (first was in delivered)
        assert any(m.get("body", {}).get("n") == 2 for m in collected)


# ===========================================================================
# filesystem/store.py — watch OSError on read (lines 412-413)
# ===========================================================================


class TestFilesystemWatchCorruptFile:

    @pytest.mark.asyncio
    async def test_watch_skips_corrupt_message_file(self, tmp_path: Path) -> None:
        """Lines 412-413: watch skips file that raises OSError/JSONDecodeError on read."""
        store = FilesystemStore(root=tmp_path, watch_poll_interval=0.02)
        await store.initialize()

        await store.subscribe("agent-f", "ch/*")

        # Place a corrupt file in the messages dir
        msgs_dir = store._messages_dir("ch/1")
        msgs_dir.mkdir(parents=True, exist_ok=True)
        corrupt_file = msgs_dir / "0000000000.000000_corrupt.json"
        corrupt_file.write_text("{bad json{{", encoding="utf-8")

        # Place a valid file too
        await store.send("ch/1", "sender", {"n": 1})

        collected = []
        async def _collect():
            async for msg in store.watch("agent-f"):
                collected.append(msg)
                break

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_collect(), timeout=0.5)

        # Should get the valid message despite the corrupt file
        valid_msgs = [m for m in collected if isinstance(m.get("body"), dict)]
        assert len(valid_msgs) >= 1


# ===========================================================================
# filesystem/store.py — unsubscribe skips non-matching channels (line 452)
# ===========================================================================


class TestFilesystemUnsubscribeSkipsChannels:

    @pytest.mark.asyncio
    async def test_unsubscribe_skips_channels_not_matching_removed_pattern(
        self, tmp_path: Path
    ) -> None:
        """Line 452: unsubscribe skips channels that don't match any removed pattern."""
        store = FilesystemStore(root=tmp_path)
        await store.initialize()

        await store.subscribe("agent-g", "ch/*")
        await store.subscribe("agent-g", "other/*")

        # Send to both channels
        await store.send("ch/1", "sender", {"n": 1})
        await store.send("other/1", "sender", {"n": 2})

        # Unsubscribe from ch/* only
        removed, pending = await store.unsubscribe("agent-g", ["ch/*"])
        assert "ch/*" in removed
        assert pending == 1  # only ch/1 should be marked


# ===========================================================================
# filesystem/store.py — list_agents status_filter continue (line 517)
# ===========================================================================


class TestFilesystemListAgentsFilter:

    @pytest.mark.asyncio
    async def test_list_agents_status_filter_excludes_non_matching(
        self, tmp_path: Path
    ) -> None:
        """Line 517: list_agents skips agents not matching status_filter."""
        store = FilesystemStore(root=tmp_path)
        await store.initialize()

        import time
        now = time.time()
        store._FilesystemStore__init_extras()  # type: ignore[attr-defined]
        store._liveness["busy-agent"] = {
            "status": "busy",
            "recorded_at": now,
            "expires_at": now + 30,
        }
        store._liveness["online-agent"] = {
            "status": "online",
            "recorded_at": now,
            "expires_at": now + 30,
        }

        result = await store.list_agents(status_filter=["online"])
        agent_ids = [r["agent_id"] for r in result]
        assert "online-agent" in agent_ids
        assert "busy-agent" not in agent_ids


# ===========================================================================
# filesystem/store.py — replay OSError (lines 535-536)
# ===========================================================================


class TestFilesystemReplayCorrupt:

    @pytest.mark.asyncio
    async def test_replay_skips_corrupt_message_file(self, tmp_path: Path) -> None:
        """Lines 535-536: replay skips OSError/JSONDecodeError files."""
        store = FilesystemStore(root=tmp_path)
        await store.initialize()

        await store.send("replay-ch", "sender", {"n": 1})

        # Write a corrupt file to the channel messages dir
        msgs_dir = store._messages_dir("replay-ch")
        corrupt_file = msgs_dir / "0000000000.000000_corrupt.json"
        corrupt_file.write_text("{corrupt{{", encoding="utf-8")

        msgs, _ = await store.replay("replay-ch", since=0)
        # Should only get the valid message
        valid_msgs = [m for m in msgs if isinstance(m.get("body"), dict)]
        assert len(valid_msgs) == 1


# ===========================================================================
# sqlite/store.py — recv with explicit channels, channel NOT in list (lines 261-262)
# ===========================================================================


class TestSqliteRecvExplicitChannels:

    @pytest.mark.asyncio
    async def test_recv_explicit_channels_filters_out_others(self) -> None:
        """Lines 236, 261-262: recv with explicit channels= filters messages by channel."""
        store = SqliteStore(":memory:")
        async with store:
            await store.subscribe("agent-a", "ch/*")
            await store.send("ch/1", "sender", {"n": 1})
            await store.send("ch/2", "sender", {"n": 2})

            # Recv with explicit channel — covers the `if ch not in channels: continue` branch
            msgs = await store.recv("agent-a", channels=["ch/1"])
            assert len(msgs) == 1
            assert msgs[0]["channel"] == "ch/1"

    @pytest.mark.asyncio
    async def test_recv_explicit_channels_empty_patterns_still_works(self) -> None:
        """Line 236: recv with explicit channels skips pattern lookup."""
        store = SqliteStore(":memory:")
        async with store:
            # No subscriptions — but recv with explicit channels should still work
            await store.send("ch/1", "sender", {"n": 1})
            msgs = await store.recv("agent-b", channels=["ch/1"])
            assert len(msgs) == 1


# ===========================================================================
# sqlite/store.py — _fetch_new_for_agent skips delivered and non-matching (442, 444)
# ===========================================================================


class TestSqliteFetchNewForAgent:

    @pytest.mark.asyncio
    async def test_fetch_new_skips_already_delivered(self) -> None:
        """Line 442: _fetch_new_for_agent skips messages already in delivered_to."""
        store = SqliteStore(":memory:")
        async with store:
            await store.subscribe("agent-a", "ch/*")
            mid, *_ = await store.send("ch/1", "sender", {"n": 1})

            # Drain via recv (marks delivered)
            msgs = await store.recv("agent-a", channels=["ch/1"])
            assert len(msgs) == 1

            # Now _fetch_new_for_agent should find nothing since message is delivered
            result = await store._fetch_new_for_agent("agent-a", 0)
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_new_skips_non_matching_channel(self) -> None:
        """Line 444: _fetch_new_for_agent skips messages on non-matching channels."""
        store = SqliteStore(":memory:")
        async with store:
            await store.subscribe("agent-a", "ch/*")
            # Send to a channel not matching agent-a's pattern
            await store.send("other/1", "sender", {"n": 1})

            result = await store._fetch_new_for_agent("agent-a", 0)
            assert result == []


# ===========================================================================
# sqlite/store.py — unsubscribe skips already-delivered messages (line 484)
# ===========================================================================


class TestSqliteUnsubscribeSkipsDelivered:

    @pytest.mark.asyncio
    async def test_unsubscribe_skips_already_delivered_messages(self) -> None:
        """Line 484: unsubscribe skips messages already in delivered_to for the agent."""
        store = SqliteStore(":memory:")
        async with store:
            await store.subscribe("agent-a", "ch/*")
            await store.send("ch/1", "sender", {"n": 1})

            # First drain the message (mark as delivered)
            msgs = await store.recv("agent-a", channels=["ch/1"])
            assert len(msgs) == 1

            # Now unsubscribe — should find 0 pending_cleared (already delivered)
            removed, pending_cleared = await store.unsubscribe("agent-a", ["ch/*"])
            assert "ch/*" in removed
            assert pending_cleared == 0


# ===========================================================================
# sqlite/store.py — list_agents status_filter continue (line 545)
# ===========================================================================


class TestSqliteListAgentsFilter:

    @pytest.mark.asyncio
    async def test_list_agents_status_filter_excludes_non_matching(self) -> None:
        """Line 545: list_agents skips agents not matching status_filter."""
        store = SqliteStore(":memory:")
        async with store:
            await store.heartbeat("busy-agent", "busy")
            await store.heartbeat("online-agent", "online")

            result = await store.list_agents(status_filter=["online"])
            agent_ids = [r["agent_id"] for r in result]
            assert "online-agent" in agent_ids
            assert "busy-agent" not in agent_ids
