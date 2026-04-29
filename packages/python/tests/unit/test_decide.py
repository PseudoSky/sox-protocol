"""Exhaustive table-driven tests for decide().

Coverage target: 100% line coverage on decide.py.

Test matrix (per acceptance criteria):
- cold-start (fresh state, no prior events)
- tool-call-threshold-crossed (tool_calls_since_drain reaches threshold)
- recv-resets-counter (channel_recv and tool_used with recv tool_name both reset)
- turn-threshold-crossed (turns_since_last_drain reaches threshold)
- send-and-stall (send_followed_by_idle_turns sends+turns anti-pattern)
- stop-without-drain (force_drain_on_stop blocks when inbox non-empty)
- stop-no-block (inbox empty or policy disabled)
- boundary conditions at exactly threshold and just below
"""

from __future__ import annotations

import pytest

from sox_protocol.core.enforcer.decide import decide
from sox_protocol.core.enforcer.events import Action, Decision, Event, EventType
from sox_protocol.core.enforcer.policy import Policy
from sox_protocol.core.enforcer.state import State

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_TS = 1_714_300_000.0
_AGENT = "agent-test"
_SCHEMA = "1.0"


def _event(
    event_type: EventType,
    tool_name: str | None = None,
    metadata: dict[str, object] | None = None,
) -> Event:
    return Event(
        schema_version=_SCHEMA,
        event_type=event_type,
        agent_id=_AGENT,
        timestamp=_TS,
        tool_name=tool_name,
        metadata=metadata or {},
    )


def _state(
    tool_calls_since_drain: int = 0,
    turns_since_last_drain: int = 0,
    sends_since_last_drain: int = 0,
    last_drain_ts: float | None = None,
    last_send_ts: float | None = None,
) -> State:
    return State(
        agent_id=_AGENT,
        tool_calls_since_drain=tool_calls_since_drain,
        turns_since_last_drain=turns_since_last_drain,
        sends_since_last_drain=sends_since_last_drain,
        last_drain_ts=last_drain_ts,
        last_send_ts=last_send_ts,
    )


_DEFAULT_POLICY = Policy()


# ===========================================================================
# tool_used — recv detection
# ===========================================================================


class TestToolUsedRecvDetection:
    """tool_used events with recv tool names reset counters (noop)."""

    @pytest.mark.parametrize(
        "tool_name",
        [
            "channels__recv",
            "mcp__sox__channels__recv",
        ],
    )
    def test_recv_tool_name_is_noop(self, tool_name: str) -> None:
        state = _state(tool_calls_since_drain=10)
        ev = _event(EventType.tool_used, tool_name=tool_name)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_recv_tool_name_noop_even_above_threshold(self) -> None:
        """Even with tool_calls_since_drain >> threshold, recv tool_name => noop."""
        state = _state(tool_calls_since_drain=100)
        ev = _event(EventType.tool_used, tool_name="channels__recv")
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_recv_tool_reason_mentions_reset(self) -> None:
        state = _state(tool_calls_since_drain=3)
        ev = _event(EventType.tool_used, tool_name="mcp__sox__channels__recv")
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.reason is not None
        assert "reset" in result.reason.lower()


# ===========================================================================
# tool_used — non-recv paths
# ===========================================================================


class TestToolUsedIncrement:
    """tool_used with non-recv tool names increment the counter."""

    @pytest.mark.parametrize(
        "tool_calls_since_drain, threshold, expected_action",
        [
            # cold start — 0 prior calls, threshold=5 → after increment=1, below threshold
            (0, 5, Action.noop),
            # one below threshold — 3 prior calls, threshold=5 → after increment=4, below
            (3, 5, Action.noop),
            # exactly at threshold after increment: 4 prior → new=5 == threshold → inject
            (4, 5, Action.inject),
            # already at threshold: 5 prior → new=6 > threshold → inject
            (5, 5, Action.inject),
            # well above threshold
            (20, 5, Action.inject),
            # threshold of 1 — any tool call triggers inject
            (0, 1, Action.inject),
            # threshold of 1, already above
            (5, 1, Action.inject),
        ],
    )
    def test_tool_used_threshold(
        self,
        tool_calls_since_drain: int,
        threshold: int,
        expected_action: Action,
    ) -> None:
        policy = Policy(reminder_threshold_tool_calls=threshold)
        state = _state(tool_calls_since_drain=tool_calls_since_drain)
        ev = _event(EventType.tool_used, tool_name="bash")
        result = decide(ev, state, policy)
        assert result.action == expected_action

    def test_tool_used_inject_has_message(self) -> None:
        state = _state(tool_calls_since_drain=4)  # next call brings to 5
        ev = _event(EventType.tool_used, tool_name="bash")
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.inject
        assert result.message is not None
        assert len(result.message) > 0

    def test_tool_used_inject_uses_policy_reminder_text(self) -> None:
        custom_text = "CUSTOM DRAIN REMINDER"
        policy = Policy(
            reminder_threshold_tool_calls=1,
            reminder_text_drain=custom_text,
        )
        state = _state(tool_calls_since_drain=0)
        ev = _event(EventType.tool_used, tool_name="read_file")
        result = decide(ev, state, policy)
        assert result.action == Action.inject
        assert result.message == custom_text

    def test_tool_used_noop_has_no_message(self) -> None:
        state = _state(tool_calls_since_drain=0)
        ev = _event(EventType.tool_used, tool_name="bash")
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop
        assert result.message is None

    def test_tool_used_below_threshold_boundary(self) -> None:
        """One below threshold (threshold-1 prior calls) must be noop."""
        threshold = 5
        policy = Policy(reminder_threshold_tool_calls=threshold)
        # After increment, count will be threshold-1 → still below
        state = _state(tool_calls_since_drain=threshold - 2)
        ev = _event(EventType.tool_used, tool_name="bash")
        result = decide(ev, state, policy)
        assert result.action == Action.noop

    def test_tool_used_tool_name_none_is_non_recv(self) -> None:
        """tool_name=None should not be treated as recv; just increment."""
        state = _state(tool_calls_since_drain=4)
        ev = _event(EventType.tool_used, tool_name=None)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.inject


# ===========================================================================
# channel_recv
# ===========================================================================


class TestChannelRecv:
    """channel_recv event always returns noop."""

    def test_channel_recv_is_noop(self) -> None:
        state = _state(tool_calls_since_drain=100, turns_since_last_drain=100)
        ev = _event(EventType.channel_recv)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_channel_recv_reason_mentions_reset(self) -> None:
        state = _state()
        ev = _event(EventType.channel_recv)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.reason is not None
        assert "reset" in result.reason.lower()


# ===========================================================================
# channel_send
# ===========================================================================


class TestChannelSend:
    """channel_send event — send-and-stall detection."""

    def test_first_send_is_noop(self) -> None:
        """Brand-new send (sends_since_last_drain == 0) does not inject."""
        state = _state(sends_since_last_drain=0, turns_since_last_drain=99)
        ev = _event(EventType.channel_send)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_send_and_stall_detected(self) -> None:
        """Prior send + enough idle turns triggers inject."""
        policy = Policy(send_followed_by_idle_turns=3, suspect_send_and_wait=True)
        # sends_since_last_drain > 0 and turns_since_last_drain >= threshold
        state = _state(sends_since_last_drain=1, turns_since_last_drain=3)
        ev = _event(EventType.channel_send)
        result = decide(ev, state, policy)
        assert result.action == Action.inject
        assert result.message == policy.reminder_text_send_and_wait

    def test_send_and_stall_exact_boundary(self) -> None:
        """turns_since_last_drain == send_followed_by_idle_turns triggers inject."""
        policy = Policy(send_followed_by_idle_turns=3, suspect_send_and_wait=True)
        state = _state(sends_since_last_drain=1, turns_since_last_drain=3)
        ev = _event(EventType.channel_send)
        result = decide(ev, state, policy)
        assert result.action == Action.inject

    def test_send_below_idle_threshold_is_noop(self) -> None:
        """Prior send but turns below threshold → noop."""
        policy = Policy(send_followed_by_idle_turns=3, suspect_send_and_wait=True)
        state = _state(sends_since_last_drain=1, turns_since_last_drain=2)
        ev = _event(EventType.channel_send)
        result = decide(ev, state, policy)
        assert result.action == Action.noop

    def test_send_and_stall_disabled_by_policy(self) -> None:
        """suspect_send_and_wait=False disables detection entirely."""
        policy = Policy(send_followed_by_idle_turns=1, suspect_send_and_wait=False)
        state = _state(sends_since_last_drain=5, turns_since_last_drain=99)
        ev = _event(EventType.channel_send)
        result = decide(ev, state, policy)
        assert result.action == Action.noop

    def test_send_and_stall_uses_custom_message(self) -> None:
        custom = "STOP WAITING"
        policy = Policy(
            send_followed_by_idle_turns=1,
            suspect_send_and_wait=True,
            reminder_text_send_and_wait=custom,
        )
        state = _state(sends_since_last_drain=1, turns_since_last_drain=1)
        ev = _event(EventType.channel_send)
        result = decide(ev, state, policy)
        assert result.action == Action.inject
        assert result.message == custom

    def test_send_and_stall_above_idle_threshold_injects(self) -> None:
        """turns well above threshold also triggers inject."""
        policy = Policy(send_followed_by_idle_turns=3, suspect_send_and_wait=True)
        state = _state(sends_since_last_drain=2, turns_since_last_drain=50)
        ev = _event(EventType.channel_send)
        result = decide(ev, state, policy)
        assert result.action == Action.inject


# ===========================================================================
# stop_requested
# ===========================================================================


class TestStopRequested:
    """stop_requested — force-drain enforcement."""

    def test_stop_with_nonempty_inbox_explicit_metadata_blocks(self) -> None:
        """inbox_non_empty=True in metadata + force_drain_on_stop → block."""
        state = _state()
        ev = _event(EventType.stop_requested, metadata={"inbox_non_empty": True})
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.block
        assert result.message == _DEFAULT_POLICY.reminder_text_drain_on_stop

    def test_stop_with_empty_inbox_explicit_metadata_is_noop(self) -> None:
        """inbox_non_empty=False in metadata → noop regardless of sends."""
        state = _state(sends_since_last_drain=10)
        ev = _event(EventType.stop_requested, metadata={"inbox_non_empty": False})
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_stop_heuristic_nonempty_inbox_blocks(self) -> None:
        """No metadata but sends_since_last_drain > 0 heuristic → block."""
        state = _state(sends_since_last_drain=1)
        ev = _event(EventType.stop_requested)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.block

    def test_stop_heuristic_empty_inbox_is_noop(self) -> None:
        """sends_since_last_drain == 0 → inbox assumed empty → noop."""
        state = _state(sends_since_last_drain=0)
        ev = _event(EventType.stop_requested)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_stop_force_drain_disabled_is_noop(self) -> None:
        """force_drain_on_stop=False → noop even when inbox non-empty."""
        policy = Policy(force_drain_on_stop=False)
        state = _state(sends_since_last_drain=5)
        ev = _event(EventType.stop_requested, metadata={"inbox_non_empty": True})
        result = decide(ev, state, policy)
        assert result.action == Action.noop

    def test_stop_block_uses_custom_message(self) -> None:
        custom = "DRAIN NOW OR ELSE"
        policy = Policy(
            force_drain_on_stop=True,
            reminder_text_drain_on_stop=custom,
        )
        state = _state(sends_since_last_drain=1)
        ev = _event(EventType.stop_requested)
        result = decide(ev, state, policy)
        assert result.action == Action.block
        assert result.message == custom

    def test_stop_block_reason_is_populated(self) -> None:
        state = _state(sends_since_last_drain=1)
        ev = _event(EventType.stop_requested)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.block
        assert result.reason is not None

    def test_stop_noop_when_no_sends_no_metadata_force_drain_true(self) -> None:
        """Cold start: no sends, no metadata, force_drain_on_stop=True → noop."""
        state = _state()
        ev = _event(EventType.stop_requested)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_stop_inbox_non_empty_falsy_value_is_noop(self) -> None:
        """inbox_non_empty=0 (falsy) in metadata → noop."""
        state = _state(sends_since_last_drain=5)
        ev = _event(EventType.stop_requested, metadata={"inbox_non_empty": 0})
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop


# ===========================================================================
# turn_started
# ===========================================================================


class TestTurnStarted:
    """turn_started events increment turns counter and check threshold."""

    @pytest.mark.parametrize(
        "turns_since_last_drain, threshold, expected_action",
        [
            # cold start — 0 prior turns, threshold=3 → after inc=1, below
            (0, 3, Action.noop),
            # one below threshold: 1 prior → new=2, below threshold=3
            (1, 3, Action.noop),
            # exactly reaches threshold: 2 prior → new=3 == threshold → inject
            (2, 3, Action.inject),
            # above threshold: 3 prior → new=4 → inject
            (3, 3, Action.inject),
            # threshold=1: any turn triggers inject
            (0, 1, Action.inject),
        ],
    )
    def test_turn_threshold(
        self,
        turns_since_last_drain: int,
        threshold: int,
        expected_action: Action,
    ) -> None:
        policy = Policy(reminder_threshold_turns=threshold)
        state = _state(turns_since_last_drain=turns_since_last_drain)
        ev = _event(EventType.turn_started)
        result = decide(ev, state, policy)
        assert result.action == expected_action

    def test_turn_inject_has_message(self) -> None:
        state = _state(turns_since_last_drain=2)  # next turn brings to 3
        ev = _event(EventType.turn_started)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.inject
        assert result.message is not None

    def test_turn_inject_uses_policy_drain_text(self) -> None:
        custom = "CHECK YOUR INBOX"
        policy = Policy(reminder_threshold_turns=1, reminder_text_drain=custom)
        state = _state(turns_since_last_drain=0)
        ev = _event(EventType.turn_started)
        result = decide(ev, state, policy)
        assert result.action == Action.inject
        assert result.message == custom

    def test_turn_noop_message_is_none(self) -> None:
        state = _state(turns_since_last_drain=0)
        ev = _event(EventType.turn_started)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop
        assert result.message is None


# ===========================================================================
# Decision schema invariants
# ===========================================================================


class TestDecisionInvariants:
    """All decisions must carry schema_version='1.0'."""

    @pytest.mark.parametrize(
        "event_type, tool_name, state_kwargs, metadata",
        [
            (EventType.tool_used, "bash", {"tool_calls_since_drain": 0}, {}),
            (EventType.tool_used, "channels__recv", {"tool_calls_since_drain": 5}, {}),
            (EventType.channel_recv, None, {}, {}),
            (EventType.channel_send, None, {"sends_since_last_drain": 0}, {}),
            (EventType.turn_started, None, {"turns_since_last_drain": 0}, {}),
            (EventType.stop_requested, None, {"sends_since_last_drain": 0}, {}),
        ],
    )
    def test_schema_version_always_10(
        self,
        event_type: EventType,
        tool_name: str | None,
        state_kwargs: dict[str, object],
        metadata: dict[str, object],
    ) -> None:
        state = _state(**state_kwargs)  # type: ignore[arg-type]
        ev = _event(event_type, tool_name=tool_name, metadata=metadata)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.schema_version == "1.0"

    def test_noop_message_is_always_none(self) -> None:
        """Spec: noop action MUST have message=None."""
        state = _state()
        ev = _event(EventType.channel_recv)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop
        assert result.message is None

    def test_inject_message_is_non_empty_string(self) -> None:
        """Spec: inject action MUST have non-empty message."""
        state = _state(turns_since_last_drain=2)
        ev = _event(EventType.turn_started)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.inject
        assert isinstance(result.message, str)
        assert len(result.message) > 0

    def test_block_message_is_non_empty_string(self) -> None:
        """Spec: block action MUST have non-empty message."""
        state = _state(sends_since_last_drain=1)
        ev = _event(EventType.stop_requested)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.block
        assert isinstance(result.message, str)
        assert len(result.message) > 0

    def test_returns_decision_instance(self) -> None:
        state = _state()
        ev = _event(EventType.channel_recv)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert isinstance(result, Decision)


# ===========================================================================
# Cold-start scenario
# ===========================================================================


class TestColdStart:
    """Simulate a brand-new agent with default (zeroed) state."""

    def test_cold_start_tool_used_below_threshold(self) -> None:
        state = State(agent_id=_AGENT)  # default zeros
        ev = _event(EventType.tool_used, tool_name="bash")
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_cold_start_turn_started_below_threshold(self) -> None:
        state = State(agent_id=_AGENT)
        ev = _event(EventType.turn_started)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_cold_start_stop_is_noop(self) -> None:
        state = State(agent_id=_AGENT)
        ev = _event(EventType.stop_requested)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_cold_start_channel_send_is_noop(self) -> None:
        state = State(agent_id=_AGENT)
        ev = _event(EventType.channel_send)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop


# ===========================================================================
# Full scenario: recv-resets-counter
# ===========================================================================


class TestRecvResetsCounterScenario:
    """
    Simulate the sequence:
      1. Several tool calls accumulate (crossing threshold).
      2. channel_recv resets counters.
      3. Subsequent tool calls start from zero.
    """

    def test_recv_resets_accumulated_tool_calls(self) -> None:
        # After drain the state would have tool_calls_since_drain=0.
        # The decide() call on a tool_used event post-drain should be noop
        # (count goes from 0 to 1, below threshold=5).
        state_after_drain = _state(tool_calls_since_drain=0)
        ev = _event(EventType.tool_used, tool_name="bash")
        result = decide(ev, state_after_drain, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_pre_recv_would_have_injected(self) -> None:
        """Establish that with counter=4, next tool_used injects (threshold=5)."""
        state_pre_drain = _state(tool_calls_since_drain=4)
        ev = _event(EventType.tool_used, tool_name="bash")
        result = decide(ev, state_pre_drain, _DEFAULT_POLICY)
        assert result.action == Action.inject

    def test_after_recv_no_inject_on_next_tool(self) -> None:
        """After recv (counter reset to 0), next tool_used is noop."""
        state_post_drain = _state(tool_calls_since_drain=0)
        ev = _event(EventType.tool_used, tool_name="bash")
        result = decide(ev, state_post_drain, _DEFAULT_POLICY)
        assert result.action == Action.noop


# ===========================================================================
# Full scenario: send-and-stall detection
# ===========================================================================


class TestSendAndStallScenario:
    """
    Simulate the sequence:
      1. Agent sends a message (first send).
      2. Agent runs several turns without recv.
      3. Agent sends again — stall detected.
    """

    def test_first_send_no_stall(self) -> None:
        state = _state(sends_since_last_drain=0, turns_since_last_drain=0)
        ev = _event(EventType.channel_send)
        result = decide(ev, state, _DEFAULT_POLICY)
        assert result.action == Action.noop

    def test_second_send_after_enough_idle_turns_detects_stall(self) -> None:
        policy = Policy(send_followed_by_idle_turns=3, suspect_send_and_wait=True)
        # Simulate: sent once, then 3 idle turns, now sending again.
        state = _state(sends_since_last_drain=1, turns_since_last_drain=3)
        ev = _event(EventType.channel_send)
        result = decide(ev, state, policy)
        assert result.action == Action.inject

    def test_second_send_with_insufficient_idle_turns_is_noop(self) -> None:
        policy = Policy(send_followed_by_idle_turns=3, suspect_send_and_wait=True)
        state = _state(sends_since_last_drain=1, turns_since_last_drain=2)
        ev = _event(EventType.channel_send)
        result = decide(ev, state, policy)
        assert result.action == Action.noop


# ===========================================================================
# ValueError for unknown event_type
# ===========================================================================


class TestUnknownEventType:
    """decide() raises ValueError on unrecognised event_type (schema drift guard)."""

    def test_unknown_event_type_raises(self) -> None:
        # Construct an event with an invalid event_type by bypassing the enum.
        ev = Event(
            schema_version="1.0",
            event_type="unknown_future_type",  # type: ignore[arg-type]
            agent_id=_AGENT,
            timestamp=_TS,
        )
        state = _state()
        with pytest.raises(ValueError, match="Unrecognised event_type"):
            decide(ev, state, _DEFAULT_POLICY)
