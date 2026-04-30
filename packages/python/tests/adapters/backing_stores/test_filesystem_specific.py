# SPDX-License-Identifier: Apache-2.0
"""Filesystem-specific BackingStore adapter tests.

Covers behaviours unique to the FilesystemStore that are not part of the
port-contract parametrised suite:

- fswatch behaviour: new files appear and are picked up by watch().
- Directory layout matches the documented structure.
- Channel names with special characters (``:``) are encoded correctly.
- Atomic write prevents partial reads (temp-file + rename).
- Collision resistance: concurrent sends with the same timestamp still
  produce unique filenames (UUID suffix).
- Delivered-set file is written atomically; concurrent recv calls for
  different agents do not corrupt each other's delivered files.
- Subscriptions file survives reopen (persistence guarantee).
- Context-manager protocol works correctly.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import time

import pytest
import pytest_asyncio

from sox_protocol.adapters.backing_stores.filesystem.store import (
    FilesystemStore,
    _decode_channel,
    _encode_channel,
)


@pytest_asyncio.fixture
async def fs_store(tmp_path: pathlib.Path) -> FilesystemStore:
    """Return an initialised FilesystemStore in a temp directory."""
    store = FilesystemStore(root=tmp_path / "fsstore")
    await store.initialize()
    return store


# ---------------------------------------------------------------------------
# Channel encoding
# ---------------------------------------------------------------------------


class TestChannelEncoding:
    """Directory names are filesystem-safe encodings of channel names."""

    def test_colon_encoded(self) -> None:
        """``:`` in channel name is encoded to ``%3A``."""
        assert _encode_channel("ticket:ENGI-0042") == "ticket%3AENGI-0042"

    def test_round_trip(self) -> None:
        """encode → decode is the identity for typical channel names."""
        names = [
            "ticket:ENGI-0042",
            "project:foo",
            "broadcast:status",
            "simple",
            "a:b:c",
        ]
        for name in names:
            assert _decode_channel(_encode_channel(name)) == name

    def test_percent_sign_encoded(self) -> None:
        """A literal ``%`` in a channel name is encoded to prevent ambiguity."""
        encoded = _encode_channel("ch%weird")
        assert encoded == "ch%25weird"
        assert _decode_channel(encoded) == "ch%weird"


# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------


class TestDirectoryLayout:
    """The store creates the expected directory hierarchy."""

    async def test_root_directories_created(self, tmp_path: pathlib.Path) -> None:
        """initialize() creates channels/ and subscriptions/ under root."""
        root = tmp_path / "layout_test"
        store = FilesystemStore(root=root)
        await store.initialize()
        assert (root / "channels").is_dir()
        assert (root / "subscriptions").is_dir()

    async def test_message_file_created_in_channel_dir(
        self, fs_store: FilesystemStore
    ) -> None:
        """send() creates a .json file inside channels/<enc-name>/messages/."""
        await fs_store.send("ticket:X", "sender", {"data": 1})
        channel_dir = fs_store._messages_dir("ticket:X")
        json_files = list(channel_dir.glob("*.json"))
        assert len(json_files) == 1

    async def test_subscription_file_created(self, fs_store: FilesystemStore) -> None:
        """subscribe() writes a .json file to subscriptions/<agent_id>.json."""
        await fs_store.subscribe("agent-sub", "ch:*")
        sub_file = fs_store._subscriptions_file("agent-sub")
        assert sub_file.exists()
        patterns = json.loads(sub_file.read_text())
        assert "ch:*" in patterns

    async def test_delivered_file_created_after_recv(
        self, fs_store: FilesystemStore
    ) -> None:
        """recv() creates a delivered/<agent_id>.json file for the channel."""
        await fs_store.subscribe("agent-d", "ch:delivered")
        await fs_store.send("ch:delivered", "s", {"x": 1})
        await fs_store.recv("agent-d")
        delivered_file = fs_store._delivered_file("ch:delivered", "agent-d")
        assert delivered_file.exists()
        delivered = json.loads(delivered_file.read_text())
        assert len(delivered) == 1


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    """Message files are written atomically."""

    async def test_no_tmp_files_left_after_send(self, fs_store: FilesystemStore) -> None:
        """No ``.tmp`` files remain after a successful send."""
        await fs_store.send("ch:atomic", "s", {"ok": True})
        msg_dir = fs_store._messages_dir("ch:atomic")
        tmp_files = list(msg_dir.glob("*.tmp"))
        assert tmp_files == [], f"Unexpected .tmp files: {tmp_files}"

    async def test_message_file_is_complete_json(
        self, fs_store: FilesystemStore
    ) -> None:
        """The written file is valid, complete JSON."""
        await fs_store.send("ch:json", "sender", {"key": "value"})
        msg_dir = fs_store._messages_dir("ch:json")
        files = list(msg_dir.glob("*.json"))
        assert len(files) == 1
        content = json.loads(files[0].read_text())
        assert content["channel"] == "ch:json"
        assert content["sender"] == "sender"
        assert content["body"] == {"key": "value"}


# ---------------------------------------------------------------------------
# Filename collision resistance
# ---------------------------------------------------------------------------


class TestFilenameCollisionResistance:
    """Concurrent sends produce unique filenames even at the same timestamp."""

    async def test_concurrent_sends_unique_filenames(
        self, fs_store: FilesystemStore
    ) -> None:
        """20 concurrent sends to the same channel produce 20 unique files."""
        n = 20
        await asyncio.gather(
            *[fs_store.send("ch:collision", "s", {"i": i}) for i in range(n)]
        )
        msg_dir = fs_store._messages_dir("ch:collision")
        files = list(msg_dir.glob("*.json"))
        assert len(files) == n, f"Expected {n} files, got {len(files)}"
        # All filenames are unique (UUIDs guarantee this).
        names = {f.name for f in files}
        assert len(names) == n


# ---------------------------------------------------------------------------
# fswatch / poll behaviour
# ---------------------------------------------------------------------------


class TestFsWatch:
    """watch() detects new files created by send()."""

    async def test_watch_detects_new_message_file(
        self, fs_store: FilesystemStore
    ) -> None:
        """watch() yields a message after its file appears on disk."""
        await fs_store.subscribe("a", "ch:fswatch")
        collected: list[dict[str, object]] = []

        async def watcher() -> None:
            async for msg in fs_store.watch("a"):
                collected.append(msg)
                if len(collected) >= 1:
                    return

        task = asyncio.create_task(watcher())
        await asyncio.sleep(0.1)
        await fs_store.send("ch:fswatch", "s", {"detected": True})

        try:
            await asyncio.wait_for(task, timeout=3.0)
        except asyncio.TimeoutError:
            task.cancel()

        assert len(collected) == 1
        assert collected[0]["body"] == {"detected": True}

    async def test_watch_skips_already_delivered_messages(
        self, fs_store: FilesystemStore
    ) -> None:
        """watch() does not yield messages already drained by recv()."""
        await fs_store.subscribe("a", "ch:fswatch-skip")
        await fs_store.send("ch:fswatch-skip", "s", {"pre": True})
        await fs_store.recv("a")  # drain via recv

        # Now send a new message.
        await fs_store.send("ch:fswatch-skip", "s", {"post": True})

        collected: list[dict[str, object]] = []

        async def watcher() -> None:
            async for msg in fs_store.watch("a"):
                collected.append(msg)
                if len(collected) >= 1:
                    return

        try:
            await asyncio.wait_for(watcher(), timeout=3.0)
        except asyncio.TimeoutError:
            pass

        assert len(collected) == 1
        assert collected[0]["body"] == {"post": True}

    async def test_watch_cancellation_clean(self, fs_store: FilesystemStore) -> None:
        """Cancelling watch() raises CancelledError without resource leaks."""
        await fs_store.subscribe("a", "ch:cancel")

        async def watcher() -> None:
            async for _ in fs_store.watch("a"):
                pass

        task = asyncio.create_task(watcher())
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# Delivered-file integrity
# ---------------------------------------------------------------------------


class TestDeliveredFileIntegrity:
    """Concurrent recv calls for different agents do not corrupt delivered files."""

    async def test_concurrent_recv_different_agents(
        self, fs_store: FilesystemStore
    ) -> None:
        """Two agents recv concurrently; each gets its own independent delivery."""
        await fs_store.subscribe("agent-x", "ch:dfi")
        await fs_store.subscribe("agent-y", "ch:dfi")
        for i in range(5):
            await fs_store.send("ch:dfi", "s", {"i": i})

        msgs_x, msgs_y = await asyncio.gather(
            fs_store.recv("agent-x"),
            fs_store.recv("agent-y"),
        )
        assert len(msgs_x) == 5
        assert len(msgs_y) == 5

        # Verify delivered files are independent.
        del_x = fs_store._get_delivered_set("ch:dfi", "agent-x")
        del_y = fs_store._get_delivered_set("ch:dfi", "agent-y")
        assert len(del_x) == 5
        assert len(del_y) == 5

    async def test_recv_not_redelivered_after_reopen(
        self, tmp_path: pathlib.Path
    ) -> None:
        """After reopening the store, drained messages are not re-delivered."""
        root = tmp_path / "reopen_test"

        store1 = FilesystemStore(root=root)
        await store1.initialize()
        await store1.subscribe("a", "ch:reopen")
        await store1.send("ch:reopen", "s", {"msg": "first"})
        first = await store1.recv("a")
        assert len(first) == 1

        # Open a fresh instance pointing at the same root.
        store2 = FilesystemStore(root=root)
        await store2.initialize()
        second = await store2.recv("a")
        assert second == [], "Message re-delivered after reopen!"


# ---------------------------------------------------------------------------
# Subscription persistence
# ---------------------------------------------------------------------------


class TestSubscriptionPersistence:
    """Subscriptions survive store reopen."""

    async def test_subscriptions_persist_across_reopen(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Subscriptions written in one instance are honoured after reopen."""
        root = tmp_path / "sub_persist"

        store1 = FilesystemStore(root=root)
        await store1.initialize()
        await store1.subscribe("a", "ch:persist-*")

        # Reopen.
        store2 = FilesystemStore(root=root)
        await store2.initialize()
        await store2.send("ch:persist-001", "s", {"ok": True})
        msgs = await store2.recv("a")
        assert len(msgs) == 1


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    """FilesystemStore supports the async context-manager protocol."""

    async def test_async_context_manager(self, tmp_path: pathlib.Path) -> None:
        """async with FilesystemStore(...) as s: should initialize cleanly."""
        root = tmp_path / "ctx_test"
        async with FilesystemStore(root=root) as s:
            msg_id, _ = await s.send("ch:ctx", "s", {"x": 1})
            assert isinstance(msg_id, str)
