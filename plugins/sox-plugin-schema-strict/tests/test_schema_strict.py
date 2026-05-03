# SPDX-License-Identifier: Apache-2.0
"""Unit tests for SchemaStrictMiddleware.

Tests construct SchemaStrictMiddleware directly (no host required).
All schema loading uses the real spec/operations/ directory resolved via
explicit path (relative to this test file).

Test strategy
-------------
- Direct construction: ``SchemaStrictMiddleware(schemas_dir=<path>)``
- Valid input: assert call_next called with unchanged ctx, result returned.
- Invalid input: assert ShortCircuitResponse raised with correct error_code.
- Violations list shape: ``[{"field": str, "issue": str}, ...]``.
- One valid + one invalid per major operation: send, recv, subscribe,
  list_channels.
- No-schema-dir: warn and pass through (graceful degradation).
- Unknown operation: pass through without error.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sox_plugin_schema_strict.middleware import SchemaStrictMiddleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Locate spec/operations/ relative to this test file.
# tests/ -> sox-plugin-schema-strict/ -> plugins/ -> repo root
_REPO_ROOT = Path(__file__).parents[3]
_SCHEMAS_DIR = _REPO_ROOT / "spec" / "operations"


def _make_ctx(operation: str, input_data: Any) -> MagicMock:
    """Create a minimal MiddlewareContext-like mock.

    Args:
        operation: SOX operation name.
        input_data: The input body value.

    Returns:
        A MagicMock with .operation and .input attributes.
    """
    ctx = MagicMock()
    ctx.operation = operation
    ctx.input = input_data
    ctx.metadata = {}
    return ctx


def _run(coro: Any) -> Any:
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def mw() -> SchemaStrictMiddleware:
    """A fresh SchemaStrictMiddleware pointing at the real spec schemas."""
    return SchemaStrictMiddleware(schemas_dir=_SCHEMAS_DIR)


# ---------------------------------------------------------------------------
# Import ShortCircuitResponse from the host package (available at test time)
# ---------------------------------------------------------------------------

from sox_protocol.core.middleware.errors import ShortCircuitResponse  # noqa: E402


# ---------------------------------------------------------------------------
# Construction / schema resolution
# ---------------------------------------------------------------------------


class TestConstruction:
    """Construction and schema resolution."""

    def test_explicit_schemas_dir_stored(self) -> None:
        """schemas_dir is stored when provided explicitly."""
        instance = SchemaStrictMiddleware(schemas_dir=_SCHEMAS_DIR)
        assert instance._schemas_dir == _SCHEMAS_DIR

    def test_env_var_sets_schemas_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env-var SOX_PLUGIN_IO_SOX_SCHEMA_STRICT_SCHEMAS_DIR is respected."""
        monkeypatch.setenv(
            "SOX_PLUGIN_IO_SOX_SCHEMA_STRICT_SCHEMAS_DIR", str(_SCHEMAS_DIR)
        )
        instance = SchemaStrictMiddleware(schemas_dir=None)
        assert instance._schemas_dir == _SCHEMAS_DIR

    def test_env_var_missing_dir_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env-var pointing to a non-existent directory is ignored (falls through)."""
        monkeypatch.setenv(
            "SOX_PLUGIN_IO_SOX_SCHEMA_STRICT_SCHEMAS_DIR",
            str(tmp_path / "does_not_exist"),
        )
        # Should not raise; _schemas_dir falls back to CWD search or None.
        instance = SchemaStrictMiddleware(schemas_dir=None)
        assert instance._schemas_dir is None or isinstance(instance._schemas_dir, Path)

    def test_explicit_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit schemas_dir takes precedence over env-var."""
        monkeypatch.setenv(
            "SOX_PLUGIN_IO_SOX_SCHEMA_STRICT_SCHEMAS_DIR", "/nonexistent"
        )
        instance = SchemaStrictMiddleware(schemas_dir=_SCHEMAS_DIR)
        assert instance._schemas_dir == _SCHEMAS_DIR


# ---------------------------------------------------------------------------
# ClassVar attributes (Middleware Protocol conformance)
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """SchemaStrictMiddleware conforms to the Middleware Protocol."""

    def test_kind_is_transformer(self, mw: SchemaStrictMiddleware) -> None:
        assert mw.kind == "transformer"

    def test_name_is_schema_strict(self, mw: SchemaStrictMiddleware) -> None:
        assert mw.name == "schema_strict"

    def test_must_run_before_contains_store_dispatch(
        self, mw: SchemaStrictMiddleware
    ) -> None:
        assert "store_dispatch" in mw.must_run_before

    def test_must_run_after_is_empty(self, mw: SchemaStrictMiddleware) -> None:
        assert mw.must_run_after == ()

    def test_callable(self, mw: SchemaStrictMiddleware) -> None:
        assert callable(mw)


# ---------------------------------------------------------------------------
# send operation
# ---------------------------------------------------------------------------


class TestSendOperation:
    """send: valid + invalid inputs."""

    def test_valid_send_calls_next(self, mw: SchemaStrictMiddleware) -> None:
        """Valid send body passes through; call_next is called once."""
        ctx = _make_ctx("send", {"channel": "dm/alice", "body": {"text": "hello"}})
        call_next = AsyncMock(return_value={"status": "ok"})

        result = _run(mw(ctx, call_next))

        call_next.assert_awaited_once_with(ctx)
        assert result == {"status": "ok"}

    def test_invalid_send_raises_short_circuit(self, mw: SchemaStrictMiddleware) -> None:
        """Missing required field raises ShortCircuitResponse with validation_error."""
        ctx = _make_ctx("send", {})  # missing channel + text
        call_next = AsyncMock()

        with pytest.raises(ShortCircuitResponse) as exc_info:
            _run(mw(ctx, call_next))

        envelope = exc_info.value.response
        assert envelope["error_code"] == "validation_error"
        call_next.assert_not_awaited()

    def test_invalid_send_violations_shape(self, mw: SchemaStrictMiddleware) -> None:
        """Violations have field + issue keys."""
        ctx = _make_ctx("send", {})
        call_next = AsyncMock()

        with pytest.raises(ShortCircuitResponse) as exc_info:
            _run(mw(ctx, call_next))

        violations = exc_info.value.response["detail"]["violations"]  # type: ignore[index]
        assert isinstance(violations, list)
        assert len(violations) >= 1
        for v in violations:
            assert "field" in v
            assert "issue" in v

    def test_valid_send_result_returned_unchanged(
        self, mw: SchemaStrictMiddleware
    ) -> None:
        """The exact result from call_next is returned unchanged."""
        sentinel: dict[str, object] = {"status": "ok", "msg_id": "abc"}
        ctx = _make_ctx("send", {"channel": "general", "body": {"text": "hi"}})
        call_next = AsyncMock(return_value=sentinel)

        result = _run(mw(ctx, call_next))
        assert result is sentinel


# ---------------------------------------------------------------------------
# recv operation
# ---------------------------------------------------------------------------


class TestRecvOperation:
    """recv: valid + invalid inputs."""

    def test_valid_recv_calls_next(self, mw: SchemaStrictMiddleware) -> None:
        """Valid recv body (empty body drains all subscribed channels) passes through."""
        ctx = _make_ctx("recv", {"channels": ["dm/alice"]})
        call_next = AsyncMock(return_value={"messages": []})

        result = _run(mw(ctx, call_next))

        call_next.assert_awaited_once_with(ctx)
        assert result == {"messages": []}

    def test_invalid_recv_raises_short_circuit(self, mw: SchemaStrictMiddleware) -> None:
        """Out-of-range max_messages raises ShortCircuitResponse."""
        ctx = _make_ctx("recv", {"max_messages": 0})  # minimum:1
        call_next = AsyncMock()

        with pytest.raises(ShortCircuitResponse) as exc_info:
            _run(mw(ctx, call_next))

        assert exc_info.value.response["error_code"] == "validation_error"
        call_next.assert_not_awaited()

    def test_invalid_recv_message_contains_op_name(
        self, mw: SchemaStrictMiddleware
    ) -> None:
        """Error message includes the operation name."""
        ctx = _make_ctx("recv", {"max_messages": 0})
        call_next = AsyncMock()

        with pytest.raises(ShortCircuitResponse) as exc_info:
            _run(mw(ctx, call_next))

        assert "recv" in exc_info.value.response["message"]  # type: ignore[operator]


# ---------------------------------------------------------------------------
# subscribe operation
# ---------------------------------------------------------------------------


class TestSubscribeOperation:
    """subscribe: valid + invalid inputs."""

    def test_valid_subscribe_calls_next(self, mw: SchemaStrictMiddleware) -> None:
        """Valid subscribe body passes through."""
        ctx = _make_ctx("subscribe", {"pattern": "dm/alice"})
        call_next = AsyncMock(return_value={"subscribed": True})

        result = _run(mw(ctx, call_next))

        call_next.assert_awaited_once_with(ctx)
        assert result == {"subscribed": True}

    def test_invalid_subscribe_raises_short_circuit(
        self, mw: SchemaStrictMiddleware
    ) -> None:
        """Missing pattern raises ShortCircuitResponse."""
        ctx = _make_ctx("subscribe", {})
        call_next = AsyncMock()

        with pytest.raises(ShortCircuitResponse) as exc_info:
            _run(mw(ctx, call_next))

        assert exc_info.value.response["error_code"] == "validation_error"
        call_next.assert_not_awaited()

    def test_valid_subscribe_result_returned_unchanged(
        self, mw: SchemaStrictMiddleware
    ) -> None:
        """The exact result from call_next is returned unchanged."""
        sentinel: dict[str, object] = {"subscribed": True, "extra": 42}
        ctx = _make_ctx("subscribe", {"pattern": "general"})
        call_next = AsyncMock(return_value=sentinel)

        result = _run(mw(ctx, call_next))
        assert result is sentinel


# ---------------------------------------------------------------------------
# list_channels operation
# ---------------------------------------------------------------------------


class TestListChannelsOperation:
    """list_channels: valid + invalid inputs."""

    def test_valid_list_channels_calls_next(self, mw: SchemaStrictMiddleware) -> None:
        """Empty body is valid for list_channels (no required fields)."""
        ctx = _make_ctx("list_channels", {})
        call_next = AsyncMock(return_value={"channels": []})

        result = _run(mw(ctx, call_next))

        call_next.assert_awaited_once_with(ctx)
        assert result == {"channels": []}

    def test_invalid_list_channels_wrong_type(self, mw: SchemaStrictMiddleware) -> None:
        """Body that is not an object raises ShortCircuitResponse."""
        ctx = _make_ctx("list_channels", None)
        call_next = AsyncMock()

        with pytest.raises(ShortCircuitResponse) as exc_info:
            _run(mw(ctx, call_next))

        assert exc_info.value.response["error_code"] == "validation_error"
        call_next.assert_not_awaited()


# ---------------------------------------------------------------------------
# Unknown / no-schema scenarios
# ---------------------------------------------------------------------------


class TestNoSchemaScenarios:
    """Graceful degradation when schema is absent."""

    def test_unknown_operation_passes_through(self, mw: SchemaStrictMiddleware) -> None:
        """An operation with no schema file is passed through without error."""
        ctx = _make_ctx("nonexistent_op", {"anything": True})
        call_next = AsyncMock(return_value={"ok": True})

        result = _run(mw(ctx, call_next))

        call_next.assert_awaited_once_with(ctx)
        assert result == {"ok": True}

    def test_no_schemas_dir_passes_through(self) -> None:
        """When schemas_dir is unresolvable, all operations pass through."""
        instance = SchemaStrictMiddleware.__new__(SchemaStrictMiddleware)
        instance._schemas_dir = None
        instance._validators = {}

        ctx = _make_ctx("send", {})  # would normally fail validation
        call_next = AsyncMock(return_value={"status": "ok"})

        result = _run(instance(ctx, call_next))

        call_next.assert_awaited_once()
        assert result == {"status": "ok"}

    def test_known_op_no_schemas_dir_passes_through_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Known op with no schemas_dir logs a warning and passes through."""
        import logging

        instance = SchemaStrictMiddleware.__new__(SchemaStrictMiddleware)
        instance._schemas_dir = None
        instance._validators = {}

        ctx = _make_ctx("send", {})
        call_next = AsyncMock(return_value={"status": "ok"})

        with caplog.at_level(logging.WARNING, logger="sox_plugin_schema_strict.middleware"):
            result = _run(instance(ctx, call_next))

        assert result == {"status": "ok"}
        assert any("send" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Violation message content
# ---------------------------------------------------------------------------


class TestViolationContent:
    """Violation payload matches routes._validate_body contract."""

    def test_violation_issue_non_empty(self, mw: SchemaStrictMiddleware) -> None:
        """Violation issue string is non-empty."""
        ctx = _make_ctx("send", {"channel": 123})  # wrong type for channel
        call_next = AsyncMock()

        with pytest.raises(ShortCircuitResponse) as exc_info:
            _run(mw(ctx, call_next))

        violations = exc_info.value.response["detail"]["violations"]  # type: ignore[index]
        for v in violations:
            assert v["issue"]  # non-empty string

    def test_root_path_shown_as_root(self, mw: SchemaStrictMiddleware) -> None:
        """Top-level schema violation shows '<root>' as the field path."""
        ctx = _make_ctx("list_channels", None)
        call_next = AsyncMock()

        with pytest.raises(ShortCircuitResponse) as exc_info:
            _run(mw(ctx, call_next))

        violations = exc_info.value.response["detail"]["violations"]  # type: ignore[index]
        fields = [v["field"] for v in violations]
        assert any(f == "<root>" for f in fields)

    def test_envelope_has_message_field(self, mw: SchemaStrictMiddleware) -> None:
        """Sox-error envelope always has a message field."""
        ctx = _make_ctx("recv", {"max_messages": 0})
        call_next = AsyncMock()

        with pytest.raises(ShortCircuitResponse) as exc_info:
            _run(mw(ctx, call_next))

        assert "message" in exc_info.value.response
        assert exc_info.value.response["message"]  # non-empty


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


class TestFactory:
    """Factory function produces a valid SchemaStrictMiddleware."""

    def test_factory_returns_middleware(self) -> None:
        """factory() returns a SchemaStrictMiddleware instance."""
        from sox_plugin_schema_strict import factory

        instance = factory()
        assert isinstance(instance, SchemaStrictMiddleware)

    def test_factory_instances_independent(self) -> None:
        """Each factory() call returns a fresh instance."""
        from sox_plugin_schema_strict import factory

        a = factory()
        b = factory()
        assert a is not b
