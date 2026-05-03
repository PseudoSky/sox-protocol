# SPDX-License-Identifier: Apache-2.0
"""Tests for AuthMiddleware plugin.

Spec reference: ``spec/ports/middleware.md §4``; ``spec/ports/identity.md §2``
"""

from __future__ import annotations

import pytest

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.pipeline import Pipeline
from sox_protocol.core.middleware.plugins.auth import AuthMiddleware, build_auth_middleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _passthrough(ctx: MiddlewareContext) -> dict[str, object]:
    return {"ok": True, "agent_id": ctx.agent_id}


# ---------------------------------------------------------------------------
# Auth populates ctx.agent_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_populates_agent_id(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    private_seed, public_key = sample_keypair
    await registry.register("alice", public_key)

    req = sign_request(agent_id="alice", method="recv")
    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _passthrough)

    result = await pipeline.dispatch(
        "recv",
        {"signed_request": req},
        connection_id="conn-1",
    )

    assert result["agent_id"] == "alice"


# ---------------------------------------------------------------------------
# bind_for_send overwrites sender
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bind_for_send_overwrites_sender(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    private_seed, public_key = sample_keypair
    await registry.register("alice", public_key)

    req = sign_request(agent_id="alice", method="send")

    captured_sender: list[str] = []

    async def _capture_sender(ctx: MiddlewareContext) -> dict[str, object]:
        captured_sender.append(str(ctx.input.get("sender", "")))
        return {"ok": True}

    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _capture_sender)

    await pipeline.dispatch(
        "send",
        {"signed_request": req, "channel": "test", "sender": "FORGED", "body": {}},
        connection_id="conn-1",
    )

    assert captured_sender == ["alice"]


# ---------------------------------------------------------------------------
# IdentityFailure short-circuits with identity_failure error code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_failure_converts_to_short_circuit(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    # Do NOT register the agent — should trigger UnknownAgentError.
    req = sign_request(agent_id="unknown_agent", method="send")
    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _passthrough)

    result = await pipeline.dispatch(
        "send",
        {"signed_request": req, "channel": "test", "body": {}},
        connection_id="conn-1",
    )

    assert result["error_code"] == "identity_failure"


# ---------------------------------------------------------------------------
# Missing signed_request short-circuits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_signed_request_short_circuits(verifier) -> None:
    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _passthrough)

    result = await pipeline.dispatch(
        "send",
        {"channel": "test", "body": {}},  # no signed_request
        connection_id="conn-1",
    )

    assert result["error_code"] == "identity_failure"


# ---------------------------------------------------------------------------
# Non-enforced operation passes through without credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_enforced_operation_passes_through(verifier) -> None:
    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _passthrough)

    result = await pipeline.dispatch(
        "list_channels",
        {},
        connection_id="conn-1",
    )

    # Should not short-circuit — passthrough returns {"ok": True, "agent_id": None}
    assert result.get("ok") is True


# ---------------------------------------------------------------------------
# factory function
# ---------------------------------------------------------------------------


def test_build_auth_middleware_factory(verifier) -> None:
    mw = build_auth_middleware(verifier)
    assert isinstance(mw, AuthMiddleware)
    assert mw.name == "auth"


# ---------------------------------------------------------------------------
# Ordering constraints
# ---------------------------------------------------------------------------


def test_auth_must_run_after_namespace_resolver(verifier) -> None:
    auth = AuthMiddleware(verifier)
    assert "namespace_resolver" in auth.must_run_after


def test_auth_must_run_before_store_dispatch(verifier) -> None:
    auth = AuthMiddleware(verifier)
    assert "store_dispatch" in auth.must_run_before


# ---------------------------------------------------------------------------
# Deliverable 1 — list_agents is in enforced operations (spec 9f3e11e)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_agents_unauthenticated_returns_identity_failure(verifier) -> None:
    """Unauthenticated list_agents returns identity_failure sox-error (spec §4)."""
    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _passthrough)

    result = await pipeline.dispatch(
        "list_agents",
        {},  # no credential in input or connection seam
        connection_id="conn-1",
    )

    assert result["error_code"] == "identity_failure"


@pytest.mark.asyncio
async def test_list_agents_authenticated_passes_through(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    """Authenticated list_agents reaches call_next with agent_id set."""
    private_seed, public_key = sample_keypair
    await registry.register("alice", public_key)

    req = sign_request(agent_id="alice", method="list_agents")
    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _passthrough)

    result = await pipeline.dispatch(
        "list_agents",
        {},
        connection_id="conn-1",
        metadata={"_connection_credential": req},
    )

    assert result.get("ok") is True
    assert result.get("agent_id") == "alice"


# ---------------------------------------------------------------------------
# Deliverable 2 — origin_server surfaced through VerifiedIdentity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verified_identity_has_origin_server_none(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    """VerifiedIdentity.origin_server is None in v1.0 (spec §7)."""
    private_seed, public_key = sample_keypair
    await registry.register("alice", public_key)

    req = sign_request(agent_id="alice", method="recv")
    identity = await verifier.verify(req, operation="recv")

    assert identity.origin_server is None


@pytest.mark.asyncio
async def test_bind_for_send_injects_origin_server_null(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    """bind_for_send injects origin_server: None into the outbound envelope (spec §7)."""
    private_seed, public_key = sample_keypair
    await registry.register("alice", public_key)

    req = sign_request(agent_id="alice", method="send")
    result = await verifier.bind_for_send(req, {"channel": "test", "body": {}})

    assert "origin_server" in result
    assert result["origin_server"] is None


@pytest.mark.asyncio
async def test_auth_middleware_send_envelope_has_origin_server(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    """AuthMiddleware on send: ctx.input has origin_server: None after bind_for_send."""
    private_seed, public_key = sample_keypair
    await registry.register("alice", public_key)

    req = sign_request(agent_id="alice", method="send")

    captured: list[dict[str, object]] = []

    async def _capture(ctx: MiddlewareContext) -> dict[str, object]:
        captured.append(dict(ctx.input))
        return {"ok": True}

    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _capture)

    await pipeline.dispatch(
        "send",
        {"channel": "test", "body": {}},
        connection_id="conn-1",
        metadata={"_connection_credential": req},
    )

    assert captured, "call_next was not reached"
    assert captured[0].get("origin_server") is None


# ---------------------------------------------------------------------------
# Deliverable 3 — credential from connection seam, not tool-call dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_from_connection_seam(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    """Credential in ctx.metadata['_connection_credential'] is accepted without warning."""
    private_seed, public_key = sample_keypair
    await registry.register("alice", public_key)

    req = sign_request(agent_id="alice", method="recv")
    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _passthrough)

    # Deliver credential via connection metadata (the canonical seam).
    result = await pipeline.dispatch(
        "recv",
        {},
        connection_id="conn-1",
        metadata={"_connection_credential": req},
    )

    assert result.get("agent_id") == "alice"


@pytest.mark.asyncio
async def test_credential_from_input_dict_deprecated_fallback(
    verifier,
    registry,
    sample_keypair,
    sign_request,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Credential in ctx.input['signed_request'] still works but logs deprecation warning."""
    import logging

    private_seed, public_key = sample_keypair
    await registry.register("alice", public_key)

    req = sign_request(agent_id="alice", method="recv")
    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _passthrough)

    with caplog.at_level(logging.WARNING, logger="sox_protocol.core.middleware.plugins.auth"):
        result = await pipeline.dispatch(
            "recv",
            {"signed_request": req},
            connection_id="conn-1",
        )

    assert result.get("agent_id") == "alice"
    assert any("deprecated" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_signed_request_stripped_from_input_after_fallback(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    """When fallback path used, signed_request is stripped from ctx.input before call_next."""
    private_seed, public_key = sample_keypair
    await registry.register("alice", public_key)

    req = sign_request(agent_id="alice", method="recv")

    captured_keys: list[list[str]] = []

    async def _capture_keys(ctx: MiddlewareContext) -> dict[str, object]:
        captured_keys.append(list(ctx.input.keys()))
        return {"ok": True, "agent_id": ctx.agent_id}

    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _capture_keys)

    await pipeline.dispatch(
        "recv",
        {"signed_request": req},
        connection_id="conn-1",
    )

    assert captured_keys, "call_next was not reached"
    assert "signed_request" not in captured_keys[0]


# ---------------------------------------------------------------------------
# Deliverable 4 — pipeline_trace emitted by Pipeline (replaces middleware_timings)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_trace_emitted_on_success(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    """Pipeline emits a pipeline_trace entry with verdict='passed' on auth success."""
    private_seed, public_key = sample_keypair
    await registry.register("alice", public_key)

    req = sign_request(agent_id="alice", method="recv")

    async def _terminal(ctx: MiddlewareContext) -> dict[str, object]:
        return {"ok": True, "agent_id": ctx.agent_id}

    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _terminal)

    result = await pipeline.dispatch(
        "recv",
        {},
        connection_id="conn-1",
        metadata={"_connection_credential": req},
    )

    trace = result.get("metadata", {}).get("pipeline_trace", [])  # type: ignore[union-attr]
    assert isinstance(trace, list)
    assert len(trace) == 1
    entry = trace[0]
    assert isinstance(entry, dict)
    assert entry["plugin_id"] == "auth"
    assert entry["kind"] == "auth"
    assert entry["verdict"] == "passed"
    assert entry["error_code"] is None
    assert isinstance(entry["started_at"], float)
    assert isinstance(entry["finished_at"], float)
    assert entry["finished_at"] >= entry["started_at"]
    assert isinstance(entry["correlation_id"], str)
    assert len(entry["correlation_id"]) > 0


@pytest.mark.asyncio
async def test_pipeline_trace_emitted_on_reject_missing_credential(verifier) -> None:
    """Pipeline emits verdict='rejected' when auth short-circuits for missing credential."""

    async def _terminal(ctx: MiddlewareContext) -> dict[str, object]:  # pragma: no cover
        raise AssertionError("should not reach terminal")

    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _terminal)

    result = await pipeline.dispatch(
        "recv",
        {},
        connection_id="conn-1",
        # No _connection_credential → auth rejects.
    )

    assert result.get("error_code") == "identity_failure"
    trace = result.get("metadata", {}).get("pipeline_trace", [])  # type: ignore[union-attr]
    assert isinstance(trace, list)
    assert len(trace) == 1
    entry = trace[0]
    assert entry["plugin_id"] == "auth"
    assert entry["verdict"] == "rejected"
    assert entry["error_code"] == "identity_failure"
    assert isinstance(entry["started_at"], float)
    assert entry["finished_at"] >= entry["started_at"]


@pytest.mark.asyncio
async def test_pipeline_trace_emitted_on_identity_failure(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    """Pipeline emits verdict='rejected' when IdentityFailure is raised (unknown agent)."""
    private_seed, public_key = sample_keypair
    # Do NOT register — triggers UnknownAgentError.
    req = sign_request(agent_id="ghost", method="recv")

    async def _terminal(ctx: MiddlewareContext) -> dict[str, object]:  # pragma: no cover
        raise AssertionError("should not reach terminal")

    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _terminal)

    result = await pipeline.dispatch(
        "recv",
        {},
        connection_id="conn-c",
        metadata={"_connection_credential": req},
    )

    assert result.get("error_code") == "identity_failure"
    trace = result.get("metadata", {}).get("pipeline_trace", [])  # type: ignore[union-attr]
    assert len(trace) == 1
    assert trace[0]["verdict"] == "rejected"
    assert trace[0]["error_code"] == "identity_failure"


# ---------------------------------------------------------------------------
# Deliverable 5 — IdentityMiddleware shim deprecated, AuthMiddleware canonical
# ---------------------------------------------------------------------------


def test_identity_middleware_shim_is_deprecated() -> None:
    """IdentityMiddleware module docstring documents it as deprecated."""
    import sox_protocol.core.identity.middleware as shim_mod

    assert "deprecated" in (shim_mod.__doc__ or "").lower()


def test_auth_middleware_is_canonical() -> None:
    """AuthMiddleware is importable from canonical path and is not IdentityMiddleware."""
    from sox_protocol.core.identity.middleware import IdentityMiddleware
    from sox_protocol.core.middleware.plugins.auth import AuthMiddleware

    assert AuthMiddleware is not IdentityMiddleware
    assert AuthMiddleware.name == "auth"
