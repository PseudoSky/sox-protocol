# SPDX-License-Identifier: Apache-2.0
"""MiddlewareContext: per-call context passed through the middleware pipeline.

Mutability rules from ``spec/ports/middleware.md §6`` are enforced via
property setters that raise on illegal writes:

- ``correlation_id`` — pipeline-internal tracking token; frozen after Pipeline
  calls :meth:`freeze_correlation_id`.
- ``connection_id`` — transport-assigned; read-only after construction.
- ``agent_id`` — settable only once (by the auth middleware).
- ``input`` — mutable dict (middleware may normalise fields).
- ``metadata`` — freely mutable for inter-middleware communication.

Spec reference: ``spec/ports/middleware.md §3, §6``
"""

from __future__ import annotations

import uuid
from typing import Literal

# All 15 SOX v1 MUST operations mirroring spec/operations/*.input.schema.json.
Operation = Literal[
    "send",
    "recv",
    "subscribe",
    "unsubscribe",
    "list_channels",
    "list_agents",
    "channels_ack",
    "channels_heartbeat",
    "channels_collect",
    "replay",
    "group_create",
    "group_invite",
    "group_join",
    "group_leave",
    "group_list_members",
]


class MiddlewareContext:
    """Per-call context passed through the middleware pipeline.

    Created fresh for every :meth:`~sox_protocol.core.middleware.pipeline.Pipeline.dispatch`
    call; MUST NOT be shared across concurrent dispatches.

    Args:
        operation: One of the 15 SOX v1 operation names.
        input: Mutable dict of tool-call input arguments.
        connection_id: Opaque connection identifier assigned by the transport layer.
        metadata: Extensible dict for inter-middleware communication.
            Defaults to an empty dict.

    Attributes:
        correlation_id: A server-generated UUID frozen at construction time.
            Read-only after :meth:`freeze_correlation_id` is called.
    """

    __slots__ = (
        "operation",
        "input",
        "metadata",
        "_meta",
        "_connection_id",
        "_agent_id",
        "_correlation_id",
        "_correlation_id_frozen",
    )

    def __init__(
        self,
        operation: str,
        input: dict[str, object],
        connection_id: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.operation: str = operation
        self.input: dict[str, object] = input
        self.metadata: dict[str, object] = metadata if metadata is not None else {}
        self._meta: dict[str, object] = {"middleware_timings": []}
        self._connection_id: str = connection_id
        self._agent_id: str | None = None
        self._correlation_id: str = uuid.uuid4().hex
        self._correlation_id_frozen: bool = False

    # ------------------------------------------------------------------
    # connection_id — read-only
    # ------------------------------------------------------------------

    @property
    def connection_id(self) -> str:
        """Opaque transport-assigned connection identifier (read-only)."""
        return self._connection_id

    @connection_id.setter
    def connection_id(self, value: str) -> None:
        raise AttributeError("connection_id is read-only; assigned at connection time")

    # ------------------------------------------------------------------
    # correlation_id — frozen after freeze_correlation_id()
    # ------------------------------------------------------------------

    @property
    def correlation_id(self) -> str:
        """Pipeline-internal call tracking token (read-only after freeze)."""
        return self._correlation_id

    def freeze_correlation_id(self) -> None:
        """Prevent further internal modification of ``correlation_id``.

        Called by :class:`~sox_protocol.core.middleware.pipeline.Pipeline`
        immediately after context construction.
        """
        self._correlation_id_frozen = True

    # ------------------------------------------------------------------
    # agent_id — settable only once
    # ------------------------------------------------------------------

    @property
    def agent_id(self) -> str | None:
        """Server-certified agent identity; ``None`` until set by auth middleware."""
        return self._agent_id

    @agent_id.setter
    def agent_id(self, value: str) -> None:
        """Set ``agent_id`` exactly once.

        The empty string is rejected: ``agent_id`` is either ``None`` (unset)
        or a non-empty registered identifier. Empty / whitespace values would
        lock the context into an "authenticated as nobody" state and silently
        defeat downstream identity checks.

        Raises:
            AttributeError: If ``agent_id`` has already been set.
            ValueError: If *value* is empty or all-whitespace.
        """
        if self._agent_id is not None:
            raise AttributeError(
                "agent_id is already set; only the auth middleware may set it"
            )
        if not value or not value.strip():
            raise ValueError(
                "agent_id must be a non-empty, non-whitespace string"
            )
        self._agent_id = value

    def __repr__(self) -> str:
        return (
            f"MiddlewareContext(operation={self.operation!r}, "
            f"connection_id={self._connection_id!r}, "
            f"agent_id={self._agent_id!r})"
        )
