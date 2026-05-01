# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ``sox_protocol.tui.state``.

Covers:
- ChatStore.ingest_message: dedup, channel creation, unread, notify
- ChatStore.focus_channel: unfocus previous, clear unread, create on demand
- ChatStore.update_agents: presence transitions, dm preservation
- ChatStore.update_channels: subscriber count merge
- ChatStore.set_ack_status
- ChatStore.toggle_thread
- ChatStore.increment_agent_dm
- ChannelState, MessageState, AgentState dataclasses
- on_change callback registration
- messages_for / focused_messages ordering
"""

from __future__ import annotations

import time

import pytest

from sox_protocol.tui.state import AgentState, ChannelState, ChatStore, MessageState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(
    message_id: str = "1",
    channel: str = "#general",
    sender: str = "agent-a",
    body: dict[str, object] | None = None,
    sent_at: float | None = None,
    seq: int = 1,
    reply_to: str | None = None,
) -> dict[str, object]:
    return {
        "message_id": message_id,
        "channel": channel,
        "sender": sender,
        "body": body or {"text": "hello"},
        "sent_at": sent_at or time.time(),
        "seq": seq,
        "reply_to": reply_to,
    }


# ---------------------------------------------------------------------------
# Dataclass smoke tests
# ---------------------------------------------------------------------------


def test_channel_state_defaults() -> None:
    cs = ChannelState(name="#general")
    assert cs.subscriber_count == 0
    assert cs.unread == 0
    assert cs.focused is False


def test_message_state_defaults() -> None:
    ms = MessageState(
        message_id="1",
        channel="#general",
        sender="a",
        body={},
        sent_at=0.0,
        seq=1,
    )
    assert ms.reply_to is None
    assert ms.ack_status == "pending"
    assert ms.thread_expanded is False


def test_agent_state_defaults() -> None:
    ag = AgentState(agent_id="agent-x")
    assert ag.presence == "unknown"
    assert ag.last_heartbeat_at == 0
    assert ag.unread_dm == 0


# ---------------------------------------------------------------------------
# ChatStore.ingest_message
# ---------------------------------------------------------------------------


def test_ingest_creates_channel() -> None:
    store = ChatStore()
    store.ingest_message(_msg(channel="#alpha"))
    assert any(c.name == "#alpha" for c in store.channels)


def test_ingest_increments_unread_when_not_focused() -> None:
    store = ChatStore()
    store.focus_channel("#other")
    store.ingest_message(_msg(channel="#general"))
    ch = next(c for c in store.channels if c.name == "#general")
    assert ch.unread == 1


def test_ingest_no_unread_when_channel_focused() -> None:
    store = ChatStore()
    store.focus_channel("#general")
    store.ingest_message(_msg(channel="#general"))
    ch = next(c for c in store.channels if c.name == "#general")
    assert ch.unread == 0


def test_ingest_deduplicates_by_message_id() -> None:
    store = ChatStore()
    store.ingest_message(_msg(message_id="dup"))
    store.ingest_message(_msg(message_id="dup"))
    msgs = store.messages_for("#general")
    assert len(msgs) == 1


def test_ingest_missing_message_id_skipped() -> None:
    store = ChatStore()
    store.ingest_message({"channel": "#general", "body": {}})
    assert store.messages_for("#general") == []


def test_ingest_empty_message_id_skipped() -> None:
    store = ChatStore()
    store.ingest_message({"message_id": "", "channel": "#general", "body": {}})
    assert store.messages_for("#general") == []


def test_ingest_notifies_callbacks() -> None:
    store = ChatStore()
    calls: list[int] = []
    store.on_change(lambda: calls.append(1))
    store.ingest_message(_msg())
    assert len(calls) == 1


def test_ingest_reply_to_preserved() -> None:
    store = ChatStore()
    store.ingest_message(_msg(message_id="1"))
    store.ingest_message(_msg(message_id="2", reply_to="1", seq=2))
    msgs = store.messages_for("#general")
    reply = next(m for m in msgs if m.message_id == "2")
    assert reply.reply_to == "1"


def test_ingest_reply_to_none_preserved() -> None:
    store = ChatStore()
    store.ingest_message(_msg(message_id="root", reply_to=None))
    msg = store.messages_for("#general")[0]
    assert msg.reply_to is None


# ---------------------------------------------------------------------------
# ChatStore.focus_channel
# ---------------------------------------------------------------------------


def test_focus_channel_clears_unread() -> None:
    store = ChatStore()
    # Ingest into unfocused channel to build up unread
    store.ingest_message(_msg(channel="#ch", message_id="1"))
    ch = next(c for c in store.channels if c.name == "#ch")
    assert ch.unread == 1
    store.focus_channel("#ch")
    assert ch.unread == 0


def test_focus_channel_sets_focused_flag() -> None:
    store = ChatStore()
    store.focus_channel("#ch")
    ch = next(c for c in store.channels if c.name == "#ch")
    assert ch.focused is True


def test_focus_channel_unfocuses_previous() -> None:
    store = ChatStore()
    store.focus_channel("#first")
    store.focus_channel("#second")
    first = next(c for c in store.channels if c.name == "#first")
    assert first.focused is False


def test_focus_channel_creates_if_absent() -> None:
    store = ChatStore()
    store.focus_channel("#new")
    assert any(c.name == "#new" for c in store.channels)


def test_focus_channel_notifies() -> None:
    store = ChatStore()
    calls: list[int] = []
    store.on_change(lambda: calls.append(1))
    store.focus_channel("#ch")
    assert len(calls) == 1


def test_focused_channel_property() -> None:
    store = ChatStore()
    assert store.focused_channel is None
    store.focus_channel("#ch")
    assert store.focused_channel == "#ch"


# ---------------------------------------------------------------------------
# ChatStore.focused_messages
# ---------------------------------------------------------------------------


def test_focused_messages_empty_when_no_focus() -> None:
    store = ChatStore()
    assert store.focused_messages() == []


def test_focused_messages_returns_focused_channel_msgs() -> None:
    store = ChatStore()
    store.focus_channel("#general")
    store.ingest_message(_msg(message_id="1", channel="#general", seq=1))
    store.ingest_message(_msg(message_id="2", channel="#other", seq=1))
    msgs = store.focused_messages()
    assert len(msgs) == 1
    assert msgs[0].message_id == "1"


def test_messages_for_ordered_by_seq() -> None:
    store = ChatStore()
    store.ingest_message(_msg(message_id="b", seq=2))
    store.ingest_message(_msg(message_id="a", seq=1))
    msgs = store.messages_for("#general")
    assert msgs[0].message_id == "a"
    assert msgs[1].message_id == "b"


# ---------------------------------------------------------------------------
# ChatStore.update_agents
# ---------------------------------------------------------------------------


def test_update_agents_creates_entries() -> None:
    store = ChatStore()
    store.update_agents([
        {"agent_id": "agent-a", "presence_state": "online", "last_heartbeat_at": 1000},
    ])
    assert any(a.agent_id == "agent-a" for a in store.agents)


def test_update_agents_updates_presence() -> None:
    store = ChatStore()
    store.update_agents([{"agent_id": "a", "presence_state": "online", "last_heartbeat_at": 0}])
    store.update_agents([{"agent_id": "a", "presence_state": "stale", "last_heartbeat_at": 0}])
    ag = next(a for a in store.agents if a.agent_id == "a")
    assert ag.presence == "stale"


def test_update_agents_preserves_unread_dm() -> None:
    store = ChatStore()
    store.increment_agent_dm("agent-a")
    store.update_agents([{"agent_id": "agent-a", "presence_state": "online", "last_heartbeat_at": 0}])
    ag = next(a for a in store.agents if a.agent_id == "agent-a")
    assert ag.unread_dm == 1


def test_update_agents_skips_empty_agent_id() -> None:
    store = ChatStore()
    store.update_agents([{"agent_id": "", "presence_state": "online", "last_heartbeat_at": 0}])
    assert store.agents == []


def test_update_agents_none_heartbeat() -> None:
    store = ChatStore()
    store.update_agents([{"agent_id": "a", "presence_state": "online", "last_heartbeat_at": None}])
    ag = next(a for a in store.agents if a.agent_id == "a")
    assert ag.last_heartbeat_at == 0


def test_update_agents_sorted_by_agent_id() -> None:
    store = ChatStore()
    store.update_agents([
        {"agent_id": "z", "presence_state": "online", "last_heartbeat_at": 0},
        {"agent_id": "a", "presence_state": "online", "last_heartbeat_at": 0},
    ])
    ids = [a.agent_id for a in store.agents]
    assert ids == sorted(ids)


def test_update_agents_notifies() -> None:
    store = ChatStore()
    calls: list[int] = []
    store.on_change(lambda: calls.append(1))
    store.update_agents([{"agent_id": "a", "presence_state": "online", "last_heartbeat_at": 0}])
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# ChatStore.update_channels
# ---------------------------------------------------------------------------


def test_update_channels_creates() -> None:
    store = ChatStore()
    store.update_channels([{"name": "#eng", "subscriber_count": 3}])
    ch = next(c for c in store.channels if c.name == "#eng")
    assert ch.subscriber_count == 3


def test_update_channels_merges_subscriber_count() -> None:
    store = ChatStore()
    store.ingest_message(_msg(channel="#general"))
    store.update_channels([{"name": "#general", "subscriber_count": 5}])
    ch = next(c for c in store.channels if c.name == "#general")
    assert ch.subscriber_count == 5


def test_update_channels_skips_empty_name() -> None:
    store = ChatStore()
    store.update_channels([{"name": "", "subscriber_count": 1}])
    assert store.channels == []


def test_update_channels_notifies() -> None:
    store = ChatStore()
    calls: list[int] = []
    store.on_change(lambda: calls.append(1))
    store.update_channels([{"name": "#x", "subscriber_count": 1}])
    assert len(calls) == 1


def test_update_channels_sorted() -> None:
    store = ChatStore()
    store.update_channels([
        {"name": "z-channel"},
        {"name": "a-channel"},
    ])
    names = [c.name for c in store.channels]
    assert names == sorted(names)


# ---------------------------------------------------------------------------
# ChatStore.set_ack_status
# ---------------------------------------------------------------------------


def test_set_ack_status_updates_message() -> None:
    store = ChatStore()
    store.ingest_message(_msg(message_id="1"))
    store.set_ack_status("1", "ack")
    msg = store.messages_for("#general")[0]
    assert msg.ack_status == "ack"


def test_set_ack_status_noop_unknown_id() -> None:
    store = ChatStore()
    # Should not raise
    store.set_ack_status("nonexistent", "ack")


def test_set_ack_status_notifies() -> None:
    store = ChatStore()
    store.ingest_message(_msg(message_id="1"))
    calls: list[int] = []
    store.on_change(lambda: calls.append(1))
    store.set_ack_status("1", "nack")
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# ChatStore.toggle_thread
# ---------------------------------------------------------------------------


def test_toggle_thread_expands() -> None:
    store = ChatStore()
    store.ingest_message(_msg(message_id="1"))
    store.toggle_thread("1")
    msg = store.messages_for("#general")[0]
    assert msg.thread_expanded is True


def test_toggle_thread_collapses() -> None:
    store = ChatStore()
    store.ingest_message(_msg(message_id="1"))
    store.toggle_thread("1")
    store.toggle_thread("1")
    msg = store.messages_for("#general")[0]
    assert msg.thread_expanded is False


def test_toggle_thread_noop_unknown_id() -> None:
    store = ChatStore()
    # Should not raise
    store.toggle_thread("nonexistent")


def test_toggle_thread_notifies() -> None:
    store = ChatStore()
    store.ingest_message(_msg(message_id="1"))
    calls: list[int] = []
    store.on_change(lambda: calls.append(1))
    store.toggle_thread("1")
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# ChatStore.increment_agent_dm
# ---------------------------------------------------------------------------


def test_increment_agent_dm_creates_agent() -> None:
    store = ChatStore()
    store.increment_agent_dm("new-agent")
    ag = next(a for a in store.agents if a.agent_id == "new-agent")
    assert ag.unread_dm == 1


def test_increment_agent_dm_accumulates() -> None:
    store = ChatStore()
    store.increment_agent_dm("a")
    store.increment_agent_dm("a")
    ag = next(a for a in store.agents if a.agent_id == "a")
    assert ag.unread_dm == 2


def test_increment_agent_dm_notifies() -> None:
    store = ChatStore()
    calls: list[int] = []
    store.on_change(lambda: calls.append(1))
    store.increment_agent_dm("a")
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Multiple callbacks
# ---------------------------------------------------------------------------


def test_multiple_callbacks_all_called() -> None:
    store = ChatStore()
    results: list[str] = []
    store.on_change(lambda: results.append("cb1"))
    store.on_change(lambda: results.append("cb2"))
    store.ingest_message(_msg())
    assert "cb1" in results
    assert "cb2" in results
