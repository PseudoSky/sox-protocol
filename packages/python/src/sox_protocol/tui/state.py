# SPDX-License-Identifier: Apache-2.0
"""Pure dataclasses + reactive store for the SOX chat TUI.

No I/O occurs in this module.  All mutations are synchronous and cheap
so they can be called safely from Textual's UI thread.

Spec reference: ``spec/primitives/channels.md``, ``spec/primitives/presence.md``
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ChannelState:
    """State for a single subscribed channel.

    Attributes:
        name: Channel name (e.g. ``#general``, ``dm/a+b``).
        subscriber_count: Number of known subscribers (from list_channels).
        unread: Number of messages received but not yet focused.
        focused: Whether this channel is currently active in the feed.
    """

    name: str
    subscriber_count: int = 0
    unread: int = 0
    focused: bool = False


@dataclass
class MessageState:
    """State for a single message.

    Attributes:
        message_id: Server-assigned unique ID.
        channel: Channel the message belongs to.
        sender: Agent ID of the sender.
        body: Opaque message body dict.
        sent_at: Unix epoch (float seconds).
        seq: Per-channel sequence number.
        reply_to: Parent message_id for threaded replies (None if root).
        ack_status: Current ACK state: ``pending``, ``ack``, or ``nack``.
        thread_expanded: Whether the reply chain is expanded in the feed.
    """

    message_id: str
    channel: str
    sender: str
    body: dict[str, object]
    sent_at: float
    seq: int
    reply_to: str | None = None
    ack_status: str = "pending"
    thread_expanded: bool = False


@dataclass
class AgentState:
    """State for a single agent in the roster.

    Attributes:
        agent_id: Unique agent identifier.
        presence: One of ``online``, ``busy``, ``stale``, ``offline``, ``unknown``.
        last_heartbeat_at: Epoch ns of last heartbeat (0 if never seen).
        unread_dm: Unread DM count for this agent.
    """

    agent_id: str
    presence: str = "unknown"
    last_heartbeat_at: int = 0
    unread_dm: int = 0


# ---------------------------------------------------------------------------
# Change-event types
# ---------------------------------------------------------------------------

ChangeCallback = Callable[[], None]


# ---------------------------------------------------------------------------
# ChatStore
# ---------------------------------------------------------------------------


class ChatStore:
    """Reactive in-process store binding channels, messages, and agents.

    All public methods are synchronous and must remain cheap (O(n) at worst
    on small n) so they can be called from Textual's UI thread without
    stalling the event loop.

    Observers register via :meth:`on_change` and are notified after every
    mutation.  Textual widgets attach a watcher that calls
    ``self.refresh()`` on the widget.

    Example::

        store = ChatStore()
        store.on_change(lambda: widget.refresh())
        store.ingest_message(msg_dict)
    """

    def __init__(self) -> None:
        self._channels: dict[str, ChannelState] = {}
        self._messages: dict[str, MessageState] = {}  # keyed by message_id
        self._channel_messages: dict[str, list[str]] = {}  # channel -> [message_id]
        self._agents: dict[str, AgentState] = {}
        self._focused_channel: str | None = None
        self._callbacks: list[ChangeCallback] = []

    # ------------------------------------------------------------------
    # Observer registration
    # ------------------------------------------------------------------

    def on_change(self, callback: ChangeCallback) -> None:
        """Register *callback* to be called after any mutation.

        Args:
            callback: Zero-argument callable invoked synchronously after
                each mutation.
        """
        self._callbacks.append(callback)

    def _notify(self) -> None:
        for cb in self._callbacks:
            cb()

    # ------------------------------------------------------------------
    # Read-only views
    # ------------------------------------------------------------------

    @property
    def channels(self) -> list[ChannelState]:
        """All channel states, sorted by name."""
        return sorted(self._channels.values(), key=lambda c: c.name)

    @property
    def focused_channel(self) -> str | None:
        """Currently focused channel name, or None."""
        return self._focused_channel

    @property
    def agents(self) -> list[AgentState]:
        """All agent states, sorted by agent_id."""
        return sorted(self._agents.values(), key=lambda a: a.agent_id)

    def messages_for(self, channel: str) -> list[MessageState]:
        """Return messages for *channel* in seq order.

        Args:
            channel: Channel name.

        Returns:
            List of :class:`MessageState` ordered by ``seq``.
        """
        ids = self._channel_messages.get(channel, [])
        msgs = [self._messages[mid] for mid in ids if mid in self._messages]
        return sorted(msgs, key=lambda m: m.seq)

    def focused_messages(self) -> list[MessageState]:
        """Messages for the currently focused channel (empty list if none)."""
        if self._focused_channel is None:
            return []
        return self.messages_for(self._focused_channel)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def ingest_message(self, msg: dict[str, object]) -> None:
        """Ingest a raw wire-format message dict from the server.

        Deduplicates by ``message_id``.  Creates the channel entry if it
        does not already exist.  Increments the unread counter if the
        message's channel is not currently focused.

        Args:
            msg: Wire-format message dict (see spec/protocol.md §Message
                envelope shape).
        """
        message_id = str(msg.get("message_id", ""))
        if not message_id:
            return
        # Deduplicate
        if message_id in self._messages:
            return

        channel = str(msg.get("channel", ""))
        sender = str(msg.get("sender", ""))
        body_raw = msg.get("body", {})
        body: dict[str, object] = body_raw if isinstance(body_raw, dict) else {}
        sent_at_raw = msg.get("sent_at", time.time())
        sent_at = (
            float(sent_at_raw)
            if isinstance(sent_at_raw, (int, float, str))
            else time.time()
        )
        seq_raw = msg.get("seq", 0)
        seq = int(seq_raw) if isinstance(seq_raw, (int, float, str)) else 0
        reply_to_raw = msg.get("reply_to")
        reply_to = str(reply_to_raw) if reply_to_raw is not None else None

        ms = MessageState(
            message_id=message_id,
            channel=channel,
            sender=sender,
            body=body,
            sent_at=sent_at,
            seq=seq,
            reply_to=reply_to,
        )
        self._messages[message_id] = ms

        if channel not in self._channel_messages:
            self._channel_messages[channel] = []
        self._channel_messages[channel].append(message_id)

        # Ensure channel exists
        if channel not in self._channels:
            self._channels[channel] = ChannelState(name=channel)

        # Increment unread if not focused
        if channel != self._focused_channel:
            self._channels[channel].unread += 1

        self._notify()

    def focus_channel(self, channel: str) -> None:
        """Focus *channel* and clear its unread counter.

        Creates the channel entry if it does not already exist.

        Args:
            channel: Channel name to focus.
        """
        # Unfocus previous
        if self._focused_channel and self._focused_channel in self._channels:
            self._channels[self._focused_channel].focused = False

        self._focused_channel = channel

        if channel not in self._channels:
            self._channels[channel] = ChannelState(name=channel)

        self._channels[channel].focused = True
        self._channels[channel].unread = 0

        self._notify()

    def update_agents(self, agents: list[dict[str, object]]) -> None:
        """Replace the agent roster from a ``list_agents`` response payload.

        Preserves existing ``unread_dm`` counts.

        Args:
            agents: List of agent dicts with keys ``agent_id``,
                ``presence_state``, ``last_heartbeat_at``.
        """
        for entry in agents:
            aid = str(entry.get("agent_id", ""))
            if not aid:
                continue
            presence = str(entry.get("presence_state", "unknown"))
            hb_raw = entry.get("last_heartbeat_at", 0)
            hb = int(hb_raw) if isinstance(hb_raw, (int, float)) else 0
            existing = self._agents.get(aid)
            unread_dm = existing.unread_dm if existing else 0
            self._agents[aid] = AgentState(
                agent_id=aid,
                presence=presence,
                last_heartbeat_at=hb,
                unread_dm=unread_dm,
            )
        self._notify()

    def update_channels(self, channels: list[dict[str, object]]) -> None:
        """Merge channel metadata from a ``list_channels`` response.

        Updates subscriber counts; preserves unread counters and focus state.

        Args:
            channels: List of channel dicts with keys ``name``,
                ``subscriber_count`` (optional).
        """
        for entry in channels:
            name = str(entry.get("name", ""))
            if not name:
                continue
            sub_count_raw = entry.get("subscriber_count", 0)
            sub_count = int(sub_count_raw) if isinstance(sub_count_raw, (int, float)) else 0
            if name in self._channels:
                self._channels[name].subscriber_count = sub_count
            else:
                self._channels[name] = ChannelState(
                    name=name, subscriber_count=sub_count
                )
        self._notify()

    def set_ack_status(self, message_id: str, status: str) -> None:
        """Update the ACK status of a message.

        Args:
            message_id: Target message ID.
            status: New status string (e.g. ``ack``, ``nack``, ``pending``).
        """
        if message_id in self._messages:
            self._messages[message_id].ack_status = status
            self._notify()

    def toggle_thread(self, message_id: str) -> None:
        """Toggle the thread-expanded state of a message.

        Args:
            message_id: Message whose thread to expand/collapse.
        """
        if message_id in self._messages:
            self._messages[message_id].thread_expanded = (
                not self._messages[message_id].thread_expanded
            )
            self._notify()

    def increment_agent_dm(self, agent_id: str) -> None:
        """Increment unread DM counter for *agent_id*.

        Creates the agent entry if absent.

        Args:
            agent_id: Target agent.
        """
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentState(agent_id=agent_id)
        self._agents[agent_id].unread_dm += 1
        self._notify()
