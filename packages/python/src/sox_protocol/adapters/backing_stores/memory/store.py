# SPDX-License-Identifier: Apache-2.0
"""Pure in-memory BackingStore implementation.

Intended for use in tests and interactive development.  Data is not persisted;
everything lives in process memory.

Spec reference: ``spec/ports/backing-store.md``
Contract binding: ``sox_protocol.core.ports.backing_store.BackingStore``

Limitations:
- No durability: all data is lost when the process exits or the object is
  garbage-collected.
- Not safe for use from multiple OS processes simultaneously.
- Subscription persistence across restarts is not possible by nature;
  this is acceptable because the in-memory adapter is for tests only.
"""

from __future__ import annotations

import asyncio
import copy
import fnmatch
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sox_protocol.core.ports.backing_store import BackingStore, BackpressureInfo


@dataclass
class _StoredMessage:
    """Internal representation of a persisted message."""

    id: int
    channel: str
    sender: str
    body: dict[str, object]
    correlation_id: str | None
    sent_at: float
    seq: int = 0
    reply_to: str | None = None
    delivered_to: set[str] = field(default_factory=set)

    def to_wire(self) -> dict[str, object]:
        """Return a spec-conformant message dict."""
        return {
            "message_id": str(self.id),
            "channel": self.channel,
            "sender": self.sender,
            "body": copy.deepcopy(self.body),
            "correlation_id": self.correlation_id,
            "sent_at": self.sent_at,
            "seq": self.seq,
            "ts": None,
            "reply_to": self.reply_to,
            "delivered_to": None,
            "origin_server": None,
            "_meta": None,
        }


class MemoryStore(BackingStore):
    """Pure in-memory implementation of ``BackingStore``.

    Thread/task-safe: all mutations are protected by a single ``asyncio.Lock``
    so concurrent coroutines in the same event loop do not corrupt state.

    Usage::

        store = MemoryStore()
        await store.initialize()
        msg_id, sent_at, seq = await store.send("ch", "agent-a", {"k": "v"})
    """

    schema_version: str = "1.0"

    def __init__(self) -> None:
        self._messages: list[_StoredMessage] = []
        self._subscriptions: dict[str, list[str]] = {}  # agent_id -> [patterns]
        self._next_id: int = 1
        self._channel_seq: dict[str, int] = {}  # per-channel seq counter
        self._lock: asyncio.Lock = asyncio.Lock()
        self._new_message_event: asyncio.Event = asyncio.Event()
        self._ack_records: dict[str, dict[str, object]] = {}  # keyed by message_id
        self._liveness: dict[str, dict[str, object]] = {}  # keyed by agent_id
        self._groups: dict[str, list[dict[str, object]]] = {}  # keyed by full group_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """No-op for the in-memory adapter; present for interface parity."""

    async def __aenter__(self) -> MemoryStore:
        await self.initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _patterns_for(self, agent_id: str) -> list[str]:
        return self._subscriptions.get(agent_id, [])

    def _matches_agent(self, channel: str, agent_id: str) -> bool:
        return any(
            fnmatch.fnmatchcase(channel, p)
            for p in self._patterns_for(agent_id)
        )

    # ------------------------------------------------------------------
    # BackingStore interface
    # ------------------------------------------------------------------

    async def send(
        self,
        channel: str,
        sender: str,
        body: dict[str, object],
        correlation_id: str | None = None,
    ) -> tuple[str, float, int, BackpressureInfo]:
        """Persist a message in memory and return ``(message_id, sent_at, seq, backpressure)``.

        Spec: ``spec/ports/backing-store.md §2.1``, ``§3.1``
        """
        sent_at = time.time()
        async with self._lock:
            msg_id = self._next_id
            self._next_id += 1
            seq = self._channel_seq.get(channel, 0) + 1
            self._channel_seq[channel] = seq
            msg = _StoredMessage(
                id=msg_id,
                channel=channel,
                sender=sender,
                body=copy.deepcopy(body),
                correlation_id=correlation_id,
                sent_at=sent_at,
                seq=seq,
            )
            self._messages.append(msg)
            # Compute queue depth: undelivered messages on this channel
            queue_depth = sum(
                1 for m in self._messages
                if m.channel == channel and not m.delivered_to
            )
        self._new_message_event.set()
        threshold = 1000
        bp = BackpressureInfo(
            queue_depth=queue_depth,
            threshold=threshold,
            over_limit=queue_depth >= threshold,
            mode="enforced",
        )
        return (str(msg_id), sent_at, seq, bp)

    async def recv(
        self,
        agent_id: str,
        channels: list[str] | None = None,
        max_messages: int = 50,
    ) -> list[dict[str, object]]:
        """Drain and atomically mark messages delivered for *agent_id*.

        Spec: ``spec/ports/backing-store.md §2.2``, ``§3.2``
        """
        async with self._lock:
            patterns = self._patterns_for(agent_id)
            eligible: list[_StoredMessage] = []
            for msg in self._messages:
                if len(eligible) >= max_messages:
                    break
                if agent_id in msg.delivered_to:
                    continue
                if channels is not None:
                    if msg.channel not in channels:
                        continue
                else:
                    if not any(fnmatch.fnmatchcase(msg.channel, p) for p in patterns):
                        continue
                eligible.append(msg)

            # Sort per-channel by sent_at, then mark delivered atomically.
            eligible.sort(key=lambda m: (m.channel, m.sent_at, m.id))
            for msg in eligible:
                msg.delivered_to.add(agent_id)

        return [m.to_wire() for m in eligible]

    async def subscribe(self, agent_id: str, pattern: str) -> list[str]:
        """Register a subscription and return currently matching channels.

        Spec: ``spec/ports/backing-store.md §2.3``
        """
        async with self._lock:
            patterns = self._subscriptions.setdefault(agent_id, [])
            if pattern not in patterns:
                patterns.append(pattern)

            known_channels: set[str] = {m.channel for m in self._messages}
            return [
                ch for ch in sorted(known_channels)
                if fnmatch.fnmatchcase(ch, pattern)
            ]

    async def list_channels(self, since: float | None = None) -> list[dict[str, object]]:
        """Return known channels with subscriber counts.

        Spec: ``spec/ports/backing-store.md §2.4``
        """
        async with self._lock:
            cutoff = since if since is not None else (time.time() - 86400.0)

            channels: set[str] = set()
            for msg in self._messages:
                if msg.sent_at >= cutoff:
                    channels.add(msg.channel)
            # Include exact-match patterns that name a channel explicitly.
            for agent_id, patterns in self._subscriptions.items():
                for p in patterns:
                    if "*" not in p and "?" not in p and "[" not in p:
                        channels.add(p)

            result: list[dict[str, object]] = []
            for ch in sorted(channels):
                count = sum(
                    1
                    for patterns in self._subscriptions.values()
                    if any(fnmatch.fnmatchcase(ch, p) for p in patterns)
                )
                result.append({"name": ch, "subscriber_count": count})
            return result

    async def watch(self, agent_id: str) -> AsyncIterator[dict[str, object]]:
        """Async generator yielding new messages for *agent_id*.

        Spec: ``spec/ports/backing-store.md §2.5``, ``§6``
        """
        # Snapshot the highest id already delivered to this agent on entry,
        # so we respect the "non-duplicating across watch calls" guarantee.
        async with self._lock:
            last_seen_id: int = max(
                (m.id for m in self._messages if agent_id in m.delivered_to),
                default=0,
            )

        while True:
            try:
                await asyncio.wait_for(
                    self._new_message_event.wait(),
                    timeout=0.05,
                )
            except TimeoutError:
                pass
            finally:
                self._new_message_event.clear()

            async with self._lock:
                patterns = self._patterns_for(agent_id)
                new_msgs = [
                    m
                    for m in self._messages
                    if m.id > last_seen_id
                    and agent_id not in m.delivered_to
                    and any(fnmatch.fnmatchcase(m.channel, p) for p in patterns)
                ]
                new_msgs.sort(key=lambda m: (m.channel, m.sent_at, m.id))
                if new_msgs:
                    last_seen_id = max(m.id for m in new_msgs)
                wire = [m.to_wire() for m in new_msgs]

            for msg in wire:
                yield msg

    async def unsubscribe(self, agent_id: str, patterns: list[str]) -> tuple[list[str], int]:
        """Remove matching subscriptions and discard queued-but-unread messages.

        Spec: spec/operations/unsubscribe.input.schema.json
        """
        removed: list[str] = []
        pending_cleared: int = 0
        async with self._lock:
            existing = self._subscriptions.get(agent_id, [])
            new_patterns: list[str] = []
            for p in existing:
                if p in patterns:
                    removed.append(p)
                    for msg in self._messages:
                        if (
                            agent_id not in msg.delivered_to
                            and fnmatch.fnmatchcase(msg.channel, p)
                        ):
                            msg.delivered_to.add(agent_id)
                            pending_cleared += 1
                else:
                    new_patterns.append(p)
            self._subscriptions[agent_id] = new_patterns
        return (removed, pending_cleared)

    async def ack(self, agent_id: str, message_id: str, status: str, reason: str | None = None) -> dict[str, object]:
        """Record an ACK/NACK for message_id.

        Spec: spec/operations/channels_ack.output.schema.json
        """
        acked_at = time.time()
        async with self._lock:
            self._ack_records[message_id] = {
                "agent_id": agent_id,
                "status": status,
                "reason": reason,
                "acked_at": acked_at,
            }
        return {"message_id": message_id, "status": status, "acked_at": acked_at}

    async def heartbeat(self, agent_id: str, status: str, ttl: int | None = None) -> dict[str, object]:
        """Update liveness record for agent_id.

        Spec: spec/operations/channels_heartbeat.output.schema.json
        """
        now = time.time()
        expires_at = now + (ttl or 30)
        async with self._lock:
            existing = self._liveness.get(agent_id, {})
            self._liveness[agent_id] = {
                "status": status,
                "recorded_at": now,
                "expires_at": expires_at,
                "namespace": existing.get("namespace"),
            }
        return {
            "agent_id": agent_id,
            "status": status,
            "recorded_at": now,
            "expires_at": expires_at,
        }

    async def list_agents(self, status_filter: list[str] | None = None, namespace: str | None = None) -> list[dict[str, object]]:
        """Return liveness table for all known agents.

        Each entry conforms to ``spec/operations/list_agents.output.schema.json``:
        - ``agent_id``: str
        - ``presence_state``: one of "online", "busy", "stale", "offline"
        - ``last_heartbeat_at``: Unix nanoseconds (int); 0 if never heartbeated
        - ``namespace``: str | None
        """
        now = time.time()
        async with self._lock:
            records = dict(self._liveness)
        result: list[dict[str, object]] = []
        for aid, rec in records.items():
            ns = rec.get("namespace")
            if namespace is not None and ns != namespace:
                continue
            expires_at = float(str(rec["expires_at"]))
            reported = str(rec["status"])
            if reported == "offline":
                presence = "offline"
            elif expires_at <= now:
                presence = "stale"
            else:
                presence = reported  # "online" or "busy"
            if status_filter is not None and presence not in status_filter:
                continue
            # last_heartbeat_at: int nanoseconds per output schema
            recorded_at_ns = int(float(str(rec["recorded_at"])) * 1_000_000_000)
            result.append({
                "agent_id": aid,
                "presence_state": presence,
                "last_heartbeat_at": recorded_at_ns,
                "namespace": ns,
            })
        return result

    async def replay(self, channel: str, since: int = 0, until: int | None = None, limit: int = 100) -> tuple[list[dict[str, object]], bool]:
        """Replay messages from channel with seq >= since.

        Spec: spec/operations/replay.output.schema.json
        """
        async with self._lock:
            matches = [
                m for m in self._messages
                if m.channel == channel
                and m.seq >= since
                and (until is None or m.seq <= until)
            ]
        matches.sort(key=lambda m: (m.seq, m.id))
        has_more = len(matches) > limit
        return ([m.to_wire() for m in matches[:limit]], has_more)

    async def group_create(self, creator_id: str, group_id: str | None = None) -> dict[str, object]:
        """Create a group channel, add creator as first active member.

        Spec: spec/operations/group_create.output.schema.json
        """
        now = time.time()
        bare = group_id if group_id else f"grp-{int(now)}"
        full_id = f"group/{bare}"
        async with self._lock:
            self._groups[full_id] = [
                {"agent_id": creator_id, "status": "active", "joined_at": now}
            ]
            patterns = self._subscriptions.setdefault(creator_id, [])
            if full_id not in patterns:
                patterns.append(full_id)
        return {"group_id": full_id, "created_at": now}

    async def group_invite(self, inviter_id: str, group_id: str, invitee_id: str) -> dict[str, object]:
        """Invite agent to group. Inviter must be active member.

        Spec: spec/operations/group_invite.output.schema.json
        """
        now = time.time()
        async with self._lock:
            members = self._groups.get(group_id, [])
            caller_active = any(
                m["agent_id"] == inviter_id and m["status"] == "active"
                for m in members
            )
            if not caller_active:
                raise ValueError(
                    f"Agent {inviter_id!r} is not an active member of {group_id!r}"
                )
            already = any(m["agent_id"] == invitee_id for m in members)
            if not already:
                members.append({"agent_id": invitee_id, "status": "invited", "joined_at": now})
            self._groups[group_id] = members
        return {"invited": True, "agent_id": invitee_id, "invited_at": now}

    async def group_join(self, agent_id: str, group_id: str) -> dict[str, object]:
        """Accept invitation and join group.

        Spec: spec/operations/group_join.output.schema.json
        """
        now = time.time()
        async with self._lock:
            members = self._groups.get(group_id, [])
            for m in members:
                if m["agent_id"] == agent_id and m["status"] == "invited":
                    m["status"] = "active"
                    m["joined_at"] = now
                    break
            patterns = self._subscriptions.setdefault(agent_id, [])
            if group_id not in patterns:
                patterns.append(group_id)
            member_count = sum(1 for m in members if m["status"] == "active")
        return {"joined": True, "group_id": group_id, "member_count": member_count, "joined_at": now}

    async def group_leave(self, agent_id: str, group_id: str) -> dict[str, object]:
        """Leave a group.

        Spec: spec/operations/group_leave.output.schema.json
        """
        now = time.time()
        async with self._lock:
            members = self._groups.get(group_id, [])
            self._groups[group_id] = [m for m in members if m["agent_id"] != agent_id]
            patterns = self._subscriptions.get(agent_id, [])
            self._subscriptions[agent_id] = [p for p in patterns if p != group_id]
        return {"left": True, "group_id": group_id, "left_at": now}

    async def group_list_members(self, agent_id: str, group_id: str) -> dict[str, object]:
        """List members of a group.

        Spec: spec/operations/group_list_members.output.schema.json
        """
        async with self._lock:
            members = list(self._groups.get(group_id, []))
        return {"group_id": group_id, "members": members}
