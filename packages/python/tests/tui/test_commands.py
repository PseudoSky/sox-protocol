# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ``sox_protocol.tui.commands``.

100% branch coverage on ``commands.py``.

Test matrix:
- plain text → SendCommand
- /reply with id and text → ReplyCommand
- /dm with target → DmCommand (sorted pair)
- /join with channel → JoinCommand
- /quit → QuitCommand
- malformed: empty text, /reply missing args, /dm missing args,
  /join missing channel, unknown verb
- dm_channel sorting
- parse() case-insensitive verbs
"""

from __future__ import annotations

import pytest

from sox_protocol.tui.commands import (
    CommandParseError,
    DmCommand,
    JoinCommand,
    QuitCommand,
    ReplyCommand,
    SendCommand,
    dm_channel,
    parse,
)

# ---------------------------------------------------------------------------
# dm_channel helper
# ---------------------------------------------------------------------------


def test_dm_channel_sorts_alphabetically() -> None:
    assert dm_channel("beta", "alpha") == "dm/alpha+beta"


def test_dm_channel_already_sorted() -> None:
    assert dm_channel("alpha", "beta") == "dm/alpha+beta"


def test_dm_channel_same_prefix() -> None:
    assert dm_channel("agent-b", "agent-a") == "dm/agent-a+agent-b"


def test_dm_channel_identical() -> None:
    # Edge case: same agent each side — sorts to same
    assert dm_channel("x", "x") == "dm/x+x"


# ---------------------------------------------------------------------------
# SendCommand
# ---------------------------------------------------------------------------


def test_parse_plain_text_returns_send() -> None:
    cmd = parse("hello world")
    assert isinstance(cmd, SendCommand)
    assert cmd.text == "hello world"


def test_parse_plain_text_strips_whitespace() -> None:
    cmd = parse("  padded  ")
    assert isinstance(cmd, SendCommand)
    assert cmd.text == "padded"


def test_parse_empty_raises() -> None:
    with pytest.raises(CommandParseError) as exc_info:
        parse("   ")
    assert exc_info.value.reason == "empty message"


def test_parse_empty_string_raises() -> None:
    with pytest.raises(CommandParseError):
        parse("")


# ---------------------------------------------------------------------------
# QuitCommand
# ---------------------------------------------------------------------------


def test_parse_quit() -> None:
    cmd = parse("/quit")
    assert isinstance(cmd, QuitCommand)


def test_parse_quit_uppercase() -> None:
    cmd = parse("/QUIT")
    assert isinstance(cmd, QuitCommand)


def test_parse_quit_mixed_case() -> None:
    cmd = parse("/Quit")
    assert isinstance(cmd, QuitCommand)


# ---------------------------------------------------------------------------
# JoinCommand
# ---------------------------------------------------------------------------


def test_parse_join() -> None:
    cmd = parse("/join #general")
    assert isinstance(cmd, JoinCommand)
    assert cmd.channel == "#general"


def test_parse_join_no_channel_raises() -> None:
    with pytest.raises(CommandParseError) as exc_info:
        parse("/join")
    assert "/join requires a channel name" in exc_info.value.reason


def test_parse_join_uppercase_verb() -> None:
    cmd = parse("/JOIN engineering")
    assert isinstance(cmd, JoinCommand)
    assert cmd.channel == "engineering"


# ---------------------------------------------------------------------------
# DmCommand
# ---------------------------------------------------------------------------


def test_parse_dm_produces_sorted_channel() -> None:
    cmd = parse("/dm beta", self_agent="alpha")
    assert isinstance(cmd, DmCommand)
    assert cmd.channel == "dm/alpha+beta"
    assert cmd.target_agent == "beta"
    assert cmd.self_agent == "alpha"


def test_parse_dm_self_agent_default() -> None:
    cmd = parse("/dm other")
    assert isinstance(cmd, DmCommand)
    assert cmd.self_agent == "tui-user"


def test_parse_dm_no_agent_raises() -> None:
    with pytest.raises(CommandParseError) as exc_info:
        parse("/dm")
    assert "/dm requires an agent_id" in exc_info.value.reason


def test_parse_dm_uppercase_verb() -> None:
    cmd = parse("/DM target", self_agent="me")
    assert isinstance(cmd, DmCommand)
    assert cmd.target_agent == "target"


# ---------------------------------------------------------------------------
# ReplyCommand
# ---------------------------------------------------------------------------


def test_parse_reply_basic() -> None:
    cmd = parse("/reply msg-123 sounds good to me")
    assert isinstance(cmd, ReplyCommand)
    assert cmd.reply_to == "msg-123"
    assert cmd.text == "sounds good to me"


def test_parse_reply_single_word_text() -> None:
    cmd = parse("/reply abc ok")
    assert isinstance(cmd, ReplyCommand)
    assert cmd.text == "ok"


def test_parse_reply_missing_text_raises() -> None:
    with pytest.raises(CommandParseError) as exc_info:
        parse("/reply msg-1")
    assert "/reply requires a message_id and reply text" in exc_info.value.reason


def test_parse_reply_missing_args_raises() -> None:
    with pytest.raises(CommandParseError) as exc_info:
        parse("/reply")
    assert "/reply requires a message_id and reply text" in exc_info.value.reason


def test_parse_reply_uppercase() -> None:
    cmd = parse("/REPLY id-1 hello")
    assert isinstance(cmd, ReplyCommand)
    assert cmd.reply_to == "id-1"


# ---------------------------------------------------------------------------
# Unknown verb
# ---------------------------------------------------------------------------


def test_parse_unknown_verb_raises() -> None:
    with pytest.raises(CommandParseError) as exc_info:
        parse("/unknown something")
    assert "unknown command verb" in exc_info.value.reason


def test_parse_error_contains_raw() -> None:
    try:
        parse("/bogus")
    except CommandParseError as exc:
        assert exc.raw == "/bogus"
        assert "bogus" in exc.reason


def test_parse_error_str_repr() -> None:
    exc = CommandParseError("/bad", "test reason")
    assert "/bad" in str(exc)
    assert "test reason" in str(exc)
