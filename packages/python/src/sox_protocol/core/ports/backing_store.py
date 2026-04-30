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
from typing import AsyncIterator


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
        schema_version: The protocol version this binding targets.  Adapters
            that target a different version MUST override this attribute and
            document the deviation.
    """

    schema_version: str = "1.0"

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
    ) -> tuple[str, float]:
        """Append a message to *channel* and return ``(message_id, sent_at)``.

        Spec reference: ``spec/ports/backing-store.md §2.1``

        Args:
            channel: Non-empty target channel name.
            sender: Non-empty ``agent_id`` of the sending agent.
            body: Opaque JSON-serialisable payload object.
            correlation_id: Optional caller-supplied correlation token.  When
                provided, callers MAY use it for application-level
                deduplication (``spec/ports/backing-store.md §4.1``).

        Returns:
            A ``(message_id, sent_at)`` pair where *message_id* is a
            backing-store-assigned unique identifier and *sent_at* is the Unix
            epoch seconds (floating-point) at which the store accepted the
            message.

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
