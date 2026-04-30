# SPDX-License-Identifier: Apache-2.0
"""Pure cadence-enforcer decision function.

This module is the heart of the SOX cadence enforcer.  It implements the
decision flowchart from CONTRACTS.md §3.4 as a single pure function with
**no I/O** — no file access, no network calls, no clock reads.  The caller
supplies the current timestamp via ``Event.timestamp``.

State mutation lives in ``state.py``.  Adapters are responsible for the
load→decide→save sequence.

Spec reference: CONTRACTS.md §3 and ``spec/schemas/``.

Example::

    from sox_protocol.core.enforcer.events import Event, EventType, Decision
    from sox_protocol.core.enforcer.policy import Policy
    from sox_protocol.core.enforcer.state import State

    event = Event(
        schema_version="1.0",
        event_type=EventType.tool_used,
        agent_id="agent-alpha",
        timestamp=1714300000.0,
        tool_name="bash",
    )
    state = State(agent_id="agent-alpha", tool_calls_since_drain=4)
    policy = Policy()

    decision = decide(event, state, policy)
    # Decision(schema_version='1.0', action=<Action.noop: 'noop'>, ...)
"""

from __future__ import annotations

from typing import Literal

from sox_protocol.core.enforcer.events import Action, Decision, Event, EventType
from sox_protocol.core.enforcer.policy import Policy
from sox_protocol.core.enforcer.state import State

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCHEMA_VERSION: Literal["1.0"] = "1.0"

# The tool name that constitutes a "drain" event when seen via tool_used.
# In practice the channel_recv event_type is the canonical signal, but the
# flowchart also handles recv detection via tool_name for completeness.
_RECV_TOOL_NAMES = frozenset(
    {
        "channels__recv",
        "mcp__sox__channels__recv",
    }
)


# ---------------------------------------------------------------------------
# Helper constructors
# ---------------------------------------------------------------------------


def _noop(reason: str | None = None) -> Decision:
    return Decision(schema_version=_SCHEMA_VERSION, action=Action.noop, reason=reason)


def _inject(message: str, reason: str) -> Decision:
    return Decision(
        schema_version=_SCHEMA_VERSION,
        action=Action.inject,
        message=message,
        reason=reason,
    )


def _block(message: str, reason: str) -> Decision:
    return Decision(
        schema_version=_SCHEMA_VERSION,
        action=Action.block,
        message=message,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Main decision function
# ---------------------------------------------------------------------------


def decide(event: Event, state: State, policy: Policy) -> Decision:
    """Return a :class:`Decision` for *event* given *state* and *policy*.

    Implements the flowchart in CONTRACTS.md §3.4 **exactly** and **without
    side effects**.  The caller is responsible for persisting any state
    mutations implied by the decision.

    The function does NOT mutate *state*.  Callers use
    :meth:`~sox_protocol.core.enforcer.state.StateStore.apply_event` to
    persist state changes, passing the *pre-mutation* state here for the
    threshold checks.

    Args:
        event: The lifecycle event to evaluate.
        state: The *current* (pre-mutation) per-agent state snapshot.
        policy: The operator-supplied (or default) policy parameters.

    Returns:
        A :class:`Decision` indicating what the adapter should do.

    Raises:
        ValueError: If ``event.event_type`` is not a recognised value
            (guard against schema drift at runtime).
    """
    et = event.event_type

    # ------------------------------------------------------------------
    # tool_used
    # ------------------------------------------------------------------
    if et == EventType.tool_used:
        # Flowchart: "tool was channels__recv?"
        if event.tool_name in _RECV_TOOL_NAMES:
            # recv resets the counter — state mutation done by caller.
            # Decision: noop (the reset itself is not an inject trigger).
            return _noop(reason="channel_recv resets counters")

        # Not a recv: increment path (mutation is caller's job).
        # Check threshold AFTER the increment (counter+1).
        new_count = state.tool_calls_since_drain + 1
        if new_count >= policy.reminder_threshold_tool_calls:
            return _inject(
                message=policy.reminder_text_drain,
                reason=(
                    f"tool_calls_since_drain {new_count} >= "
                    f"reminder_threshold_tool_calls {policy.reminder_threshold_tool_calls}"
                ),
            )
        return _noop(reason=f"tool_calls_since_drain will be {new_count}")

    # ------------------------------------------------------------------
    # channel_recv
    # ------------------------------------------------------------------
    if et == EventType.channel_recv:
        # Explicit recv event (as opposed to tool_used with recv tool_name).
        # Always resets counters; always noop from the decision perspective.
        return _noop(reason="channel_recv resets counters")

    # ------------------------------------------------------------------
    # channel_send
    # ------------------------------------------------------------------
    if et == EventType.channel_send:
        # Record the send (mutation: caller's job).
        # Send-and-stall detection: has enough idle turns elapsed since
        # the most recent send without a subsequent recv?
        #
        # The flowchart checks "at or above send_followed_by_idle_turns since
        # send without progress".  We interpret "without progress" as:
        #   turns_since_last_drain >= send_followed_by_idle_turns
        # after a send has occurred (sends_since_last_drain > 0 OR this is
        # the current send event).
        #
        # On the *send* event itself, turns_since_last_drain reflects how many
        # turns have elapsed since the last drain up to this moment.  We check
        # whether that count already qualifies (e.g. the agent sent once, did
        # N idle turns, and is now sending again).
        if policy.suspect_send_and_wait:
            # Only flag if we already had a prior send (sends_since_last_drain
            # > 0) and have accumulated enough idle turns.  A brand-new send
            # (sends_since_last_drain == 0) starts the clock; we don't inject
            # on the very first send.
            if (
                state.sends_since_last_drain > 0
                and state.turns_since_last_drain >= policy.send_followed_by_idle_turns
            ):
                return _inject(
                    message=policy.reminder_text_send_and_wait,
                    reason=(
                        f"sends_since_last_drain={state.sends_since_last_drain}, "
                        f"turns_since_last_drain={state.turns_since_last_drain} >= "
                        f"send_followed_by_idle_turns={policy.send_followed_by_idle_turns}"
                    ),
                )
        return _noop(reason="channel_send recorded")

    # ------------------------------------------------------------------
    # stop_requested
    # ------------------------------------------------------------------
    if et == EventType.stop_requested:
        # The flowchart asks: "inbox non-empty AND force_drain_on_stop?"
        # The enforcer does not query the backing store directly (pure function).
        # Inbox non-empty is inferred from sends_since_last_drain > 0: the agent
        # sent at least one message and has not received a corresponding reply
        # drain.  Callers with richer inbox information can pass it via
        # event.metadata["inbox_non_empty"] = True.
        inbox_non_empty: bool
        if "inbox_non_empty" in event.metadata:
            inbox_non_empty = bool(event.metadata["inbox_non_empty"])
        else:
            # Heuristic: if sends_since_last_drain > 0 the agent has an
            # outbox with outstanding sends but hasn't drained since; treat
            # inbox as potentially non-empty.
            inbox_non_empty = state.sends_since_last_drain > 0

        if inbox_non_empty and policy.force_drain_on_stop:
            return _block(
                message=policy.reminder_text_drain_on_stop,
                reason="stop_requested with non-empty inbox and force_drain_on_stop=True",
            )
        return _noop(reason="stop_requested; inbox empty or force_drain_on_stop=False")

    # ------------------------------------------------------------------
    # turn_started
    # ------------------------------------------------------------------
    if et == EventType.turn_started:
        # Increment turn counter (mutation: caller's job).
        new_turns = state.turns_since_last_drain + 1
        if new_turns >= policy.reminder_threshold_turns:
            return _inject(
                message=policy.reminder_text_drain,
                reason=(
                    f"turns_since_last_drain {new_turns} >= "
                    f"reminder_threshold_turns {policy.reminder_threshold_turns}"
                ),
            )
        return _noop(reason=f"turns_since_last_drain will be {new_turns}")

    # ------------------------------------------------------------------
    # Guard: unknown event_type (schema drift protection)
    # ------------------------------------------------------------------
    raise ValueError(f"Unrecognised event_type: {et!r}")
