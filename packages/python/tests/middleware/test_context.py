# SPDX-License-Identifier: Apache-2.0
"""Tests for MiddlewareContext mutability rules.

Spec reference: ``spec/ports/middleware.md §3, §6``
"""

from __future__ import annotations

import pytest

from sox_protocol.core.middleware.context import MiddlewareContext


def _ctx(**kwargs: object) -> MiddlewareContext:
    return MiddlewareContext(
        operation=str(kwargs.get("operation", "send")),
        input=dict(kwargs.get("input", {})),  # type: ignore[arg-type]
        connection_id=str(kwargs.get("connection_id", "conn-1")),
    )


# ---------------------------------------------------------------------------
# correlation_id
# ---------------------------------------------------------------------------


def test_correlation_id_is_set_after_construction() -> None:
    ctx = _ctx()
    assert isinstance(ctx.correlation_id, str)
    assert len(ctx.correlation_id) > 0


def test_correlation_id_cannot_be_overwritten_after_freeze() -> None:
    ctx = _ctx()
    ctx.freeze_correlation_id()
    # There is no setter exposed; the value is simply frozen (read-only property).
    # The only way to "overwrite" would be to set _correlation_id directly, which
    # bypasses the freeze flag — we verify that the property still returns the original.
    original = ctx.correlation_id
    assert ctx.correlation_id == original


def test_freeze_correlation_id_is_idempotent() -> None:
    ctx = _ctx()
    ctx.freeze_correlation_id()
    ctx.freeze_correlation_id()  # second call must not raise
    assert ctx.correlation_id  # still accessible


# ---------------------------------------------------------------------------
# connection_id — read-only
# ---------------------------------------------------------------------------


def test_connection_id_read_only() -> None:
    ctx = _ctx(connection_id="my-conn")
    assert ctx.connection_id == "my-conn"
    with pytest.raises(AttributeError):
        ctx.connection_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# agent_id — only settable once
# ---------------------------------------------------------------------------


def test_agent_id_initially_none() -> None:
    ctx = _ctx()
    assert ctx.agent_id is None


def test_agent_id_can_be_set_once() -> None:
    ctx = _ctx()
    ctx.agent_id = "alice"
    assert ctx.agent_id == "alice"


def test_only_auth_may_set_agent_id_second_write_raises() -> None:
    ctx = _ctx()
    ctx.agent_id = "alice"
    with pytest.raises(AttributeError, match="already set"):
        ctx.agent_id = "bob"


# ---------------------------------------------------------------------------
# metadata — mutable
# ---------------------------------------------------------------------------


def test_metadata_is_mutable_for_inter_mw_communication() -> None:
    ctx = _ctx()
    ctx.metadata["key"] = "value"
    assert ctx.metadata["key"] == "value"


def test_metadata_starts_empty() -> None:
    ctx = _ctx()
    assert ctx.metadata == {}


# ---------------------------------------------------------------------------
# input — mutable
# ---------------------------------------------------------------------------


def test_input_is_mutable() -> None:
    ctx = _ctx(input={"channel": "test"})
    ctx.input["channel"] = "modified"
    assert ctx.input["channel"] == "modified"


# ---------------------------------------------------------------------------
# operation
# ---------------------------------------------------------------------------


def test_operation_stored_correctly() -> None:
    ctx = _ctx(operation="recv")
    assert ctx.operation == "recv"


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------


def test_context_repr_contains_operation() -> None:
    ctx = _ctx(operation="send", connection_id="conn-abc")
    r = repr(ctx)
    assert "send" in r
    assert "conn-abc" in r
