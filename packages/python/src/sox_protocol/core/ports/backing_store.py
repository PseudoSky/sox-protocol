# SPDX-License-Identifier: Apache-2.0
"""Python binding of the BackingStore port.

Canonical behaviour contract: ``spec/ports/backing-store.md``

This module contains **only** the ABC that binds the language-neutral port spec
to Python.  It MUST NOT import from ``sox_protocol.adapters`` (enforced by
import-linter; see ``pyproject.toml [tool.importlinter]``).

Any additional semantics beyond what ``spec/ports/backing-store.md`` requires
MUST NOT be added here.  Adapter-specific behaviour (WAL mode, directory
layout, etc.) belongs in the concrete adapter package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class BackpressureInfo:
    """Backpressure status returned alongside a successful send.

    Attributes:
        queue_depth: Number of messages currently buffered for the target channel.
        threshold: Configured limit before backpressure is enforced.
        over_limit: True when queue_depth >= threshold (backpressure active).
        mode: Enforcement mode — ``"enforced"`` raises an error; ``"warn"`` continues.
    """

    queue_depth: int = 0
    threshold: int = 1000
    over_limit: bool = False
    mode: str = "enforced"
    state: str = "ok"


class BackingStore(ABC):
    """Python ABC binding of the SOX ``BackingStore`` port.

    The normative specification for every method's behaviour is
    ``spec/ports/backing-store.md``.  The docstrings below cite the relevant
    spec sections; in case of disagreement between a docstring and the spec,
    the spec wins.

    Adapters MUST implement all five abstract methods.  Omitting any method
    makes the adapter non-conformant and the MCP server MUST refuse to start
    (``spec/ports/backing-store.md §2``).

    Class attribute:
        schema_version: The persisted-data shape version this adapter targets.
            Adapters with a non-trivial on-disk schema (e.g. SQLite) MUST run
            forward migrations on ``initialize()`` to bring an existing
            datastore up to this version.  Adapters whose state is ephemeral
            (memory) or shape-tolerant (filesystem JSON files) MAY hold the
            default and treat ``initialize()`` as schema-only.

            Bumping ``schema_version`` is REQUIRED whenever the adapter's
            persisted shape changes in a way that an older deployment's
            datastore could not satisfy.  Bumps are additive within a major
            version (1.x); destructive changes require a major-version bump
            and an operator-run upgrade tool (no auto-downgrade ever).
    """

    schema_version: str = "1.1"

    # ------------------------------------------------------------------
    # Required methods — spec/ports/backing-store.md §2
    # ------------------------------------------------------------------

    @abstractmethod
    async def send(
        self,
        channel: str,
        sender: str,
        body: dict[str, object],
        correlation_id: str | None = None,
        *,
        reply_to: str | None = None,
    ) -> tuple[str, float, int, BackpressureInfo]:
        """Append a message to *channel* and return ``(message_id, sent_at, seq)``.

        Spec reference: ``spec/ports/backing-store.md §2.1``

        Args:
            channel: Non-empty target channel name.
            sender: Non-empty ``agent_id`` of the sending agent.
            body: Opaque JSON-serialisable payload object.
            correlation_id: Optional caller-supplied correlation token.  When
                provided, callers MAY use it for application-level
                deduplication (``spec/ports/backing-store.md §4.1``).
            reply_to: Optional ``message_id`` of the parent message this
                message is replying to.  Used to build threading chains.
                When ``None`` (the default), the message is a top-level
                message with no parent.  Echoed verbatim in the stored
                envelope and returned on ``recv``/``replay``.

        Returns:
            A ``(message_id, sent_at, seq, backpressure)`` 4-tuple where
            *message_id* is a backing-store-assigned unique identifier,
            *sent_at* is the Unix epoch seconds (floating-point) at which the
            store accepted the message, *seq* is the per-channel monotone
            sequence number (starting at 1) assigned to this message, and
            *backpressure* is a :class:`BackpressureInfo` describing the
            channel's current queue depth relative to its threshold.

        Raises:
            Exception: If the store cannot durably accept the message.  A
                failed ``send`` MUST NOT leave a partially-persisted message
                (``spec/ports/backing-store.md §2.1`` — Failure).

        Atomicity:
            A successful return guarantees the message is immediately visible
            to all matching ``watch`` loops and subsequent ``recv`` calls.
            There is no "pending" intermediate state after ``send`` returns
            successfully (``spec/ports/backing-store.md §3.1``).
        """

    @abstractmethod
    async def recv(
        self,
        agent_id: str,
        channels: list[str] | None = None,
        max_messages: int = 50,
    ) -> list[dict[str, object]]:
        """Drain pending messages for *agent_id* and mark them delivered.

        Spec reference: ``spec/ports/backing-store.md §2.2``

        Args:
            agent_id: Non-empty identifier of the draining agent.
            channels: Channels to drain.  When ``None``, all channels to which
                *agent_id* is subscribed are drained.
            max_messages: Upper bound on messages returned in one call
                (1–1000).  Default 50.

        Returns:
            A list of message objects conforming to
            ``spec/schemas/message.schema.json``.  Within a single channel,
            messages are ordered by ``sent_at`` ascending
            (``spec/ports/backing-store.md §5.1``).  Cross-channel order
            within one response is unspecified (``§5.2``).

        Non-blocking:
            MUST return immediately with whatever messages are currently
            available.  MUST NOT block waiting for new messages
            (``spec/ports/backing-store.md §2.2`` — Non-blocking).

        Atomicity:
            The delivery marking and message selection are a single atomic
            operation per agent.  A message returned here MUST NOT be returned
            to *agent_id* again in any subsequent call, even under concurrent
            ``recv`` calls from other agents
            (``spec/ports/backing-store.md §3.2``).
        """

    @abstractmethod
    async def subscribe(self, agent_id: str, pattern: str) -> list[str]:
        """Register *agent_id*'s interest in channels matching *pattern*.

        Spec reference: ``spec/ports/backing-store.md §2.3``

        Args:
            agent_id: Non-empty identifier of the subscribing agent.
            pattern: Non-empty channel-name pattern (max 256 chars).  Supports
                Unix-glob ``*`` wildcard applied to the full channel name and
                exact match.  Example: ``ticket:ENGI-*`` matches
                ``ticket:ENGI-0042`` but not ``project:foo``.

        Returns:
            A list of channel name strings that currently exist in the store
            and match *pattern*.  An empty list is valid; the subscription is
            still registered and will deliver future messages on matching
            channels.

        Persistence:
            Subscriptions MUST survive MCP server restarts without
            re-subscribing (``spec/ports/backing-store.md §2.3`` —
            Persistence).

        Idempotency:
            Registering the same ``(agent_id, pattern)`` pair twice MUST be
            idempotent — no duplicate subscription, no error
            (``spec/ports/backing-store.md §2.3`` — Idempotency).
        """

    @abstractmethod
    async def list_channels(self, since: float | None = None) -> list[dict[str, object]]:
        """Return a list of known channels.

        Spec reference: ``spec/ports/backing-store.md §2.4``

        Args:
            since: Optional Unix epoch seconds.  When provided, returns only
                channels that have received a message since that timestamp.
                When ``None``, implementations SHOULD return channels with at
                least one subscriber or at least one message in the last 24
                hours.

        Returns:
            A list of dicts, each containing at minimum:

            - ``name`` (str): channel name.
            - ``subscriber_count`` (int, ≥ 0): number of agents currently
              subscribed.
        """

    @abstractmethod
    async def watch(self, agent_id: str) -> AsyncIterator[dict[str, object]]:
        """Async generator yielding new messages for *agent_id* as they arrive.

        Spec reference: ``spec/ports/backing-store.md §2.5``, ``§6``

        This method is typed as returning ``AsyncIterator[dict]`` but
        implementations MUST be ``async def`` generators (i.e., use
        ``yield``).  Callers drive the generator with ``async for`` or
        ``__anext__``.

        Args:
            agent_id: Non-empty identifier of the watching agent.

        Yields:
            Message objects conforming to ``spec/schemas/message.schema.json``
            for channels matching *agent_id*'s registered subscriptions, in
            per-channel send-time order (``spec/ports/backing-store.md §5.3``).

        Exactly-once per invocation:
            Each new matching message MUST be yielded exactly once by a given
            ``watch`` call.  The same message MUST NOT be yielded twice to the
            same invocation (``spec/ports/backing-store.md §2.5`` —
            Semantics).

        Non-duplicating across watch calls:
            If ``watch`` is cancelled and restarted, the new invocation MUST
            NOT re-yield messages already delivered via a previous ``recv``
            call (``spec/ports/backing-store.md §2.5``).

        Non-blocking production:
            A slow ``watch`` consumer for one agent MUST NOT delay ``send``
            calls or ``watch`` delivery to other agents
            (``spec/ports/backing-store.md §6.3``).

        Lifecycle:
            The generator MUST support clean cancellation without resource
            leaks (``spec/ports/backing-store.md §2.5`` — Lifecycle,
            ``§6.4``).
        """
        # This body is never executed; it exists only to make Python treat
        # the abstract method as an async generator (required so that
        # subclasses can override with ``async def watch(...): yield ...``).
        raise NotImplementedError  # pragma: no cover
        yield {}  # pragma: no cover  # makes this an async generator

    @abstractmethod
    async def unsubscribe(self, agent_id: str, patterns: list[str]) -> tuple[list[str], int]:
        """Remove subscriptions matching *patterns* for *agent_id*.

        Returns (removed_patterns, pending_cleared) where pending_cleared is
        the count of queued-but-unread messages discarded for removed subscriptions.
        Spec: spec/operations/unsubscribe.input.schema.json
        """

    @abstractmethod
    async def ack(self, agent_id: str, message_id: str, status: str, reason: str | None = None) -> dict[str, object]:
        """Record an ACK/NACK for message_id. Control-plane only — no channel message.

        Returns {"message_id": str, "status": str, "acked_at": float}.
        Spec: spec/operations/channels_ack.output.schema.json
        """

    @abstractmethod
    async def heartbeat(self, agent_id: str, status: str, ttl: int | None = None) -> dict[str, object]:
        """Update liveness record for agent_id.

        Returns {"agent_id": str, "status": str, "recorded_at": float, "expires_at": float}.
        Default TTL: 30s for stale threshold. expires_at = recorded_at + (ttl or 30).
        Spec: spec/operations/channels_heartbeat.output.schema.json
        """

    @abstractmethod
    async def list_agents(self, status_filter: list[str] | None = None, namespace: str | None = None) -> list[dict[str, object]]:
        """Return liveness table for all known agents.

        Each entry: {"agent_id": str, "status": str, "last_heartbeat_at": float | null}.
        Spec: spec/operations/list_agents.output.schema.json
        """

    @abstractmethod
    async def replay(self, channel: str, since: int = 0, until: int | None = None, limit: int = 100) -> tuple[list[dict[str, object]], bool]:
        """Replay messages from channel with seq >= since.

        Returns (messages, has_more).
        Spec: spec/operations/replay.output.schema.json
        """

    @abstractmethod
    async def group_create(self, creator_id: str, group_id: str | None = None) -> dict[str, object]:
        """Create a group channel, add creator as first active member.

        Returns {"group_id": str, "created_at": float}.
        Spec: spec/operations/group_create.output.schema.json
        """

    @abstractmethod
    async def group_invite(self, inviter_id: str, group_id: str, invitee_id: str) -> dict[str, object]:
        """Invite agent to group. Inviter must be active member.

        Returns {"invited": True, "agent_id": str, "invited_at": float}.
        Spec: spec/operations/group_invite.output.schema.json
        """

    @abstractmethod
    async def group_join(self, agent_id: str, group_id: str) -> dict[str, object]:
        """Accept invitation and join group.

        Returns {"joined": True, "group_id": str, "member_count": int, "joined_at": float}.
        Spec: spec/operations/group_join.output.schema.json
        """

    @abstractmethod
    async def group_leave(self, agent_id: str, group_id: str) -> dict[str, object]:
        """Leave a group.

        Returns {"left": True, "group_id": str, "left_at": float}.
        Spec: spec/operations/group_leave.output.schema.json
        """

    @abstractmethod
    async def group_list_members(self, agent_id: str, group_id: str) -> dict[str, object]:
        """List members of a group.

        Returns {"group_id": str, "members": [{"agent_id": str, "status": str, "joined_at": float}]}.
        Spec: spec/operations/group_list_members.output.schema.json
        """
