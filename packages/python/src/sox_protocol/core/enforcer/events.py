# SPDX-License-Identifier: Apache-2.0
# GENERATED FROM spec/schemas/ — DO NOT EDIT BY HAND
# Regenerate with: make codegen
#
# Source schemas:
#   spec/schemas/event.schema.json
#   spec/schemas/decision.schema.json
#
# Generator: datamodel-code-generator
# Protocol version: 1.0

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Event  (spec/schemas/event.schema.json)
# ---------------------------------------------------------------------------


class EventType(StrEnum):
    """Discriminator for enforcer events.

    Matches the ``event_type`` enum in ``spec/schemas/event.schema.json``.
    """

    tool_used = "tool_used"
    channel_send = "channel_send"
    channel_recv = "channel_recv"
    turn_started = "turn_started"
    stop_requested = "stop_requested"


@dataclass(frozen=True)
class Event:
    """A lifecycle moment delivered to the cadence enforcer's ``decide()`` function.

    Generated from ``spec/schemas/event.schema.json`` (protocol version 1.0).
    """

    schema_version: Literal["1.0"]
    event_type: EventType
    agent_id: str
    timestamp: float
    tool_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Decision  (spec/schemas/decision.schema.json)
# ---------------------------------------------------------------------------


class Action(StrEnum):
    """Action discriminator for enforcer decisions.

    Matches the ``action`` enum in ``spec/schemas/decision.schema.json``.
    """

    noop = "noop"
    inject = "inject"
    block = "block"


@dataclass(frozen=True)
class Decision:
    """The output of the cadence enforcer's ``decide()`` pure function.

    Generated from ``spec/schemas/decision.schema.json`` (protocol version 1.0).

    Constraints (per spec):
    - ``noop``: ``message`` MUST be ``None``.
    - ``inject``: ``message`` MUST be a non-empty string.
    - ``block``: ``message`` MUST be a non-empty string.
    """

    schema_version: Literal["1.0"]
    action: Action
    message: str | None = None
    reason: str | None = None
