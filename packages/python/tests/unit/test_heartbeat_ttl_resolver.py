# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ``_resolve_heartbeat_ttl`` in ``core.mcp_server.tools``.

Covers the precedence rules for the server-side default-TTL knob:
 1. Per-call ``ttl`` argument always wins.
 2. ``SOX_HEARTBEAT_TTL_DEFAULT`` env var fills in when ``ttl is None``.
 3. Garbage env var values are warned and ignored (return None ⇒ store default).
"""

from __future__ import annotations

import logging

import pytest

from sox_protocol.core.mcp_server.tools import _resolve_heartbeat_ttl


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure SOX_HEARTBEAT_TTL_DEFAULT is unset before each test."""
    monkeypatch.delenv("SOX_HEARTBEAT_TTL_DEFAULT", raising=False)


def test_per_call_ttl_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOX_HEARTBEAT_TTL_DEFAULT", "120")
    assert _resolve_heartbeat_ttl(45) == 45


def test_env_var_used_when_per_call_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOX_HEARTBEAT_TTL_DEFAULT", "120")
    assert _resolve_heartbeat_ttl(None) == 120


def test_no_per_call_no_env_returns_none() -> None:
    # Falls through to backing-store default (30s in the in-tree adapters).
    assert _resolve_heartbeat_ttl(None) is None


def test_empty_env_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOX_HEARTBEAT_TTL_DEFAULT", "")
    assert _resolve_heartbeat_ttl(None) is None


def test_whitespace_env_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOX_HEARTBEAT_TTL_DEFAULT", "   ")
    assert _resolve_heartbeat_ttl(None) is None


def test_non_integer_env_returns_none_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SOX_HEARTBEAT_TTL_DEFAULT", "not-a-number")
    with caplog.at_level(logging.WARNING, logger="sox_protocol.core.mcp_server.tools"):
        assert _resolve_heartbeat_ttl(None) is None
    assert any("not-a-number" in rec.message for rec in caplog.records)


def test_zero_env_returns_none_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SOX_HEARTBEAT_TTL_DEFAULT", "0")
    with caplog.at_level(logging.WARNING, logger="sox_protocol.core.mcp_server.tools"):
        assert _resolve_heartbeat_ttl(None) is None
    assert any("must be positive" in rec.message for rec in caplog.records)


def test_negative_env_returns_none_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SOX_HEARTBEAT_TTL_DEFAULT", "-5")
    with caplog.at_level(logging.WARNING, logger="sox_protocol.core.mcp_server.tools"):
        assert _resolve_heartbeat_ttl(None) is None
    assert any("must be positive" in rec.message for rec in caplog.records)


def test_per_call_zero_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ttl=0`` is an explicit per-call value; do NOT override with env."""
    monkeypatch.setenv("SOX_HEARTBEAT_TTL_DEFAULT", "120")
    # Per-call wins even at edge values — the validation of ttl=0 is the
    # backing-store's responsibility, not this resolver's.
    assert _resolve_heartbeat_ttl(0) == 0
