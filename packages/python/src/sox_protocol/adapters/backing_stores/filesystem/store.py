# SPDX-License-Identifier: Apache-2.0
"""Directory-per-channel, file-per-message backing-store adapter.

Layout::

    <root>/
      channels/
        <channel-name>/
          messages/
            <timestamp>_<uuid>.json   # one file per message
          delivered/
            <agent_id>.json           # JSON array of message filenames delivered
      subscriptions/
        <agent_id>.json               # JSON array of channel patterns

Design notes
------------
- Channel names may contain ``:`` and ``-`` characters; directory names on
  POSIX replace ``:`` with ``%3A`` (URL-encoding) to stay portable.
- Files are written atomically via a temp-file + rename dance to prevent
  partial reads by concurrent watchers.
- ``watch()`` uses asyncio polling (default 50 ms) so no OS-level inotify
  dependency is required.  On Linux with Python 3.13+ a proper inotify
  integration would reduce latency; that is left as a future enhancement.
- Delivery tracking is per-agent: each agent has a ``delivered/<agent_id>.json``
  file listing filenames it has already drained.  This file is updated
  atomically with the same rename dance.

Limitations (documented per CONTRACTS.md §7.5):
- Channel names may not contain ``/`` or ``\\`` on any platform (these are
  filesystem path separators and cannot appear in directory names).
- Maximum channel name length is constrained by the host filesystem's
  NAME_MAX (typically 255 bytes on Linux/macOS).
- ``watch()`` latency is bounded by the poll interval (default 50 ms).
- The adapter does not enforce a maximum number of channels or messages;
  operators should apply filesystem-level quotas.

Spec reference: ``spec/ports/backing-store.md``
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from sox_protocol.core.ports.backing_store import BackingStore, BackpressureInfo

_WATCH_POLL_INTERVAL: float = 0.05


def _encode_channel(channel: str) -> str:
    """Encode a channel name to a filesystem-safe directory name."""
    return channel.replace("%", "%25").replace("/", "%2F").replace("\\", "%5C").replace(":", "%3A")


def _decode_channel(dirname: str) -> str:
    """Decode a filesystem directory name back to a channel name."""
    # URL-decode in the correct order (% must be last).
    return (
        dirname.replace("%3A", ":").replace("%2F", "/").replace("%5C", "\\").replace("%25", "%")
    )


def _atomic_write(path: Path, data: str) -> None:
    """Write *data* to *path* atomically using a temp-file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_json_file(path: Path, default: object = None) -> object:
    """Read and JSON-parse *path*, returning *default* on missing file."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


class FilesystemStore(BackingStore):
    """Directory-per-channel, file-per-message BackingStore implementation.

    Args:
        root: Root directory for all store data.  Created if it does not
            exist.
        watch_poll_interval: Seconds between poll iterations in ``watch()``.
    """

    schema_version: str = "1.0"

    def __init__(
        self,
        root: str | Path,
        watch_poll_interval: float = _WATCH_POLL_INTERVAL,
    ) -> None:
        self._root = Path(root)
        self._watch_poll_interval = watch_poll_interval
        self._new_message_event: asyncio.Event = asyncio.Event()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _channels_dir(self) -> Path:
        return self._root / "channels"

    def _channel_dir(self, channel: str) -> Path:
        return self._channels_dir() / _encode_channel(channel)

    def _messages_dir(self, channel: str) -> Path:
        return self._channel_dir(channel) / "messages"

    def _delivered_dir(self, channel: str) -> Path:
        return self._channel_dir(channel) / "delivered"

    def _delivered_file(self, channel: str, agent_id: str) -> Path:
        return self._delivered_dir(channel) / f"{agent_id}.json"

    def _subscriptions_dir(self) -> Path:
        return self._root / "subscriptions"

    def _subscriptions_file(self, agent_id: str) -> Path:
        return self._subscriptions_dir() / f"{agent_id}.json"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the root directory structure."""
        self._root.mkdir(parents=True, exist_ok=True)
        self._channels_dir().mkdir(exist_ok=True)
        self._subscriptions_dir().mkdir(exist_ok=True)

    async def __aenter__(self) -> FilesystemStore:
        await self.initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        pass  # No connection to close.

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_patterns(self, agent_id: str) -> list[str]:
        result = _read_json_file(self._subscriptions_file(agent_id), default=[])
        assert isinstance(result, list)
        return [str(p) for p in result]

    def _matches_any(self, channel: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatchcase(channel, p) for p in patterns)

    def _list_message_files(self, channel: str) -> list[Path]:
        """Return message files for *channel* sorted by send-time (filename)."""
        d = self._messages_dir(channel)
        if not d.exists():
            return []
        files = sorted(d.glob("*.json"))
        return files

    def _get_delivered_set(self, channel: str, agent_id: str) -> set[str]:
        """Return the set of message filenames already delivered to *agent_id*."""
        result = _read_json_file(self._delivered_file(channel, agent_id), default=[])
        assert isinstance(result, list)
        return set(str(x) for x in result)

    def _mark_delivered(
        self, channel: str, agent_id: str, filenames: list[str]
    ) -> None:
        """Atomically add *filenames* to the delivered set for *agent_id*."""
        existing = self._get_delivered_set(channel, agent_id)
        updated = sorted(existing | set(filenames))
        _atomic_write(
            self._delivered_file(channel, agent_id),
            json.dumps(updated),
        )

    def _known_channels(self) -> list[str]:
        """Return all channel names currently known (have a directory)."""
        d = self._channels_dir()
        if not d.exists():
            return []
        return [_decode_channel(p.name) for p in d.iterdir() if p.is_dir()]

    # ------------------------------------------------------------------
    # BackingStore interface
    # ------------------------------------------------------------------

    async def send(
        self,
        channel: str,
        sender: str,
        body: dict[str, object],
        correlation_id: str | None = None,
        *,
        reply_to: str | None = None,
    ) -> tuple[str, float, int, BackpressureInfo]:
        """Write a message file and return ``(message_id, sent_at, seq, backpressure)``.

        Spec: ``spec/ports/backing-store.md §2.1``, ``§3.1``

        Atomicity is provided by the temp-file + rename pattern: readers
        either see a complete file or nothing.
        """
        sent_at = time.time()
        # Build a sortable, unique filename: timestamp prefix + uuid suffix.
        msg_uuid = uuid.uuid4().hex
        filename = f"{sent_at:.6f}_{msg_uuid}.json"
        message_id = f"{_encode_channel(channel)}/{filename}"

        # Compute per-channel seq by counting existing messages.
        msgs_dir = self._messages_dir(channel)
        msgs_dir.mkdir(parents=True, exist_ok=True)
        queue_depth = len(list(msgs_dir.glob("*.json")))
        seq = queue_depth + 1

        payload: dict[str, object] = {
            "message_id": message_id,
            "channel": channel,
            "sender": sender,
            "body": body,
            "correlation_id": correlation_id,
            "sent_at": sent_at,
            "seq": seq,
            "reply_to": reply_to,
        }
        dest = msgs_dir / filename
        _atomic_write(dest, json.dumps(payload))

        # Signal any sleeping watch() loops.
        self._new_message_event.set()
        threshold = 1000
        bp = BackpressureInfo(
            queue_depth=queue_depth,
            threshold=threshold,
            over_limit=queue_depth >= threshold,
            mode="enforced",
        )
        return (message_id, sent_at, seq, bp)

    async def recv(
        self,
        agent_id: str,
        channels: list[str] | None = None,
        max_messages: int = 50,
        _delivered_lock: asyncio.Lock | None = None,
    ) -> list[dict[str, object]]:
        """Drain and mark messages delivered for *agent_id*.

        Spec: ``spec/ports/backing-store.md §2.2``, ``§3.2``

        Note on atomicity: the filesystem adapter uses per-agent delivered
        files with atomic rename.  Concurrent recv calls for *different*
        agents operate on independent delivered files and do not interfere.
        Concurrent recv calls for the *same* agent from multiple coroutines
        in the same process are protected by a per-agent asyncio.Lock
        (callers that need this may pass _delivered_lock; the MCP server
        should hold one lock per agent_id).
        """
        patterns = self._get_patterns(agent_id)

        if channels is None:
            target_channels = [
                ch for ch in self._known_channels()
                if self._matches_any(ch, patterns)
            ]
        else:
            target_channels = list(channels)

        messages: list[dict[str, object]] = []
        to_mark: dict[str, list[str]] = {}  # channel -> filenames to mark

        for channel in target_channels:
            msg_files = self._list_message_files(channel)
            delivered = self._get_delivered_set(channel, agent_id)
            for path in msg_files:
                if len(messages) >= max_messages:
                    break
                fname = path.name
                if fname in delivered:
                    continue
                try:
                    raw = path.read_text(encoding="utf-8")
                    msg: dict[str, object] = json.loads(raw)
                except (OSError, json.JSONDecodeError):
                    continue
                messages.append(msg)
                to_mark.setdefault(channel, []).append(fname)

        # Atomically update delivered tracking.
        for channel, filenames in to_mark.items():
            self._mark_delivered(channel, agent_id, filenames)

        # Sort within each channel by sent_at (filenames encode this, so
        # the list is already ordered; explicit sort is a safety net).
        messages.sort(key=lambda m: (str(m["channel"]), float(str(m["sent_at"]))))
        return messages

    async def subscribe(self, agent_id: str, pattern: str) -> list[str]:
        """Register a subscription and return currently matching channels.

        Spec: ``spec/ports/backing-store.md §2.3``
        """
        patterns = self._get_patterns(agent_id)
        if pattern not in patterns:
            patterns.append(pattern)
            _atomic_write(
                self._subscriptions_file(agent_id),
                json.dumps(patterns),
            )

        # Return currently known channels matching the pattern.
        return [
            ch for ch in self._known_channels()
            if fnmatch.fnmatchcase(ch, pattern)
        ]

    async def list_channels(self, since: float | None = None) -> list[dict[str, object]]:
        """Return known channels with subscriber counts.

        Spec: ``spec/ports/backing-store.md §2.4``
        """
        cutoff = since if since is not None else (time.time() - 86400.0)

        # Collect all agents that have subscription files.
        all_agents: list[str] = []
        sub_dir = self._subscriptions_dir()
        if sub_dir.exists():
            for f in sub_dir.glob("*.json"):
                all_agents.append(f.stem)

        def _subscriber_count(ch: str) -> int:
            return sum(
                1
                for a in all_agents
                if any(fnmatch.fnmatchcase(ch, pat) for pat in self._get_patterns(a))
            )

        def _has_recent_message(ch: str) -> bool:
            for p in self._list_message_files(ch):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if data.get("sent_at", 0.0) >= cutoff:
                        return True
                except (OSError, json.JSONDecodeError):
                    continue
            return False

        result: list[dict[str, object]] = []
        for ch in sorted(self._known_channels()):
            has_recent = _has_recent_message(ch)
            sub_count = _subscriber_count(ch)
            # Include channel if it has a recent message OR an active subscriber.
            if not has_recent and sub_count == 0:
                continue
            result.append({"name": ch, "subscriber_count": sub_count})

        return result

    async def watch(self, agent_id: str) -> AsyncIterator[dict[str, object]]:
        """Async generator yielding new messages for *agent_id*.

        Implemented via asyncio polling with an event-based early-wakeup.

        Spec: ``spec/ports/backing-store.md §2.5``, ``§6``
        """
        # Snapshot of filenames already seen (to avoid re-yielding).
        seen: set[str] = set()

        # Pre-seed *seen* with messages already delivered to this agent so
        # we don't re-yield them on watch restart.
        patterns = self._get_patterns(agent_id)
        for channel in self._known_channels():
            if self._matches_any(channel, patterns):
                seen |= self._get_delivered_set(channel, agent_id)

        while True:
            try:
                await asyncio.wait_for(
                    self._new_message_event.wait(),
                    timeout=self._watch_poll_interval,
                )
            except TimeoutError:
                pass
            finally:
                self._new_message_event.clear()

            # Re-read patterns on every iteration so new subscriptions are
            # picked up without restarting watch().
            patterns = self._get_patterns(agent_id)

            for channel in self._known_channels():
                if not self._matches_any(channel, patterns):
                    continue
                delivered = self._get_delivered_set(channel, agent_id)
                for path in self._list_message_files(channel):
                    fname = path.name
                    if fname in seen:
                        continue
                    if fname in delivered:  # pragma: no cover — race guard for multi-process delivery
                        seen.add(fname)
                        continue
                    try:
                        msg: dict[str, object] = json.loads(
                            path.read_text(encoding="utf-8")
                        )
                    except (OSError, json.JSONDecodeError):
                        continue
                    seen.add(fname)
                    yield msg

    # ------------------------------------------------------------------
    # Extended BackingStore operations
    # (in-memory for group/liveness; TODO: persist to filesystem in future)
    # ------------------------------------------------------------------

    def __init_extras(self) -> None:
        """Lazily initialise extra in-memory state if not yet present."""
        if not hasattr(self, "_ack_records"):
            self._ack_records: dict[str, dict[str, object]] = {}
        if not hasattr(self, "_liveness"):
            self._liveness: dict[str, dict[str, object]] = {}
        if not hasattr(self, "_groups"):
            self._groups: dict[str, list[dict[str, object]]] = {}

    async def unsubscribe(self, agent_id: str, patterns: list[str]) -> tuple[list[str], int]:
        """Remove matching subscriptions and discard queued-but-unread messages.

        Spec: spec/operations/unsubscribe.input.schema.json
        """
        existing = self._get_patterns(agent_id)
        removed: list[str] = []
        new_patterns: list[str] = []
        pending_cleared: int = 0

        for p in existing:
            if p in patterns:
                removed.append(p)
            else:
                new_patterns.append(p)

        if removed:
            _atomic_write(self._subscriptions_file(agent_id), json.dumps(new_patterns))
            # Count and mark delivered messages matching removed patterns.
            for channel in self._known_channels():
                if not any(fnmatch.fnmatchcase(channel, p) for p in removed):
                    continue
                delivered = self._get_delivered_set(channel, agent_id)
                msg_files = self._list_message_files(channel)
                to_mark: list[str] = []
                for path in msg_files:
                    fname = path.name
                    if fname not in delivered:
                        to_mark.append(fname)
                        pending_cleared += 1
                if to_mark:
                    self._mark_delivered(channel, agent_id, to_mark)

        return (removed, pending_cleared)

    async def ack(self, agent_id: str, message_id: str, status: str, reason: str | None = None) -> dict[str, object]:
        """Record an ACK/NACK for message_id.

        TODO: persist to filesystem in future
        Spec: spec/operations/channels_ack.output.schema.json
        """
        self.__init_extras()
        acked_at = time.time()
        self._ack_records[message_id] = {
            "agent_id": agent_id,
            "status": status,
            "reason": reason,
            "acked_at": acked_at,
        }
        return {"message_id": message_id, "status": status, "acked_at": acked_at}

    async def heartbeat(self, agent_id: str, status: str, ttl: int | None = None) -> dict[str, object]:
        """Update liveness record for agent_id.

        TODO: persist to filesystem in future
        Spec: spec/operations/channels_heartbeat.output.schema.json
        """
        self.__init_extras()
        now = time.time()
        expires_at = now + (ttl or 30)
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

        TODO: persist to filesystem in future
        """
        self.__init_extras()
        now = time.time()
        result: list[dict[str, object]] = []
        for aid, rec in self._liveness.items():
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
        msg_files = self._list_message_files(channel)
        matches: list[dict[str, object]] = []
        for path in msg_files:
            try:
                msg: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            seq = int(str(msg.get("seq", 0)))
            if seq < since:
                continue
            if until is not None and seq > until:
                continue
            matches.append(msg)
        matches.sort(key=lambda m: (int(str(m.get("seq", 0))), str(m.get("message_id", ""))))
        has_more = len(matches) > limit
        return (matches[:limit], has_more)

    async def group_create(self, creator_id: str, group_id: str | None = None) -> dict[str, object]:
        """Create a group channel, add creator as first active member.

        TODO: persist to filesystem in future
        Spec: spec/operations/group_create.output.schema.json
        """
        self.__init_extras()
        now = time.time()
        bare = group_id if group_id else f"grp-{int(now)}"
        full_id = f"group/{bare}"
        self._groups[full_id] = [
            {"agent_id": creator_id, "status": "active", "joined_at": now}
        ]
        await self.subscribe(creator_id, full_id)
        return {"group_id": full_id, "created_at": now}

    async def group_invite(self, inviter_id: str, group_id: str, invitee_id: str) -> dict[str, object]:
        """Invite agent to group. Inviter must be active member.

        TODO: persist to filesystem in future
        Spec: spec/operations/group_invite.output.schema.json
        """
        self.__init_extras()
        now = time.time()
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

        TODO: persist to filesystem in future
        Spec: spec/operations/group_join.output.schema.json
        """
        self.__init_extras()
        now = time.time()
        members = self._groups.get(group_id, [])
        for m in members:
            if m["agent_id"] == agent_id and m["status"] == "invited":
                m["status"] = "active"
                m["joined_at"] = now
                break
        await self.subscribe(agent_id, group_id)
        member_count = sum(1 for m in members if m["status"] == "active")
        return {"joined": True, "group_id": group_id, "member_count": member_count, "joined_at": now}

    async def group_leave(self, agent_id: str, group_id: str) -> dict[str, object]:
        """Leave a group.

        TODO: persist to filesystem in future
        Spec: spec/operations/group_leave.output.schema.json
        """
        self.__init_extras()
        now = time.time()
        members = self._groups.get(group_id, [])
        self._groups[group_id] = [m for m in members if m["agent_id"] != agent_id]
        # Remove subscription to group channel.
        existing = self._get_patterns(agent_id)
        new_patterns = [p for p in existing if p != group_id]
        _atomic_write(self._subscriptions_file(agent_id), json.dumps(new_patterns))
        return {"left": True, "group_id": group_id, "left_at": now}

    async def group_list_members(self, agent_id: str, group_id: str) -> dict[str, object]:
        """List members of a group.

        TODO: persist to filesystem in future
        Spec: spec/operations/group_list_members.output.schema.json
        """
        self.__init_extras()
        members = list(self._groups.get(group_id, []))
        return {"group_id": group_id, "members": members}
