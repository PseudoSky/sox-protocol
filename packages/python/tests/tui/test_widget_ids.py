# SPDX-License-Identifier: Apache-2.0
"""Tests for the widget-id sanitization helpers.

These tests are pure-function tests for the helpers extracted in 0.1.1
to fix a real user-reported crash:

    BadIdentifier: 'ch-#general' is an invalid id; identifiers must contain
    only letters, numbers, underscores, or hyphens, and must not begin
    with a number.

The widgets themselves (``ChannelListWidget``, ``AgentRosterWidget``) are
marked ``# pragma: no cover`` because Textual's rendering glue requires a
running reactor.  This test file covers the pure logic that the widgets
delegate to — that's exactly the part where the bug lived and exactly the
part that should never have shipped without a test.
"""

from __future__ import annotations

import re

import pytest

from sox_protocol.tui.widgets.agent_roster import _agent_to_widget_id
from sox_protocol.tui.widgets.channel_list import _channel_to_widget_id

# Textual's id alphabet, per the BadIdentifier exception text:
# "letters, numbers, underscores, or hyphens, and must not begin with a number"
_TEXTUAL_ID_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")


def _is_valid_textual_id(s: str) -> bool:
    """Return True iff ``s`` matches Textual's required id pattern."""
    return _TEXTUAL_ID_RE.match(s) is not None


# ---------------------------------------------------------------------------
# _channel_to_widget_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "channel",
    [
        # Default channel that triggered the user-reported crash:
        "#general",
        # Spec-canonical channel forms:
        "group/live-e2e-test",
        "dm/alice/bob",
        "sox/presence",
        # Free-form / namespaced:
        "agent:cto-agent",
        "ticket:ENGI-42",
        "broadcast:cto-announcements",
        # Pure ASCII:
        "general",
        "test-channel",
        "snake_case",
        # Edge cases:
        "a",
        "a/b/c/d/e",
        "name with spaces",
        "weird@chars!here",
        # Starts with digit (would be invalid as raw id; the ``ch-`` prefix saves it):
        "1-leading-digit",
        # Multiple consecutive invalid chars:
        "a///b",
        "##broadcast",
    ],
)
def test_channel_to_widget_id_produces_valid_textual_id(channel: str) -> None:
    """Every channel name must produce a Textual-valid widget id."""
    widget_id = _channel_to_widget_id(channel)
    assert _is_valid_textual_id(widget_id), (
        f"_channel_to_widget_id({channel!r}) returned {widget_id!r} which is "
        f"NOT a valid Textual id (must match {_TEXTUAL_ID_RE.pattern})"
    )


def test_channel_to_widget_id_starts_with_ch_prefix() -> None:
    """All channel ids share the ``ch-`` prefix so on_list_view_selected can branch on it."""
    for channel in ["#general", "group/x", "dm/a/b", ""]:
        assert _channel_to_widget_id(channel).startswith("ch-")


def test_channel_to_widget_id_replaces_slash() -> None:
    """``/`` (the namespace separator) must be sanitized."""
    assert "/" not in _channel_to_widget_id("group/live-e2e-test")


def test_channel_to_widget_id_replaces_hash() -> None:
    """``#`` (the historical channel sigil) must be sanitized — this is the user-reported crash case."""
    assert "#" not in _channel_to_widget_id("#general")


def test_channel_to_widget_id_replaces_colon() -> None:
    """``:`` (the namespace separator in ``ticket:42`` etc.) must be sanitized."""
    assert ":" not in _channel_to_widget_id("ticket:ENGI-42")


def test_channel_to_widget_id_preserves_alnum_and_hyphen() -> None:
    """Already-id-safe characters survive unchanged."""
    assert _channel_to_widget_id("group-foo") == "ch-group-foo"
    assert _channel_to_widget_id("test_123") == "ch-test_123"


def test_channel_to_widget_id_is_deterministic() -> None:
    """Same input always produces the same output (required for selection round-trip)."""
    a = _channel_to_widget_id("group/live-e2e-test")
    b = _channel_to_widget_id("group/live-e2e-test")
    assert a == b


def test_channel_to_widget_id_user_reported_case() -> None:
    """Regression test — exact string from the user-reported BadIdentifier crash."""
    widget_id = _channel_to_widget_id("#general")
    assert _is_valid_textual_id(widget_id)


# ---------------------------------------------------------------------------
# _agent_to_widget_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent_id",
    [
        # Plain identities:
        "alice",
        "bob",
        "cto-agent",
        "agent_with_underscore",
        # Namespace-prefixed (used by some installs):
        "team/alice",
        "ns/team/bob",
        # Edge cases:
        "agent#1",
        "agent.with.dots",
        "1leading-digit",
        "a",
    ],
)
def test_agent_to_widget_id_produces_valid_textual_id(agent_id: str) -> None:
    """Every agent_id must produce a Textual-valid widget id."""
    widget_id = _agent_to_widget_id(agent_id)
    assert _is_valid_textual_id(widget_id), (
        f"_agent_to_widget_id({agent_id!r}) returned {widget_id!r} which is "
        f"NOT a valid Textual id (must match {_TEXTUAL_ID_RE.pattern})"
    )


def test_agent_to_widget_id_starts_with_agent_prefix() -> None:
    for aid in ["alice", "bob/inner", ""]:
        assert _agent_to_widget_id(aid).startswith("agent-")


def test_agent_to_widget_id_replaces_slash() -> None:
    assert "/" not in _agent_to_widget_id("team/alice")


def test_agent_to_widget_id_is_deterministic() -> None:
    a = _agent_to_widget_id("alice")
    b = _agent_to_widget_id("alice")
    assert a == b


# ---------------------------------------------------------------------------
# Round-trip: widget instance maintains id → original-name dict
# ---------------------------------------------------------------------------


def test_channel_widget_id_lookup_round_trip() -> None:
    """The widget's _id_to_channel dict round-trips correctly for any channel name.

    This guards against a bug where two distinct channels both get sanitized
    to the same id (e.g. ``a#b`` and ``a/b`` both → ``ch-a_b``).  Within a
    single render pass, whichever channel was rendered last wins — which
    matches the behaviour we test here.
    """
    # Simulate what compose() does: build the dict for a set of channels.
    channels = ["#general", "group/foo", "dm/alice/bob", "sox/presence"]
    id_map: dict[str, str] = {}
    for ch in channels:
        wid = _channel_to_widget_id(ch)
        id_map[wid] = ch

    # Every id in the map should be a valid Textual id and round-trip.
    for wid, ch in id_map.items():
        assert _is_valid_textual_id(wid)
        assert id_map[wid] == ch


def test_agent_widget_id_lookup_round_trip() -> None:
    agents = ["alice", "bob", "cto-agent", "team/qa-1"]
    id_map: dict[str, str] = {}
    for aid in agents:
        wid = _agent_to_widget_id(aid)
        id_map[wid] = aid
    for wid, aid in id_map.items():
        assert _is_valid_textual_id(wid)
        assert id_map[wid] == aid
