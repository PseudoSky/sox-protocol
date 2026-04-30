# SPDX-License-Identifier: Apache-2.0
"""Tests for sox_protocol.core.identity.middleware.

Spec reference: spec/ports/identity.md §4; spec/ports/middleware.md §4
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sox_protocol.core.identity.audit import AuditLogWriter
from sox_protocol.core.identity.envelope import SignedRequest, canonical_payload, compute_body_hash
from sox_protocol.core.identity.keys import generate_keypair
from sox_protocol.core.identity.middleware import IdentityMiddleware
from sox_protocol.core.identity.registry import InMemoryCredentialRegistry
from sox_protocol.core.identity.verifier import IdentityVerifier

FIXED_TS = 1_700_000_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signed_request(
    *,
    agent_id: str,
    method: str,
    private_seed: bytes,
    nonce: str = "test-nonce",
    timestamp: float = FIXED_TS,
) -> SignedRequest:
    import uuid
    body: dict[str, object] = {"channel": "test"}
    body_hash = compute_body_hash(body)
    actual_nonce = nonce if nonce != "test-nonce" else uuid.uuid4().hex
    skeleton = SignedRequest(
        agent_id=agent_id,
        nonce=actual_nonce,
        timestamp=timestamp,
        method=method,
        body_hash=body_hash,
        signature=b"",
    )
    pk = Ed25519PrivateKey.from_private_bytes(private_seed)
    sig = pk.sign(canonical_payload(skeleton))
    return SignedRequest(
        agent_id=agent_id,
        nonce=actual_nonce,
        timestamp=timestamp,
        method=method,
        body_hash=body_hash,
        signature=sig,
    )


@pytest.fixture
def keypair() -> tuple[bytes, bytes]:
    return generate_keypair()


@pytest.fixture
def reg() -> InMemoryCredentialRegistry:
    return InMemoryCredentialRegistry(clock=lambda: FIXED_TS)


@pytest.fixture
def audit_writer(tmp_path: Path) -> AuditLogWriter:
    return AuditLogWriter(path=tmp_path / "audit.jsonl", clock=lambda: FIXED_TS)


@pytest.fixture
def verifier(
    reg: InMemoryCredentialRegistry,
    audit_writer: AuditLogWriter,
) -> IdentityVerifier:
    return IdentityVerifier(reg, audit_writer, replay_window_seconds=300.0, clock=lambda: FIXED_TS)


@pytest.fixture
def mw(verifier: IdentityVerifier) -> IdentityMiddleware:
    return IdentityMiddleware(verifier)


# ---------------------------------------------------------------------------
# Identity middleware import smoke test (required by plan)
# ---------------------------------------------------------------------------

def test_identity_middleware_importable_from_package() -> None:
    """IdentityMiddleware is importable from sox_protocol.core.identity."""
    from sox_protocol.core.identity import IdentityMiddleware  # noqa: F401
    assert IdentityMiddleware is not None


# ---------------------------------------------------------------------------
# §4 — send requires verification
# ---------------------------------------------------------------------------

async def test_send_requires_verification(
    mw: IdentityMiddleware,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """IdentityMiddleware short-circuits unverified send before call_next."""
    call_next_called = False

    async def call_next(req: dict[str, object]) -> dict[str, object]:
        nonlocal call_next_called
        call_next_called = True
        return {"ok": True}

    request: dict[str, object] = {
        "operation": "send",
        "channel": "test",
        # No signed_request — should be rejected
    }
    response = await mw(request, call_next)
    assert response.get("error_code") == "identity_failure"
    assert not call_next_called


async def test_middleware_short_circuits_before_call_next(
    mw: IdentityMiddleware,
) -> None:
    """Unverified request: call_next is NOT awaited."""
    call_next_called = False

    async def call_next(req: dict[str, object]) -> dict[str, object]:
        nonlocal call_next_called
        call_next_called = True
        return {"ok": True}

    request: dict[str, object] = {"operation": "recv"}
    await mw(request, call_next)
    assert not call_next_called


async def test_subscribe_requires_verification(mw: IdentityMiddleware) -> None:
    """IdentityMiddleware short-circuits unverified subscribe."""
    call_next_called = False

    async def call_next(req: dict[str, object]) -> dict[str, object]:
        nonlocal call_next_called
        call_next_called = True
        return {"ok": True}

    request: dict[str, object] = {"operation": "subscribe"}
    response = await mw(request, call_next)
    assert response.get("error_code") == "identity_failure"
    assert not call_next_called


async def test_recv_requires_verification(mw: IdentityMiddleware) -> None:
    """IdentityMiddleware short-circuits unverified recv."""
    call_next_called = False

    async def call_next(req: dict[str, object]) -> dict[str, object]:
        nonlocal call_next_called
        call_next_called = True
        return {"ok": True}

    request: dict[str, object] = {"operation": "recv"}
    response = await mw(request, call_next)
    assert response.get("error_code") == "identity_failure"
    assert not call_next_called


async def test_list_channels_passes_through_when_unauthenticated(
    mw: IdentityMiddleware,
) -> None:
    """list_channels is informational and passes through without credential check."""
    call_next_called = False

    async def call_next(req: dict[str, object]) -> dict[str, object]:
        nonlocal call_next_called
        call_next_called = True
        return {"channels": []}

    request: dict[str, object] = {"operation": "list_channels"}
    response = await mw(request, call_next)
    assert call_next_called
    assert response == {"channels": []}


# ---------------------------------------------------------------------------
# Verified requests forward with mutated sender
# ---------------------------------------------------------------------------

async def test_verified_send_injects_sender(
    mw: IdentityMiddleware,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """Verified send request reaches call_next with server-certified sender."""
    private_seed, pub = keypair
    await reg.register("alice", pub)

    signed_request = _make_signed_request(
        agent_id="alice", method="send", private_seed=private_seed
    )
    received_request: dict[str, object] = {}

    async def call_next(req: dict[str, object]) -> dict[str, object]:
        received_request.update(req)
        return {"sent_at": FIXED_TS, "message_id": "1"}

    request: dict[str, object] = {
        "operation": "send",
        "channel": "test",
        "signed_request": signed_request,
        "sender": "evil-claim",  # should be overwritten
    }
    response = await mw(request, call_next)
    assert "error_code" not in response
    assert received_request.get("sender") == "alice"


async def test_middleware_propagates_response_on_success(
    mw: IdentityMiddleware,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """Verified request: call_next response is returned unchanged."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    signed_request = _make_signed_request(
        agent_id="alice", method="send", private_seed=private_seed
    )

    async def call_next(req: dict[str, object]) -> dict[str, object]:
        return {"sent_at": FIXED_TS, "message_id": "42"}

    request: dict[str, object] = {
        "operation": "send",
        "channel": "test",
        "signed_request": signed_request,
    }
    response = await mw(request, call_next)
    assert response == {"sent_at": FIXED_TS, "message_id": "42"}


async def test_verified_recv_injects_agent_id(
    mw: IdentityMiddleware,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """Verified recv request reaches call_next with agent_id injected."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    signed_request = _make_signed_request(
        agent_id="alice", method="recv", private_seed=private_seed
    )
    received: dict[str, object] = {}

    async def call_next(req: dict[str, object]) -> dict[str, object]:
        received.update(req)
        return {"messages": [], "drained_at": FIXED_TS}

    request: dict[str, object] = {
        "operation": "recv",
        "signed_request": signed_request,
    }
    await mw(request, call_next)
    assert received.get("agent_id") == "alice"


# ---------------------------------------------------------------------------
# Error envelope shape
# ---------------------------------------------------------------------------

async def test_error_envelope_has_identity_failure_code(mw: IdentityMiddleware) -> None:
    """Rejection response has error_code 'identity_failure'."""
    async def call_next(req: dict[str, object]) -> dict[str, object]:
        return {}

    request: dict[str, object] = {"operation": "send"}
    response = await mw(request, call_next)
    assert response["error_code"] == "identity_failure"
    assert "message" in response


async def test_invalid_signed_request_type_rejected(mw: IdentityMiddleware) -> None:
    """signed_request that is not a SignedRequest instance is rejected."""
    async def call_next(req: dict[str, object]) -> dict[str, object]:
        return {}

    request: dict[str, object] = {
        "operation": "send",
        "signed_request": {"fake": "dict"},  # not a SignedRequest
    }
    response = await mw(request, call_next)
    assert response["error_code"] == "identity_failure"


async def test_identity_failure_on_subscribe_caught_as_error(
    mw: IdentityMiddleware,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """IdentityFailure on subscribe (bad sig) is caught and returned as sox-error."""
    private_seed, pub = keypair
    await reg.register("alice", pub)

    # Build a valid-looking SignedRequest but with a wrong signature
    signed_request = _make_signed_request(
        agent_id="alice", method="subscribe", private_seed=private_seed
    )
    # Tamper signature
    from sox_protocol.core.identity.envelope import SignedRequest as SR
    tampered = SR(
        agent_id=signed_request.agent_id,
        nonce=signed_request.nonce,
        timestamp=signed_request.timestamp,
        method=signed_request.method,
        body_hash=signed_request.body_hash,
        signature=b"\x00" * 64,
    )

    async def call_next(req: dict[str, object]) -> dict[str, object]:
        return {}

    request: dict[str, object] = {
        "operation": "subscribe",
        "signed_request": tampered,
    }
    response = await mw(request, call_next)
    assert response["error_code"] == "identity_failure"


def test_make_identity_error_response_returns_json_string() -> None:
    """make_identity_error_response() returns a valid JSON string."""
    import json

    from sox_protocol.core.identity.middleware import make_identity_error_response
    result = make_identity_error_response("test error")
    parsed = json.loads(result)
    assert parsed["error_code"] == "identity_failure"
    assert parsed["message"] == "test error"
