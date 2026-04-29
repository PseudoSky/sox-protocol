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
from dataclasses import dataclass, field
from typing import AsyncIterator

from sox_protocol.core.ports.backing_store import BackingStore


@dataclass
class _StoredMessage:
    """Internal representation of a persisted message."""

    id: int
    channel: str
    sender: str
    body: dict[str, object]
    correlation_id: str | None
    sent_at: float
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
        }


class MemoryStore(BackingStore):
    """Pure in-memory implementation of ``BackingStore``.

    Thread/task-safe: all mutations are protected by a single ``asyncio.Lock``
    so concurrent coroutines in the same event loop do not corrupt state.

    Usage::

        store = MemoryStore()
        await store.initialize()
        msg_id, sent_at = await store.send("ch", "agent-a", {"k": "v"})
    """

    schema_version: str = "1.0"

    def __init__(self) -> None:
        self._messages: list[_StoredMessage] = []
        self._subscriptions: dict[str, list[str]] = {}  # agent_id -> [patterns]
        self._next_id: int = 1
        self._lock: asyncio.Lock = asyncio.Lock()
        self._new_message_event: asyncio.Event = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """No-op for the in-memory adapter; present for interface parity."""

    async def __aenter__(self) -> "MemoryStore":
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
    ) -> tuple[str, float]:
        """Persist a message in memory and return ``(message_id, sent_at)``.

        Spec: ``spec/ports/backing-store.md §2.1``, ``§3.1``
        """
        sent_at = time.time()
        async with self._lock:
            msg_id = self._next_id
            self._next_id += 1
            msg = _StoredMessage(
                id=msg_id,
                channel=channel,
                sender=sender,
                body=copy.deepcopy(body),
                correlation_id=correlation_id,
                sent_at=sent_at,
            )
            self._messages.append(msg)
        self._new_message_event.set()
        return (str(msg_id), sent_at)

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
            except asyncio.TimeoutError:
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
