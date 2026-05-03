# SPDX-License-Identifier: Apache-2.0
"""Tests for Pipeline ordering, short-circuit, response propagation, and error handling.

Spec reference: ``spec/ports/middleware.md §2, §5, §7, §9``
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.errors import ShortCircuitResponse
from sox_protocol.core.middleware.pipeline import Pipeline, PipelineBuilder
from sox_protocol.core.middleware.protocol import CallNext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_terminal(
    response: dict[str, object],
) -> Callable[[MiddlewareContext], Awaitable[dict[str, object]]]:
    async def _terminal(ctx: MiddlewareContext) -> dict[str, object]:
        return response

    return _terminal


class OrderRecorder:
    """Records call order for testing left-to-right / right-to-left flow."""

    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self.must_run_before: tuple[str, ...] = ()
        self.must_run_after: tuple[str, ...] = ()
        self._log = log

    async def __call__(self, ctx: MiddlewareContext, call_next: CallNext) -> dict[str, object]:
        self._log.append(f"{self.name}:before")
        response = await call_next(ctx)
        self._log.append(f"{self.name}:after")
        return response


class ShortCircuitMiddleware:
    """Raises ShortCircuitResponse on call."""

    def __init__(self, name: str, response: dict[str, object]) -> None:
        self.name = name
        self.must_run_before: tuple[str, ...] = ()
        self.must_run_after: tuple[str, ...] = ()
        self._response = response

    async def __call__(self, ctx: MiddlewareContext, call_next: CallNext) -> dict[str, object]:
        raise ShortCircuitResponse(self._response)


class RaisingMiddleware:
    """Raises a plain exception (not ShortCircuitResponse) on call."""

    def __init__(self, name: str, exc: Exception) -> None:
        self.name = name
        self.must_run_before: tuple[str, ...] = ()
        self.must_run_after: tuple[str, ...] = ()
        self._exc = exc

    async def __call__(self, ctx: MiddlewareContext, call_next: CallNext) -> dict[str, object]:
        raise self._exc


class MetaWriter:
    """Writes a key to ctx.metadata then forwards."""

    def __init__(self, name: str, key: str, value: str) -> None:
        self.name = name
        self.must_run_before: tuple[str, ...] = ()
        self.must_run_after: tuple[str, ...] = ()
        self._key = key
        self._value = value

    async def __call__(self, ctx: MiddlewareContext, call_next: CallNext) -> dict[str, object]:
        ctx.metadata[self._key] = self._value
        return await call_next(ctx)


class MetaReader:
    """Reads a key from ctx.metadata and puts it in response."""

    def __init__(self, name: str, key: str) -> None:
        self.name = name
        self.must_run_before: tuple[str, ...] = ()
        self.must_run_after: tuple[str, ...] = ()
        self._key = key

    async def __call__(self, ctx: MiddlewareContext, call_next: CallNext) -> dict[str, object]:
        val = ctx.metadata.get(self._key, "MISSING")
        resp = await call_next(ctx)
        resp["read_value"] = val
        return resp


# ---------------------------------------------------------------------------
# §2 Pipeline structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_flows_left_to_right() -> None:
    log: list[str] = []
    mw1 = OrderRecorder("mw1", log)
    mw2 = OrderRecorder("mw2", log)
    mw3 = OrderRecorder("mw3", log)
    pipeline = Pipeline([mw1, mw2, mw3], _make_terminal({"ok": True}))

    await pipeline.dispatch("send", {}, connection_id="c")

    assert log.index("mw1:before") < log.index("mw2:before") < log.index("mw3:before")


@pytest.mark.asyncio
async def test_response_flows_right_to_left() -> None:
    log: list[str] = []
    mw1 = OrderRecorder("mw1", log)
    mw2 = OrderRecorder("mw2", log)
    pipeline = Pipeline([mw1, mw2], _make_terminal({"ok": True}))

    await pipeline.dispatch("send", {}, connection_id="c")

    assert log.index("mw2:after") < log.index("mw1:after")


@pytest.mark.asyncio
async def test_short_circuit_skips_subsequent_middlewares() -> None:
    log: list[str] = []
    mw1 = OrderRecorder("mw1", log)
    mw2 = ShortCircuitMiddleware("mw2", {"error_code": "denied"})
    mw3 = OrderRecorder("mw3", log)

    reached_terminal = False

    async def _terminal(ctx: MiddlewareContext) -> dict[str, object]:
        nonlocal reached_terminal
        reached_terminal = True
        return {}

    pipeline = Pipeline([mw1, mw2, mw3], _terminal)
    result = await pipeline.dispatch("send", {}, connection_id="c")

    # pipeline_trace + correlation_id are injected by Pipeline; check the
    # error payload independently of the observability metadata.
    assert result.get("error_code") == "denied"
    assert "mw3:before" not in log
    assert not reached_terminal


@pytest.mark.asyncio
async def test_terminal_invoked_on_full_passthrough() -> None:
    terminal_called = False

    async def _terminal(ctx: MiddlewareContext) -> dict[str, object]:
        nonlocal terminal_called
        terminal_called = True
        return {"ok": True}

    log: list[str] = []
    pipeline = Pipeline([OrderRecorder("mw1", log)], _terminal)
    result = await pipeline.dispatch("send", {}, connection_id="c")

    assert terminal_called
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# §3 Context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_per_call() -> None:
    """Concurrent dispatches receive distinct MiddlewareContext objects."""
    seen_ids: list[str] = []

    class CtxCapture:
        name = "capture"
        must_run_before: tuple[str, ...] = ()
        must_run_after: tuple[str, ...] = ()

        async def __call__(self, ctx: MiddlewareContext, call_next: CallNext) -> dict[str, object]:
            seen_ids.append(ctx.correlation_id)
            return await call_next(ctx)

    pipeline = Pipeline([CtxCapture()], _make_terminal({"ok": True}))
    await asyncio.gather(
        pipeline.dispatch("send", {}, connection_id="c"),
        pipeline.dispatch("recv", {}, connection_id="c"),
    )

    assert len(seen_ids) == 2
    assert seen_ids[0] != seen_ids[1]


@pytest.mark.asyncio
async def test_metadata_is_mutable_for_inter_mw_communication() -> None:
    mw1 = MetaWriter("writer", "shared_key", "hello")
    mw2 = MetaReader("reader", "shared_key")
    pipeline = Pipeline([mw1, mw2], _make_terminal({}))

    result = await pipeline.dispatch("send", {}, connection_id="c")

    assert result["read_value"] == "hello"


# ---------------------------------------------------------------------------
# §7 Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uncaught_exception_becomes_internal_error() -> None:
    mw = RaisingMiddleware("raiser", RuntimeError("boom"))
    pipeline = Pipeline([mw], _make_terminal({"ok": True}))

    result = await pipeline.dispatch("send", {}, connection_id="c")

    assert result["error_code"] == "internal_error"


@pytest.mark.asyncio
async def test_internal_error_does_not_leak_traceback() -> None:
    mw = RaisingMiddleware("raiser", RuntimeError("secret internal path"))
    pipeline = Pipeline([mw], _make_terminal({}))

    result = await pipeline.dispatch("send", {}, connection_id="c")

    message = str(result.get("message", ""))
    assert "secret internal path" not in message
    assert "Traceback" not in message


# ---------------------------------------------------------------------------
# §5 Short-circuit response shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_circuit_response_returned_directly() -> None:
    short: dict[str, object] = {
        "error_code": "identity_failure", "message": "nope",
        "detail": None, "retry_after": None,
    }
    mw = ShortCircuitMiddleware("auth", short)
    pipeline = Pipeline([mw], _make_terminal({}))

    result = await pipeline.dispatch("send", {}, connection_id="c")

    # Pipeline injects metadata; verify the sox-error payload keys individually.
    assert result.get("error_code") == short["error_code"]
    assert result.get("message") == short["message"]


# ---------------------------------------------------------------------------
# §9 Reentrancy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_is_reentrant() -> None:
    """50 concurrent dispatches do not bleed context."""
    seen: list[str] = []

    class CaptureCtx:
        name = "capture"
        must_run_before: tuple[str, ...] = ()
        must_run_after: tuple[str, ...] = ()

        async def __call__(self, ctx: MiddlewareContext, call_next: CallNext) -> dict[str, object]:
            seen.append(ctx.correlation_id)
            return await call_next(ctx)

    pipeline = Pipeline([CaptureCtx()], _make_terminal({"ok": True}))
    await asyncio.gather(*[pipeline.dispatch("send", {}, connection_id="c") for _ in range(50)])

    assert len(seen) == 50
    assert len(set(seen)) == 50, "correlation_ids must be unique per call"


@pytest.mark.asyncio
async def test_chain_order_documented_on_pipeline_order_attribute() -> None:
    log: list[str] = []
    mw1 = OrderRecorder("mw1", log)
    mw2 = OrderRecorder("mw2", log)
    pipeline = PipelineBuilder().add(mw1).add(mw2).build(_make_terminal({}))

    assert pipeline.order == ("mw1", "mw2")
