# SPDX-License-Identifier: Apache-2.0
"""Tests for Pipeline-level pipeline_trace observability.

Validates the structured ``metadata["pipeline_trace"]`` array per analysis
§7.5 risk #7 and suggestions-v2.md §Q3 risk #7.  Emission is via the
Pipeline base; plugins do NOT opt-in individually.

Acceptance gates (per engagement prompt):
- Every plugin in DEFAULT_ORDER appears in the trace.
- ``verdict`` correctly reflects rejection (auth short-circuit → identity_failure).
- ``correlation_id`` is consistent across all entries within one dispatch.
- ``correlation_id`` is preserved if provided in input metadata, else generated.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.errors import ShortCircuitResponse
from sox_protocol.core.middleware.pipeline import Pipeline, _get_kind
from sox_protocol.core.middleware.plugins.auth import AuthMiddleware
from sox_protocol.core.middleware.plugins.store_dispatch import StoreDispatchMiddleware

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


class _PassthroughMiddleware:
    """Minimal middleware that always passes through."""

    def __init__(self, name: str, kind: str = "transformer") -> None:
        self.name = name
        self.kind = kind
        self.must_run_before: tuple[str, ...] = ()
        self.must_run_after: tuple[str, ...] = ()

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: Callable[[MiddlewareContext], Awaitable[dict[str, object]]],
    ) -> dict[str, object]:
        return await call_next(ctx)


class _RejectingMiddleware:
    """Middleware that short-circuits with a sox-error envelope."""

    def __init__(self, name: str, error_code: str = "validation_failed") -> None:
        self.name = name
        self.kind = "interceptor"
        self.must_run_before: tuple[str, ...] = ()
        self.must_run_after: tuple[str, ...] = ()
        self._error_code = error_code

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: Callable[[MiddlewareContext], Awaitable[dict[str, object]]],
    ) -> dict[str, object]:
        raise ShortCircuitResponse(
            {"error_code": self._error_code, "message": "rejected by test"}
        )


class _ErroringMiddleware:
    """Middleware that raises an unexpected exception."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.kind = "transformer"
        self.must_run_before: tuple[str, ...] = ()
        self.must_run_after: tuple[str, ...] = ()

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: Callable[[MiddlewareContext], Awaitable[dict[str, object]]],
    ) -> dict[str, object]:
        raise RuntimeError("unexpected middleware crash")


async def _simple_terminal(ctx: MiddlewareContext) -> dict[str, object]:
    return {"result": "ok"}


# ---------------------------------------------------------------------------
# _get_kind helper
# ---------------------------------------------------------------------------


def test_get_kind_returns_kind_attribute() -> None:
    """_get_kind returns the kind attribute when present."""
    mw = _PassthroughMiddleware("mw", kind="transformer")
    assert _get_kind(mw) == "transformer"  # type: ignore[arg-type]


def test_get_kind_falls_back_to_unknown() -> None:
    """_get_kind returns 'unknown' when kind attribute is absent."""

    class _NoKind:
        name = "no_kind"
        must_run_before: tuple[str, ...] = ()
        must_run_after: tuple[str, ...] = ()

        async def __call__(self, ctx: MiddlewareContext, call_next: object) -> dict[str, object]:
            return {}

    assert _get_kind(_NoKind()) == "unknown"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Trace structure — single middleware, success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trace_entry_shape_on_success() -> None:
    """A passing middleware produces a complete, correct trace entry."""
    mw = _PassthroughMiddleware("alpha", kind="transformer")
    pipeline = Pipeline([mw], _simple_terminal)

    result = await pipeline.dispatch("list_channels", {}, connection_id="c1")

    meta = result.get("metadata")
    assert isinstance(meta, dict), "response must have metadata dict"
    trace = meta.get("pipeline_trace")
    assert isinstance(trace, list)
    assert len(trace) == 1

    entry = trace[0]
    assert entry["plugin_id"] == "alpha"
    assert entry["kind"] == "transformer"
    assert entry["verdict"] == "passed"
    assert entry["error_code"] is None
    assert isinstance(entry["started_at"], float)
    assert isinstance(entry["finished_at"], float)
    assert entry["finished_at"] >= entry["started_at"]
    assert isinstance(entry["correlation_id"], str)
    assert len(entry["correlation_id"]) > 0


# ---------------------------------------------------------------------------
# Verdict mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verdict_rejected_on_short_circuit() -> None:
    """ShortCircuitResponse → verdict='rejected' with error_code populated."""
    mw = _RejectingMiddleware("gate", error_code="validation_failed")
    pipeline = Pipeline([mw], _simple_terminal)

    result = await pipeline.dispatch("send", {}, connection_id="c2")

    assert result.get("error_code") == "validation_failed"
    trace = result["metadata"]["pipeline_trace"]  # type: ignore[index]
    assert len(trace) == 1
    entry = trace[0]
    assert entry["verdict"] == "rejected"
    assert entry["error_code"] == "validation_failed"
    assert entry["finished_at"] >= entry["started_at"]


@pytest.mark.asyncio
async def test_verdict_errored_on_unhandled_exception() -> None:
    """Unhandled exception → verdict='errored'; pipeline returns internal_error."""
    mw = _ErroringMiddleware("crasher")
    pipeline = Pipeline([mw], _simple_terminal)

    result = await pipeline.dispatch("send", {}, connection_id="c3")

    assert result.get("error_code") == "internal_error"
    trace = result["metadata"]["pipeline_trace"]  # type: ignore[index]
    assert len(trace) == 1
    entry = trace[0]
    assert entry["verdict"] == "errored"
    assert entry["finished_at"] >= entry["started_at"]


@pytest.mark.asyncio
async def test_verdict_skipped_for_unreached_middlewares() -> None:
    """Middlewares after a short-circuit get verdict='skipped'."""
    rejecter = _RejectingMiddleware("gate")
    downstream1 = _PassthroughMiddleware("downstream1")
    downstream2 = _PassthroughMiddleware("downstream2")
    pipeline = Pipeline([rejecter, downstream1, downstream2], _simple_terminal)

    result = await pipeline.dispatch("send", {}, connection_id="c4")

    trace = result["metadata"]["pipeline_trace"]  # type: ignore[index]
    assert len(trace) == 3
    assert trace[0]["plugin_id"] == "gate"
    assert trace[0]["verdict"] == "rejected"
    assert trace[1]["plugin_id"] == "downstream1"
    assert trace[1]["verdict"] == "skipped"
    assert trace[1]["started_at"] == 0.0
    assert trace[1]["finished_at"] == 0.0
    assert trace[2]["plugin_id"] == "downstream2"
    assert trace[2]["verdict"] == "skipped"


# ---------------------------------------------------------------------------
# correlation_id consistency and preservation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correlation_id_consistent_across_all_entries() -> None:
    """All trace entries within one dispatch share the same correlation_id."""
    mw1 = _PassthroughMiddleware("a")
    mw2 = _PassthroughMiddleware("b")
    mw3 = _PassthroughMiddleware("c")
    pipeline = Pipeline([mw1, mw2, mw3], _simple_terminal)

    result = await pipeline.dispatch("list_channels", {}, connection_id="c5")

    trace = result["metadata"]["pipeline_trace"]  # type: ignore[index]
    assert len(trace) == 3
    cids = {e["correlation_id"] for e in trace}
    assert len(cids) == 1, f"Expected single correlation_id, got: {cids}"
    # Also verify the top-level correlation_id matches
    assert result["metadata"]["correlation_id"] == trace[0]["correlation_id"]  # type: ignore[index]


@pytest.mark.asyncio
async def test_correlation_id_generated_when_not_provided() -> None:
    """correlation_id is auto-generated (non-empty string) when not in metadata."""
    mw = _PassthroughMiddleware("mw")
    pipeline = Pipeline([mw], _simple_terminal)

    result = await pipeline.dispatch("list_channels", {}, connection_id="c6")

    cid = result["metadata"]["correlation_id"]  # type: ignore[index]
    assert isinstance(cid, str)
    assert len(cid) > 0


@pytest.mark.asyncio
async def test_correlation_id_preserved_from_input_metadata() -> None:
    """correlation_id is echoed from caller-supplied metadata if provided."""
    caller_cid = uuid.uuid4().hex
    mw = _PassthroughMiddleware("mw")
    pipeline = Pipeline([mw], _simple_terminal)

    result = await pipeline.dispatch(
        "list_channels",
        {},
        connection_id="c7",
        metadata={"correlation_id": caller_cid},
    )

    trace = result["metadata"]["pipeline_trace"]  # type: ignore[index]
    top_cid = result["metadata"]["correlation_id"]  # type: ignore[index]
    assert top_cid == caller_cid
    assert trace[0]["correlation_id"] == caller_cid


@pytest.mark.asyncio
async def test_correlation_id_preserved_across_skipped_entries() -> None:
    """Skipped entries still carry the dispatch's correlation_id."""
    caller_cid = uuid.uuid4().hex
    rejecter = _RejectingMiddleware("gate")
    skipped = _PassthroughMiddleware("skip_me")
    pipeline = Pipeline([rejecter, skipped], _simple_terminal)

    result = await pipeline.dispatch(
        "send",
        {},
        connection_id="c8",
        metadata={"correlation_id": caller_cid},
    )

    trace = result["metadata"]["pipeline_trace"]  # type: ignore[index]
    assert trace[0]["correlation_id"] == caller_cid
    assert trace[1]["correlation_id"] == caller_cid


# ---------------------------------------------------------------------------
# Default order coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_default_order_plugins_traced(
    verifier: object,
    stub_store: object,
) -> None:
    """Every plugin in DEFAULT_ORDER that IS present appears in pipeline_trace.

    We build a pipeline with only the two required plugins (auth + store_dispatch)
    and verify both appear in the trace.  Optional plugins (namespace_resolver,
    rate_limit, schema_validator, idempotency, audit_log) are absent from this
    test but would appear if registered.
    """
    from sox_protocol.core.identity.verifier import IdentityVerifier
    from sox_protocol.core.middleware.default_chain import build_default_pipeline
    from sox_protocol.core.ports.backing_store import BackingStore

    assert isinstance(verifier, IdentityVerifier)
    assert isinstance(stub_store, BackingStore)

    pipeline = build_default_pipeline(verifier=verifier, store=stub_store)

    # list_channels is non-enforced (no auth required) → auth passes through.
    result = await pipeline.dispatch("list_channels", {}, connection_id="c9")

    trace = result["metadata"]["pipeline_trace"]  # type: ignore[index]
    plugin_ids = [e["plugin_id"] for e in trace]

    # auth and store_dispatch are always registered in DEFAULT_ORDER.
    assert "auth" in plugin_ids
    assert "store_dispatch" in plugin_ids

    # auth passes (non-enforced op), store_dispatch passes → all "passed".
    for entry in trace:
        assert entry["verdict"] == "passed", (
            f"Expected 'passed' for {entry['plugin_id']}, got {entry['verdict']!r}"
        )


@pytest.mark.asyncio
async def test_auth_short_circuit_marks_store_dispatch_skipped(
    verifier: object,
    stub_store: object,
) -> None:
    """Auth rejection on enforced op → store_dispatch gets verdict='skipped'."""
    from sox_protocol.core.identity.verifier import IdentityVerifier
    from sox_protocol.core.middleware.default_chain import build_default_pipeline
    from sox_protocol.core.ports.backing_store import BackingStore

    assert isinstance(verifier, IdentityVerifier)
    assert isinstance(stub_store, BackingStore)

    pipeline = build_default_pipeline(verifier=verifier, store=stub_store)

    # recv is identity-enforced; no credential → identity_failure short-circuit.
    result = await pipeline.dispatch(
        "recv",
        {},
        connection_id="c10",
        # deliberately omit _connection_credential
    )

    assert result.get("error_code") == "identity_failure"
    trace = result["metadata"]["pipeline_trace"]  # type: ignore[index]

    trace_by_id = {e["plugin_id"]: e for e in trace}
    assert trace_by_id["auth"]["verdict"] == "rejected"
    assert trace_by_id["auth"]["error_code"] == "identity_failure"
    assert trace_by_id["store_dispatch"]["verdict"] == "skipped"

    # correlation_id must be consistent.
    cids = {e["correlation_id"] for e in trace}
    assert len(cids) == 1


# ---------------------------------------------------------------------------
# AuthMiddleware kind attribute
# ---------------------------------------------------------------------------


def test_auth_middleware_has_kind_auth() -> None:
    """AuthMiddleware exposes kind='auth' for pipeline_trace entries."""
    assert AuthMiddleware.kind == "auth"


def test_store_dispatch_has_kind_store() -> None:
    """StoreDispatchMiddleware exposes kind='store' for pipeline_trace entries."""
    assert StoreDispatchMiddleware.kind == "store"


# ---------------------------------------------------------------------------
# metadata injection — existing metadata is preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_metadata_preserved_in_response() -> None:
    """Pipeline injects pipeline_trace without clobbering other metadata keys."""

    async def _terminal_with_meta(ctx: MiddlewareContext) -> dict[str, object]:
        return {"result": "ok", "metadata": {"custom_key": "custom_value"}}

    mw = _PassthroughMiddleware("mw")
    pipeline = Pipeline([mw], _terminal_with_meta)

    result = await pipeline.dispatch("list_channels", {}, connection_id="c11")

    meta = result.get("metadata")
    assert isinstance(meta, dict)
    assert meta.get("custom_key") == "custom_value"
    assert "pipeline_trace" in meta
    assert "correlation_id" in meta
