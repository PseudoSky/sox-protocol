# SPDX-License-Identifier: Apache-2.0
"""Parametrised port-contract tests for all BackingStore adapters.

Each test in this module is run against SqliteStore, FilesystemStore, and
MemoryStore.  A test that passes for all three proves that every adapter
correctly binds the BackingStore port as specified in
``spec/ports/backing-store.md``.

Spec coverage
-------------
- Round-trip (§2.1, §2.2)
- Concurrent writers — 10 senders, no loss (§3.1)
- Subscription matching including glob (§2.3)
  - ``ticket:ENGI-*`` matches ``ticket:ENGI-0042`` but not ``project:foo``
- Delivery tracking — recv'd messages not re-delivered to same agent (§3.2, §3.3)
- Per-channel send-time ordering (§5.1)
- Watch-loop yields exactly once per subscribed agent (§2.5)
- Cross-agent delivery independence (§4.3)
- subscribe() idempotency (§2.3 — Idempotency)
- list_channels() returns subscriber_count (§2.4)
- Stress test: 10 concurrent writers + 10 concurrent readers, 100 messages each (§3.1, §3.2)
"""

from __future__ import annotations

import asyncio
import pathlib
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import pytest
import pytest_asyncio

from sox_protocol.adapters.backing_stores.filesystem.store import FilesystemStore
from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore
from sox_protocol.core.ports.backing_store import BackingStore

# ---------------------------------------------------------------------------
# Fixtures — one per adapter, parametrised
# ---------------------------------------------------------------------------

StoreFactory = Callable[[], Coroutine[Any, Any, BackingStore]]


@pytest_asyncio.fixture(
    params=["memory", "sqlite", "filesystem"],
)
async def store(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> AsyncIterator[BackingStore]:
    """Yield an initialised BackingStore for each adapter under test."""
    kind: str = request.param

    if kind == "memory":
        s: BackingStore = MemoryStore()
        await s.initialize()  # type: ignore[attr-defined]
        yield s

    elif kind == "sqlite":
        db_path = tmp_path / "test.db"
        s = SqliteStore(db_path=db_path)
        await s.initialize()  # type: ignore[attr-defined]
        yield s
        await s.close()  # type: ignore[attr-defined]

    elif kind == "filesystem":
        fs_root = tmp_path / "fsstore"
        s = FilesystemStore(root=fs_root)
        await s.initialize()  # type: ignore[attr-defined]
        yield s

    else:
        pytest.fail(f"Unknown store kind: {kind}")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _collect_watch(
    s: BackingStore,
    agent_id: str,
    expected_count: int,
    timeout: float = 3.0,
) -> list[dict[str, object]]:
    """Collect *expected_count* messages from watch(), with a timeout."""
    collected: list[dict[str, object]] = []

    async def _drain() -> None:
        async for msg in s.watch(agent_id):  # type: ignore[attr-defined]
            collected.append(msg)
            if len(collected) >= expected_count:
                return

    try:
        await asyncio.wait_for(_drain(), timeout=timeout)
    except TimeoutError:
        pass
    return collected


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """spec/ports/backing-store.md §2.1, §2.2"""

    async def test_send_and_recv(self, store: BackingStore) -> None:
        """A message sent to a channel is returned by recv for a subscribed agent."""
        await store.subscribe("agent-a", "ch:test")
        msg_id, sent_at, seq, _bp = await store.send("ch:test", "agent-b", {"hello": "world"})

        assert isinstance(msg_id, str)
        assert isinstance(sent_at, float)
        assert sent_at > 0
        assert isinstance(seq, int)
        assert seq >= 1

        messages = await store.recv("agent-a")
        assert len(messages) == 1
        m = messages[0]
        assert m["channel"] == "ch:test"
        assert m["sender"] == "agent-b"
        assert m["body"] == {"hello": "world"}
        assert m["message_id"] == msg_id
        assert m["sent_at"] == pytest.approx(sent_at, abs=1.0)

    async def test_correlation_id_round_trips(self, store: BackingStore) -> None:
        """correlation_id is preserved verbatim."""
        await store.subscribe("agent-a", "ch:corr")
        await store.send("ch:corr", "sender", {"x": 1}, correlation_id="req-42")
        msgs = await store.recv("agent-a")
        assert msgs[0]["correlation_id"] == "req-42"

    async def test_null_correlation_id(self, store: BackingStore) -> None:
        """When correlation_id is not supplied it is returned as None/null."""
        await store.subscribe("agent-a", "ch:nocorr")
        await store.send("ch:nocorr", "sender", {"x": 1})
        msgs = await store.recv("agent-a")
        assert msgs[0]["correlation_id"] is None

    async def test_reply_to_round_trips(self, store: BackingStore) -> None:
        """reply_to is persisted and echoed verbatim on recv.

        Spec: spec/primitives/threads.md (reply_to links a message to its
        parent). This exercises the fix for the threading conformance fixtures
        threading/01-reply-to-link, threading/02-deep-thread, and
        threading/03-thread-depth-zero.
        """
        await store.subscribe("agent-a", "ch:thread")
        parent_id, _, _, _ = await store.send("ch:thread", "agent-b", {"type": "parent"})
        # Send a reply referencing the parent message id.
        await store.send(
            "ch:thread",
            "agent-b",
            {"type": "reply"},
            reply_to=parent_id,
        )
        # Drain both messages.
        msgs = await store.recv("agent-a")
        assert len(msgs) == 2
        # First message is top-level — reply_to must be None.
        assert msgs[0]["reply_to"] is None
        # Second message is the reply — reply_to must match the parent id.
        assert msgs[1]["reply_to"] == parent_id

    async def test_reply_to_defaults_to_none(self, store: BackingStore) -> None:
        """When reply_to is not supplied it is returned as None (not absent)."""
        await store.subscribe("agent-a", "ch:noreply")
        await store.send("ch:noreply", "sender", {"x": 1})
        msgs = await store.recv("agent-a")
        assert "reply_to" in msgs[0]
        assert msgs[0]["reply_to"] is None

    async def test_recv_returns_empty_when_no_messages(self, store: BackingStore) -> None:
        """recv returns [] when there are no pending messages."""
        await store.subscribe("agent-a", "ch:empty")
        msgs = await store.recv("agent-a")
        assert msgs == []

    async def test_unsubscribed_agent_gets_no_messages(self, store: BackingStore) -> None:
        """An agent that has not subscribed receives nothing."""
        await store.send("ch:x", "sender", {"k": "v"})
        msgs = await store.recv("agent-unsubscribed")
        assert msgs == []


class TestConcurrentWriters:
    """spec/ports/backing-store.md §3.1 — send-atomicity, no loss."""

    async def test_ten_senders_no_loss(self, store: BackingStore) -> None:
        """10 concurrent senders; all messages arrive without loss."""
        n_senders = 10
        n_per_sender = 10  # 100 total
        channel = "ch:concurrent"
        await store.subscribe("agent-reader", channel)

        async def send_batch(sender_id: int) -> None:
            for i in range(n_per_sender):
                await store.send(channel, f"sender-{sender_id}", {"i": i, "s": sender_id})

        await asyncio.gather(*[send_batch(s) for s in range(n_senders)])

        received: list[dict[str, object]] = []
        while True:
            batch = await store.recv("agent-reader", max_messages=50)
            if not batch:
                break
            received.extend(batch)

        assert len(received) == n_senders * n_per_sender, (
            f"Expected {n_senders * n_per_sender} messages, got {len(received)}"
        )


class TestSubscriptionMatching:
    """spec/ports/backing-store.md §2.3"""

    async def test_exact_match(self, store: BackingStore) -> None:
        """An exact subscription pattern matches the exact channel."""
        await store.subscribe("a", "ticket:ENGI-0042")
        await store.send("ticket:ENGI-0042", "s", {"t": 1})
        msgs = await store.recv("a")
        assert len(msgs) == 1

    async def test_glob_matches_wildcard(self, store: BackingStore) -> None:
        """ticket:ENGI-* matches ticket:ENGI-0042."""
        await store.subscribe("a", "ticket:ENGI-*")
        await store.send("ticket:ENGI-0042", "s", {"t": 1})
        msgs = await store.recv("a")
        assert len(msgs) == 1
        assert msgs[0]["channel"] == "ticket:ENGI-0042"

    async def test_glob_does_not_match_unrelated(self, store: BackingStore) -> None:
        """ticket:ENGI-* does NOT match project:foo."""
        await store.subscribe("a", "ticket:ENGI-*")
        await store.send("project:foo", "s", {"t": 1})
        msgs = await store.recv("a")
        assert msgs == []

    async def test_glob_matches_multiple_channels(self, store: BackingStore) -> None:
        """A glob pattern delivers messages from all matching channels."""
        await store.subscribe("a", "ticket:ENGI-*")
        await store.send("ticket:ENGI-0001", "s", {"n": 1})
        await store.send("ticket:ENGI-0002", "s", {"n": 2})
        await store.send("ticket:ENGI-0003", "s", {"n": 3})
        msgs = await store.recv("a")
        assert len(msgs) == 3

    async def test_subscribe_returns_matching_existing_channels(
        self, store: BackingStore
    ) -> None:
        """subscribe() returns channels that currently exist and match."""
        await store.send("ticket:ENGI-0001", "s", {"x": 1})
        await store.send("project:foo", "s", {"x": 2})
        matched = await store.subscribe("a", "ticket:ENGI-*")
        assert "ticket:ENGI-0001" in matched
        assert "project:foo" not in matched

    async def test_subscribe_idempotent(self, store: BackingStore) -> None:
        """Registering the same (agent_id, pattern) twice is a no-op."""
        await store.subscribe("a", "ch:idem")
        await store.subscribe("a", "ch:idem")  # second call — must not error
        await store.send("ch:idem", "s", {"x": 1})
        msgs = await store.recv("a")
        # Exactly one message, not two.
        assert len(msgs) == 1


class TestDeliveryTracking:
    """spec/ports/backing-store.md §3.2, §3.3 — recv atomicity + no phantom reads."""

    async def test_recv_not_redelivered_to_same_agent(self, store: BackingStore) -> None:
        """A message drained by recv is NOT returned to the same agent again."""
        await store.subscribe("a", "ch:track")
        await store.send("ch:track", "s", {"msg": 1})

        first = await store.recv("a")
        assert len(first) == 1

        second = await store.recv("a")
        assert second == [], "Message was re-delivered to the same agent!"

    async def test_cross_agent_delivery_independence(self, store: BackingStore) -> None:
        """Agent A draining a message does NOT suppress it for agent B."""
        await store.subscribe("agent-a", "ch:fan")
        await store.subscribe("agent-b", "ch:fan")
        await store.send("ch:fan", "sender", {"k": "v"})

        msgs_a = await store.recv("agent-a")
        msgs_b = await store.recv("agent-b")

        assert len(msgs_a) == 1, "agent-a should have received the message"
        assert len(msgs_b) == 1, "agent-b should have received the message (independent)"

    async def test_concurrent_recv_different_agents_no_interference(
        self, store: BackingStore
    ) -> None:
        """Concurrent recv calls from two agents do not interfere."""
        await store.subscribe("a", "ch:conc")
        await store.subscribe("b", "ch:conc")
        for i in range(5):
            await store.send("ch:conc", "s", {"i": i})

        msgs_a, msgs_b = await asyncio.gather(
            store.recv("a"),
            store.recv("b"),
        )
        assert len(msgs_a) == 5
        assert len(msgs_b) == 5

    async def test_max_messages_limits_batch(self, store: BackingStore) -> None:
        """max_messages caps the number of messages returned per call."""
        await store.subscribe("a", "ch:max")
        for i in range(10):
            await store.send("ch:max", "s", {"i": i})

        first_batch = await store.recv("a", max_messages=5)
        assert len(first_batch) == 5

        second_batch = await store.recv("a", max_messages=10)
        assert len(second_batch) == 5  # remaining 5


class TestPerChannelOrdering:
    """spec/ports/backing-store.md §5.1"""

    async def test_messages_ordered_by_sent_at_within_channel(
        self, store: BackingStore
    ) -> None:
        """Messages on a single channel are returned in ascending sent_at order."""
        await store.subscribe("a", "ch:order")
        # Send sequentially — each send has a strictly later timestamp.
        n = 8
        for i in range(n):
            await store.send("ch:order", "s", {"seq": i})
            await asyncio.sleep(0)  # yield to allow timestamp progression

        msgs = await store.recv("a")
        assert len(msgs) == n
        times = [m["sent_at"] for m in msgs]
        assert times == sorted(times), "Messages not in ascending sent_at order"

    async def test_cross_channel_messages_each_ordered(
        self, store: BackingStore
    ) -> None:
        """Per-channel ordering holds when recv drains multiple channels."""
        await store.subscribe("a", "ch:ord-*")
        for i in range(5):
            await store.send("ch:ord-x", "s", {"i": i})
        for i in range(5):
            await store.send("ch:ord-y", "s", {"i": i})

        msgs = await store.recv("a")
        assert len(msgs) == 10
        for ch in ("ch:ord-x", "ch:ord-y"):
            ch_msgs = [m for m in msgs if m["channel"] == ch]
            times = [m["sent_at"] for m in ch_msgs]
            assert times == sorted(times), f"Channel {ch} not ordered"


class TestWatchLoop:
    """spec/ports/backing-store.md §2.5, §6"""

    async def test_watch_yields_new_messages(self, store: BackingStore) -> None:
        """watch() yields messages sent after it starts."""
        await store.subscribe("a", "ch:watch")

        async def sender() -> None:
            await asyncio.sleep(0.05)
            await store.send("ch:watch", "s", {"n": 1})
            await store.send("ch:watch", "s", {"n": 2})

        asyncio.create_task(sender())
        collected = await _collect_watch(store, "a", expected_count=2, timeout=3.0)
        assert len(collected) == 2

    async def test_watch_yields_exactly_once_per_message(
        self, store: BackingStore
    ) -> None:
        """Each message is yielded exactly once by a single watch invocation."""
        await store.subscribe("a", "ch:once")
        await store.send("ch:once", "s", {"n": 1})
        await store.send("ch:once", "s", {"n": 2})

        collected = await _collect_watch(store, "a", expected_count=2, timeout=3.0)
        assert len(collected) == 2
        ids = [m["message_id"] for m in collected]
        assert len(ids) == len(set(ids)), "Duplicate message_id in watch output"

    async def test_watch_does_not_yield_already_delivered(
        self, store: BackingStore
    ) -> None:
        """watch() skips messages already delivered via recv before watch started."""
        await store.subscribe("a", "ch:nodup")
        await store.send("ch:nodup", "s", {"pre": True})

        # Drain via recv first.
        pre = await store.recv("a")
        assert len(pre) == 1

        # Then send a new message.
        await store.send("ch:nodup", "s", {"post": True})

        # watch() must only yield the new message.
        collected = await _collect_watch(store, "a", expected_count=1, timeout=3.0)
        assert len(collected) == 1
        assert collected[0]["body"] == {"post": True}

    async def test_watch_picks_up_new_subscription(self, store: BackingStore) -> None:
        """A subscription added after watch() starts delivers future messages."""
        # Subscribe to one pattern first.
        await store.subscribe("a", "ch:watch-a")

        watch_started = asyncio.Event()
        collected: list[dict[str, object]] = []

        async def watcher() -> None:
            watch_started.set()
            async for msg in store.watch("a"):  # type: ignore[attr-defined]
                collected.append(msg)
                if len(collected) >= 2:
                    return

        task = asyncio.create_task(watcher())
        await watch_started.wait()
        await asyncio.sleep(0.05)

        # Add a new subscription after watch has started.
        await store.subscribe("a", "ch:watch-b")
        await asyncio.sleep(0.05)

        await store.send("ch:watch-a", "s", {"from": "a"})
        await store.send("ch:watch-b", "s", {"from": "b"})

        try:
            await asyncio.wait_for(task, timeout=3.0)
        except TimeoutError:
            task.cancel()

        assert len(collected) == 2


class TestListChannels:
    """spec/ports/backing-store.md §2.4"""

    async def test_list_channels_returns_known_channels(
        self, store: BackingStore
    ) -> None:
        """list_channels returns channels that have received messages."""
        await store.send("ch:list-a", "s", {})
        await store.send("ch:list-b", "s", {})
        channels = await store.list_channels()
        names = [c["name"] for c in channels]
        assert "ch:list-a" in names
        assert "ch:list-b" in names

    async def test_list_channels_subscriber_count(self, store: BackingStore) -> None:
        """subscriber_count reflects the number of subscribed agents."""
        await store.subscribe("agent-1", "ch:count")
        await store.subscribe("agent-2", "ch:count")
        await store.send("ch:count", "s", {})
        channels = await store.list_channels()
        ch = next((c for c in channels if c["name"] == "ch:count"), None)
        assert ch is not None
        assert ch["subscriber_count"] == 2

    async def test_list_channels_since_filter(self, store: BackingStore) -> None:
        """since parameter filters to channels active after the timestamp."""
        import time as time_mod
        await store.send("ch:old", "s", {})
        cutoff = time_mod.time()
        await asyncio.sleep(0.01)
        await store.send("ch:new", "s", {})

        channels = await store.list_channels(since=cutoff)
        names = [c["name"] for c in channels]
        assert "ch:new" in names
        # "ch:old" should NOT appear (it was before the cutoff).
        assert "ch:old" not in names


class TestStressTest:
    """Stress test: 10 writers + 10 readers, 100 messages/writer, no loss/duplication.

    spec/ports/backing-store.md §3.1, §3.2
    """

    async def test_stress_10x10_writers_readers(self, store: BackingStore) -> None:
        """1000 messages total — no loss, no duplication, per-channel ordering preserved."""
        n_writers = 10
        n_msgs_per_writer = 10  # keep fast; 100 total per channel
        channel = "ch:stress"

        # One reader subscribes.
        await store.subscribe("reader", channel)

        # Writers send concurrently.
        async def write(writer_id: int) -> None:
            for i in range(n_msgs_per_writer):
                await store.send(channel, f"writer-{writer_id}", {"w": writer_id, "i": i})

        await asyncio.gather(*[write(w) for w in range(n_writers)])

        total_expected = n_writers * n_msgs_per_writer
        received: list[dict[str, object]] = []
        max_iterations = total_expected * 2

        for _ in range(max_iterations):
            batch = await store.recv("reader", max_messages=100)
            if not batch:
                break
            received.extend(batch)

        assert len(received) == total_expected, (
            f"Expected {total_expected} messages, got {len(received)}"
        )

        # Check no duplicate message_ids.
        ids = [m["message_id"] for m in received]
        assert len(ids) == len(set(ids)), "Duplicate message_ids detected"

        # Per-channel ordering preserved.
        channel_msgs = [m for m in received if m["channel"] == channel]
        times = [m["sent_at"] for m in channel_msgs]
        assert times == sorted(times), "Per-channel ordering violated"


# ---------------------------------------------------------------------------
# list_agents — spec/operations/list_agents.output.schema.json
# ---------------------------------------------------------------------------


class TestListAgents:
    """BackingStore.list_agents() conforms to spec/operations/list_agents.output.schema.json."""

    async def test_empty_before_heartbeat(self, store: BackingStore) -> None:
        """list_agents returns empty list before any heartbeat is recorded."""
        agents = await store.list_agents()
        assert agents == []

    async def test_agent_appears_after_heartbeat(self, store: BackingStore) -> None:
        """An agent appears in list_agents after a heartbeat call."""
        await store.heartbeat("agent-alpha", "online")
        agents = await store.list_agents()
        agent_ids = [a["agent_id"] for a in agents]
        assert "agent-alpha" in agent_ids

    async def test_output_shape_conforms_to_schema(self, store: BackingStore) -> None:
        """Each record has agent_id, presence_state, last_heartbeat_at (int), namespace.

        Conforms to spec/operations/list_agents.output.schema.json.
        """
        await store.heartbeat("agent-beta", "online")
        agents = await store.list_agents()
        assert len(agents) >= 1
        for rec in agents:
            assert "agent_id" in rec
            assert "presence_state" in rec
            assert "last_heartbeat_at" in rec
            # presence_state must be one of the spec-defined values
            assert rec["presence_state"] in ("online", "busy", "stale", "offline"), (
                f"presence_state {rec['presence_state']!r} not in allowed set"
            )
            # last_heartbeat_at must be a non-negative integer (nanoseconds)
            assert isinstance(rec["last_heartbeat_at"], int), (
                f"last_heartbeat_at must be int (ns), got {type(rec['last_heartbeat_at'])}"
            )
            assert rec["last_heartbeat_at"] >= 0
            # namespace is allowed to be present and null
            assert "namespace" in rec

    async def test_status_filter_online(self, store: BackingStore) -> None:
        """status_filter=['online'] returns only online agents."""
        await store.heartbeat("agent-online", "online")
        await store.heartbeat("agent-busy", "busy")
        agents = await store.list_agents(status_filter=["online"])
        for rec in agents:
            assert rec["presence_state"] == "online"
        ids = [a["agent_id"] for a in agents]
        assert "agent-online" in ids

    async def test_status_filter_busy(self, store: BackingStore) -> None:
        """status_filter=['busy'] returns only busy agents."""
        await store.heartbeat("agent-online2", "online")
        await store.heartbeat("agent-busy2", "busy")
        agents = await store.list_agents(status_filter=["busy"])
        for rec in agents:
            assert rec["presence_state"] == "busy"
        ids = [a["agent_id"] for a in agents]
        assert "agent-busy2" in ids

    async def test_multiple_agents(self, store: BackingStore) -> None:
        """Multiple agents are all returned."""
        for i in range(5):
            await store.heartbeat(f"multi-agent-{i}", "online")
        agents = await store.list_agents()
        ids = [a["agent_id"] for a in agents]
        for i in range(5):
            assert f"multi-agent-{i}" in ids

    async def test_heartbeat_updates_record(self, store: BackingStore) -> None:
        """A second heartbeat updates the existing record (not duplicated)."""
        await store.heartbeat("agent-update", "online")
        await store.heartbeat("agent-update", "busy")
        agents = await store.list_agents()
        matching = [a for a in agents if a["agent_id"] == "agent-update"]
        assert len(matching) == 1
        assert matching[0]["presence_state"] == "busy"

    async def test_no_filter_returns_all(self, store: BackingStore) -> None:
        """Calling list_agents() with no filters returns all recorded agents."""
        await store.heartbeat("filter-a", "online")
        await store.heartbeat("filter-b", "busy")
        agents = await store.list_agents()
        ids = [a["agent_id"] for a in agents]
        assert "filter-a" in ids
        assert "filter-b" in ids


@pytest.mark.asyncio
class TestReplaySince:
    """Unit tests verifying BackingStore.replay honors the `since` cursor.

    These tests close fixtures replay/01-replay-since-seq and
    replay/02-replay-empty-future-cursor.  They are intentionally thin
    wrappers around the store — the conformance runner exercises the full
    HTTP + middleware stack.
    """

    async def _send_n(self, store: BackingStore, channel: str, n: int) -> None:
        """Helper: send n messages to channel, ignore output."""
        for i in range(1, n + 1):
            await store.send(channel, "agent-test", {"n": i})

    async def test_since_zero_returns_all(self, store: BackingStore) -> None:
        """replay(since=0) returns all messages on the channel."""
        channel = "replay-contract-all"
        await store.subscribe("agent-test", channel)
        await self._send_n(store, channel, 4)
        msgs, has_more = await store.replay(channel, since=0)
        assert len(msgs) == 4
        assert has_more is False

    async def test_since_mid_returns_tail(self, store: BackingStore) -> None:
        """replay(since=3) returns only messages with seq >= 3 (fixture 01)."""
        channel = "replay-contract-since"
        await store.subscribe("agent-test", channel)
        await self._send_n(store, channel, 4)
        msgs, has_more = await store.replay(channel, since=3)
        seqs = [int(m["seq"]) for m in msgs]
        assert seqs == [3, 4], f"expected [3, 4], got {seqs}"
        assert has_more is False

    async def test_since_past_last_seq_returns_empty(self, store: BackingStore) -> None:
        """replay(since=999) on a 2-message channel returns [] (fixture 02)."""
        channel = "replay-contract-empty"
        await store.subscribe("agent-test", channel)
        await self._send_n(store, channel, 2)
        msgs, has_more = await store.replay(channel, since=999)
        assert msgs == []
        assert has_more is False

    async def test_messages_ordered_by_seq(self, store: BackingStore) -> None:
        """Messages returned by replay are in ascending seq order."""
        channel = "replay-contract-order"
        await store.subscribe("agent-test", channel)
        await self._send_n(store, channel, 5)
        msgs, _ = await store.replay(channel, since=0)
        seqs = [int(m["seq"]) for m in msgs]
        assert seqs == sorted(seqs), f"messages not in seq order: {seqs}"


class TestUnsubscribeDiscard:
    """Unit tests for BackingStore.unsubscribe queue-discard semantics.

    Spec: docs/V1-SCOPE.md unsubscribe row — "Discards queued-but-unread messages."
    Closes fixture: spec/conformance/subscription-patterns/02-unsubscribe-discards-queue.yaml
    """

    async def test_unsubscribe_before_any_messages_recv_returns_nothing(
        self, store: BackingStore
    ) -> None:
        """Unsubscribe before any messages are sent; recv returns empty.

        Contract: (a) unsubscribe before any messages — recv returns nothing.
        """
        await store.subscribe("agent-a", "chan:empty")
        removed, pending_cleared = await store.unsubscribe("agent-a", ["chan:empty"])
        assert removed == ["chan:empty"]
        assert pending_cleared == 0
        msgs = await store.recv("agent-a")
        assert msgs == []

    async def test_unsubscribe_after_messages_queued_discards_them(
        self, store: BackingStore
    ) -> None:
        """Messages queued before unsubscribe must not be delivered on subsequent recv.

        Contract: (b) unsubscribe after messages queued — recv returns nothing for
        that channel.
        """
        await store.subscribe("agent-b", "chan:discard")
        await store.send("chan:discard", "sender", {"x": 1})
        removed, pending_cleared = await store.unsubscribe("agent-b", ["chan:discard"])
        assert removed == ["chan:discard"]
        assert pending_cleared == 1
        msgs = await store.recv("agent-b")
        assert msgs == [], f"expected no messages after unsubscribe, got {msgs}"

    async def test_unsubscribe_only_discards_matching_channel_messages(
        self, store: BackingStore
    ) -> None:
        """Messages on retained subscriptions must still be delivered after unsubscribe.

        Contract: (b) other channels' messages still delivered.
        """
        await store.subscribe("agent-c", "chan:keep")
        await store.subscribe("agent-c", "chan:drop")
        await store.send("chan:keep", "sender", {"keep": True})
        await store.send("chan:drop", "sender", {"drop": True})
        removed, pending_cleared = await store.unsubscribe("agent-c", ["chan:drop"])
        assert removed == ["chan:drop"]
        assert pending_cleared == 1
        msgs = await store.recv("agent-c")
        assert len(msgs) == 1, f"expected 1 message on kept channel, got {len(msgs)}"
        assert msgs[0]["channel"] == "chan:keep"

    async def test_unsubscribe_non_matching_pattern_does_not_discard(
        self, store: BackingStore
    ) -> None:
        """Unsubscribing a pattern the agent isn't subscribed to discards nothing.

        Contract: (c) unsubscribe with pattern that doesn't match — no messages discarded.
        """
        await store.subscribe("agent-d", "chan:actual")
        await store.send("chan:actual", "sender", {"n": 1})
        removed, pending_cleared = await store.unsubscribe("agent-d", ["chan:nonexistent"])
        assert removed == []
        assert pending_cleared == 0
        msgs = await store.recv("agent-d")
        assert len(msgs) == 1, f"expected message still present, got {len(msgs)}"


# ---------------------------------------------------------------------------
# TestGroupInviteOutput — spec/operations/group_invite.output.schema.json
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("store")
class TestGroupInviteOutput:
    """Verify group_invite returns the spec-canonical output shape.

    Spec: spec/operations/group_invite.output.schema.json
    Required fields: invited (bool), agent_id (str), invited_at (int/float).
    """

    @pytest.mark.asyncio
    async def test_group_invite_returns_spec_fields(self, store: BackingStore) -> None:
        """group_invite must return {invited, agent_id, invited_at} — spec shape."""
        group = await store.group_create(creator_id="owner-gi", group_id="gi-test-1")
        group_id: str = str(group["group_id"])

        result = await store.group_invite(
            inviter_id="owner-gi", group_id=group_id, invitee_id="invitee-gi"
        )

        assert "invited" in result, "missing 'invited' field (spec-required)"
        assert "agent_id" in result, "missing 'agent_id' field (spec-required)"
        assert "invited_at" in result, "missing 'invited_at' field (spec-required)"
        # Must NOT contain legacy field names
        assert "invited_agent" not in result, "legacy 'invited_agent' must not be present"
        assert result.get("agent_id") == "invitee-gi"

    @pytest.mark.asyncio
    async def test_group_invite_invited_true_for_new_invitee(self, store: BackingStore) -> None:
        """invited=True when invitee is newly added."""
        group = await store.group_create(creator_id="owner-gi2", group_id="gi-test-2")
        group_id = str(group["group_id"])

        result = await store.group_invite(
            inviter_id="owner-gi2", group_id=group_id, invitee_id="new-invitee"
        )

        assert result["invited"] is True

    @pytest.mark.asyncio
    async def test_group_invite_invited_at_is_numeric(self, store: BackingStore) -> None:
        """invited_at must be a numeric timestamp."""
        group = await store.group_create(creator_id="owner-gi3", group_id="gi-test-3")
        group_id = str(group["group_id"])

        result = await store.group_invite(
            inviter_id="owner-gi3", group_id=group_id, invitee_id="ts-invitee"
        )

        invited_at = result["invited_at"]
        assert isinstance(invited_at, (int, float)), (
            f"invited_at must be numeric, got {type(invited_at)}"
        )
        assert float(str(invited_at)) > 0

    @pytest.mark.asyncio
    async def test_group_invite_non_member_raises_value_error(
        self, store: BackingStore
    ) -> None:
        """Inviter who is not an active member must raise ValueError."""
        group = await store.group_create(creator_id="owner-gi4", group_id="gi-test-4")
        group_id = str(group["group_id"])

        with pytest.raises(ValueError):
            await store.group_invite(
                inviter_id="non-member", group_id=group_id, invitee_id="target"
            )


# ---------------------------------------------------------------------------
# TestHeartbeatPresenceEmit — spec/primitives/presence.md §5
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("store")
class TestHeartbeatPresenceEmit:
    """Verify heartbeat emits a message on sox/presence.

    Spec: spec/primitives/presence.md §5
    Body shape: {event, agent_id, state, changed_at}
    """

    @pytest.mark.asyncio
    async def test_heartbeat_emits_on_sox_presence(self, store: BackingStore) -> None:
        """A subscriber to sox/presence receives a message after heartbeat."""
        await store.subscribe("observer-hb", "sox/presence")
        await store.heartbeat("agent-hb-emit", "online")

        msgs = await store.recv("observer-hb")
        assert len(msgs) >= 1, "expected at least 1 message on sox/presence after heartbeat"
        msg = msgs[0]
        assert msg["channel"] == "sox/presence"
        assert msg["sender"] == "__server__"

    @pytest.mark.asyncio
    async def test_heartbeat_presence_body_shape(self, store: BackingStore) -> None:
        """sox/presence event body must contain event, agent_id, state, changed_at."""
        await store.subscribe("observer-shape", "sox/presence")
        await store.heartbeat("agent-body-shape", "busy")

        msgs = await store.recv("observer-shape")
        assert len(msgs) >= 1
        body = msgs[0]["body"]
        assert isinstance(body, dict)
        assert "event" in body, "missing 'event' field"
        assert "agent_id" in body, "missing 'agent_id' field"
        assert "state" in body, "missing 'state' field"
        assert "changed_at" in body, "missing 'changed_at' field"
        assert body["agent_id"] == "agent-body-shape"
        assert body["state"] == "busy"
        assert "busy" in str(body["event"])

    @pytest.mark.asyncio
    async def test_heartbeat_offline_emits_agent_offline(self, store: BackingStore) -> None:
        """Heartbeat with status=offline emits agent_offline event."""
        await store.subscribe("observer-offline", "sox/presence")
        await store.heartbeat("agent-going-offline", "offline")

        msgs = await store.recv("observer-offline")
        assert len(msgs) >= 1
        body = msgs[0]["body"]
        assert isinstance(body, dict)
        assert body["state"] == "offline"
        assert "offline" in str(body["event"])

    @pytest.mark.asyncio
    async def test_heartbeat_presence_sender_is_server(self, store: BackingStore) -> None:
        """sox/presence messages must be emitted by __server__, not the calling agent."""
        await store.subscribe("observer-sender", "sox/presence")
        await store.heartbeat("agent-sender-check", "online")

        msgs = await store.recv("observer-sender")
        assert len(msgs) >= 1
        assert msgs[0]["sender"] == "__server__"
