# SPDX-License-Identifier: Apache-2.0
"""Policy dataclass for the SOX cadence enforcer.

Operator-tunable parameters loaded from ``${SOX_CONFIG_DIR}/policy.toml``
when present, falling back to the spec-defined defaults.

Spec reference: ``spec/schemas/policy.schema.json`` and CONTRACTS.md §4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Policy:
    """Operator-tunable parameters governing the cadence enforcer.

    All fields have spec-defined defaults matching ``spec/schemas/policy.schema.json``.
    Operators override them via ``${SOX_CONFIG_DIR}/policy.toml``; adapters MAY
    override per-agent.

    Attributes:
        schema_version: Protocol schema version. Always ``"1.0"``.
        reminder_threshold_tool_calls: Number of ``tool_used`` events since last
            drain before a reminder injection is triggered. Default: 5.
        reminder_threshold_turns: Number of ``turn_started`` events since last drain
            before a reminder injection is triggered. Default: 3.
        force_drain_on_stop: When ``True``, a ``stop_requested`` event while the
            agent's inbox is non-empty produces a ``block`` decision. Default: True.
        send_followed_by_idle_turns: Turns after a ``channel_send`` with no
            subsequent ``channel_recv`` that triggers a send-and-wait warning.
            Default: 3.
        suspect_send_and_wait: When ``True``, enables send-and-wait anti-pattern
            detection governed by ``send_followed_by_idle_turns``. Default: True.
        reminder_text_drain: Message injected when tool-call or turn threshold is
            crossed. Uses ``{{recv_tool}}`` placeholder.
        reminder_text_drain_on_stop: Block message for stop-with-non-empty-inbox.
            Uses ``{{recv_tool}}`` placeholder.
        reminder_text_send_and_wait: Message injected on send-and-wait detection.
    """

    schema_version: Literal["1.0"] = "1.0"

    # Cadence thresholds
    reminder_threshold_tool_calls: int = 5
    reminder_threshold_turns: int = 3
    force_drain_on_stop: bool = True

    # Send-and-stall detection
    send_followed_by_idle_turns: int = 3
    suspect_send_and_wait: bool = True

    # Reminder messages (operators can override)
    reminder_text_drain: str = (
        "You have not checked the channels inbox in a while. "
        "Call {{recv_tool}} before continuing if you may be waiting on input."
    )
    reminder_text_drain_on_stop: str = (
        "Inbox not drained. Call {{recv_tool}} and integrate any messages "
        "before completing the task."
    )
    reminder_text_send_and_wait: str = (
        "You sent a message and have not made progress. Per the discipline, "
        "continue under your best-guess interpretation while awaiting reply. "
        "Drain the inbox at the next major decision."
    )
