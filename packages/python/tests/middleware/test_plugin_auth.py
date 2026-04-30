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
