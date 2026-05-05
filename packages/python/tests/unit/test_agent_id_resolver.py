# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ``_resolve_agent_id_from_env`` in ``core.mcp_server.server``.

Covers the four recognized ``SOX_AGENT_ID_SOURCE`` modes:
 1. ``"claude_code_agent_name"`` → CLAUDE_AGENT_NAME
 2. ``"env:VARNAME"``            → arbitrary env var
 3. ``""`` / unset                → historical SOX_AGENT_ID then CLAUDE_AGENT_NAME
 4. Fall-throughs and defaults
"""

from __future__ import annotations

from sox_protocol.core.mcp_server.server import _resolve_agent_id_from_env


# ---------------------------------------------------------------------------
# Mode: claude_code_agent_name
# ---------------------------------------------------------------------------


def test_claude_code_agent_name_picks_up_claude_var() -> None:
    env = {
        "SOX_AGENT_ID_SOURCE": "claude_code_agent_name",
        "CLAUDE_AGENT_NAME": "researcher",
    }
    assert _resolve_agent_id_from_env(env) == "researcher"


def test_claude_code_agent_name_falls_back_to_sox_agent_id() -> None:
    env = {
        "SOX_AGENT_ID_SOURCE": "claude_code_agent_name",
        "CLAUDE_AGENT_NAME": "",
        "SOX_AGENT_ID": "fallback-id",
    }
    assert _resolve_agent_id_from_env(env) == "fallback-id"


def test_claude_code_agent_name_default_when_all_empty() -> None:
    env = {"SOX_AGENT_ID_SOURCE": "claude_code_agent_name"}
    assert _resolve_agent_id_from_env(env) == "default"


# ---------------------------------------------------------------------------
# Mode: env:VARNAME
# ---------------------------------------------------------------------------


def test_env_source_reads_arbitrary_var() -> None:
    env = {
        "SOX_AGENT_ID_SOURCE": "env:SOX_AGENT_NAME",
        "SOX_AGENT_NAME": "alice",
    }
    assert _resolve_agent_id_from_env(env) == "alice"


def test_env_source_with_unusual_var_name() -> None:
    """Any env var name should work — not just SOX_AGENT_NAME."""
    env = {
        "SOX_AGENT_ID_SOURCE": "env:MY_HOST_AGENT_ID",
        "MY_HOST_AGENT_ID": "bob-from-host",
    }
    assert _resolve_agent_id_from_env(env) == "bob-from-host"


def test_env_source_falls_back_when_target_var_unset() -> None:
    env = {
        "SOX_AGENT_ID_SOURCE": "env:SOX_AGENT_NAME",
        "SOX_AGENT_ID": "fallback",
    }
    assert _resolve_agent_id_from_env(env) == "fallback"


def test_env_source_falls_back_through_claude_var() -> None:
    env = {
        "SOX_AGENT_ID_SOURCE": "env:SOX_AGENT_NAME",
        "CLAUDE_AGENT_NAME": "claude-fallback",
    }
    assert _resolve_agent_id_from_env(env) == "claude-fallback"


def test_env_source_default_when_nothing_set() -> None:
    env = {"SOX_AGENT_ID_SOURCE": "env:SOX_AGENT_NAME"}
    assert _resolve_agent_id_from_env(env) == "default"


def test_env_source_with_empty_varname_falls_through() -> None:
    """``env:`` with no name after the colon must not match an empty string."""
    env = {
        "SOX_AGENT_ID_SOURCE": "env:",
        "SOX_AGENT_ID": "via-fallback",
    }
    assert _resolve_agent_id_from_env(env) == "via-fallback"


def test_env_source_strips_whitespace_in_var_name() -> None:
    env = {
        "SOX_AGENT_ID_SOURCE": "env:  SOX_AGENT_NAME  ",
        "SOX_AGENT_NAME": "trimmed",
    }
    assert _resolve_agent_id_from_env(env) == "trimmed"


def test_env_source_per_call_value_takes_precedence_over_other_vars() -> None:
    """When env:VARNAME has a value, fallbacks are not consulted."""
    env = {
        "SOX_AGENT_ID_SOURCE": "env:SOX_AGENT_NAME",
        "SOX_AGENT_NAME": "primary",
        "SOX_AGENT_ID": "should-not-be-used",
        "CLAUDE_AGENT_NAME": "neither-this",
    }
    assert _resolve_agent_id_from_env(env) == "primary"


# ---------------------------------------------------------------------------
# Mode: unset / empty (historical default)
# ---------------------------------------------------------------------------


def test_unset_source_prefers_sox_agent_id() -> None:
    env = {
        "SOX_AGENT_ID": "primary",
        "CLAUDE_AGENT_NAME": "secondary",
    }
    assert _resolve_agent_id_from_env(env) == "primary"


def test_unset_source_falls_back_to_claude_agent_name() -> None:
    env = {"CLAUDE_AGENT_NAME": "from-claude"}
    assert _resolve_agent_id_from_env(env) == "from-claude"


def test_unset_source_returns_default_when_nothing_set() -> None:
    assert _resolve_agent_id_from_env({}) == "default"


def test_empty_source_string_treated_same_as_unset() -> None:
    env = {
        "SOX_AGENT_ID_SOURCE": "",
        "SOX_AGENT_ID": "some-id",
    }
    assert _resolve_agent_id_from_env(env) == "some-id"


def test_whitespace_only_source_treated_same_as_unset() -> None:
    env = {
        "SOX_AGENT_ID_SOURCE": "   ",
        "SOX_AGENT_ID": "some-id",
    }
    assert _resolve_agent_id_from_env(env) == "some-id"


# ---------------------------------------------------------------------------
# Whitespace / strip behavior
# ---------------------------------------------------------------------------


def test_resolved_value_is_stripped() -> None:
    env = {
        "SOX_AGENT_ID_SOURCE": "env:SOX_AGENT_NAME",
        "SOX_AGENT_NAME": "  spaced-out  ",
    }
    assert _resolve_agent_id_from_env(env) == "spaced-out"
