# SPDX-License-Identifier: Apache-2.0
"""Migration regression: identity scenarios via AuthMiddleware + Pipeline.dispatch.

Re-runs the identity rejection scenarios using the new AuthMiddleware via
Pipeline.dispatch (rather than the standalone IdentityMiddleware) and asserts
identical outcomes — the migration regression check.

Spec reference: ``spec/ports/identity.md §2-§5 (post-migration)``
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.pipeline import Pipeline
from sox_protocol.core.middleware.plugins.auth import AuthMiddleware

# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------


async def _passthrough(ctx: MiddlewareContext) -> dict[str, object]:
    return {"ok": True, "agent_id": ctx.agent_id}


# ---------------------------------------------------------------------------
# test_unknown_agent_through_pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_agent_through_pipeline(
    verifier,
    sign_request,
) -> None:
    """Unknown agent through Pipeline.dispatch returns identity_failure (same as old MW)."""
    req = sign_request(agent_id="ghost", method="recv")
    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _passthrough)

    result = await pipeline.dispatch(
        "recv",
        {"signed_request": req},
        connection_id="conn-1",
    )

    assert result["error_code"] == "identity_failure"


# ---------------------------------------------------------------------------
# test_send_sender_overwritten_through_pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_sender_overwritten_through_pipeline(
    verifier,
    registry,
    sample_keypair,
    sign_request,
) -> None:
    """Verified send replaces caller-claimed sender (same as old MW bind_for_send)."""
    private_seed, public_key = sample_keypair
    await registry.register("alice", public_key)

    req = sign_request(agent_id="alice", method="send")

    captured: list[str] = []

    async def _capture(ctx: MiddlewareContext) -> dict[str, object]:
        captured.append(str(ctx.input.get("sender", "")))
        return {"ok": True}

    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _capture)

    await pipeline.dispatch(
        "send",
        {
            "signed_request": req,
            "channel": "test",
            "sender": "FORGED_VALUE",
            "body": {},
        },
        connection_id="conn-1",
    )

    assert captured == ["alice"]


# ---------------------------------------------------------------------------
# test_audit_log_still_written_on_rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_still_written_on_rejection(
    verifier,
    audit_path: Path,
    sign_request,
) -> None:
    """Audit log entry is written when auth rejects an unknown agent."""
    req = sign_request(agent_id="unknown_agent", method="send")
    auth_mw = AuthMiddleware(verifier)
    pipeline = Pipeline([auth_mw], _passthrough)

    result = await pipeline.dispatch(
        "send",
        {"signed_request": req, "channel": "x", "body": {}},
        connection_id="conn-audit",
    )

    assert result["error_code"] == "identity_failure"
    assert audit_path.exists(), "Audit log must be written on rejection"
    content = audit_path.read_text()
    assert "unknown_agent" in content


# ---------------------------------------------------------------------------
# Shim import still works
# ---------------------------------------------------------------------------


def test_identity_middleware_shim_import() -> None:
    """Existing imports of sox_protocol.core.identity.middleware.IdentityMiddleware still work."""
    from sox_protocol.core.identity.middleware import IdentityMiddleware

    # The shim class still exists and is instantiable with a verifier.
    assert IdentityMiddleware is not None
    assert callable(IdentityMiddleware)
