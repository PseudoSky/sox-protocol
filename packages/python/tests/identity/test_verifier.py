# SPDX-License-Identifier: Apache-2.0
"""Tests for sox_protocol.core.identity.verifier.

Spec reference: spec/ports/identity.md §2, §4, §5
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sox_protocol.core.identity.audit import AuditLogWriter
from sox_protocol.core.identity.envelope import (
    SignedRequest,
    VerifiedIdentity,
    canonical_payload,
    compute_body_hash,
)
from sox_protocol.core.identity.errors import (
    MalformedRequestError,
    ReplayDetectedError,
    RevokedCredentialError,
    SignatureMismatchError,
    UnknownAgentError,
)
from sox_protocol.core.identity.keys import generate_keypair
from sox_protocol.core.identity.registry import InMemoryCredentialRegistry
from sox_protocol.core.identity.verifier import IdentityVerifier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXED_TS = 1_700_000_000.0


@pytest.fixture
def clock() -> Callable[[], float]:
    return lambda: FIXED_TS


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "audit.jsonl"


@pytest.fixture
def audit(audit_path: Path) -> AuditLogWriter:
    return AuditLogWriter(path=audit_path, clock=lambda: FIXED_TS)


@pytest.fixture
def reg(clock: Callable[[], float]) -> InMemoryCredentialRegistry:
    return InMemoryCredentialRegistry(clock=clock)


@pytest.fixture
def keypair() -> tuple[bytes, bytes]:
    return generate_keypair()


@pytest.fixture
def verifier(
    reg: InMemoryCredentialRegistry,
    audit: AuditLogWriter,
    clock: Callable[[], float],
) -> IdentityVerifier:
    return IdentityVerifier(reg, audit, replay_window_seconds=300.0, clock=clock)


def _make_request(
    *,
    agent_id: str = "alice",
    method: str = "send",
    body: dict[str, object] | None = None,
    nonce: str | None = None,
    timestamp: float = FIXED_TS,
    private_seed: bytes,
) -> SignedRequest:
    if body is None:
        body = {"channel": "test"}
    if nonce is None:
        nonce = uuid.uuid4().hex
    pk = Ed25519PrivateKey.from_private_bytes(private_seed)
    body_hash = compute_body_hash(body)
    skeleton = SignedRequest(
        agent_id=agent_id,
        nonce=nonce,
        timestamp=timestamp,
        method=method,
        body_hash=body_hash,
        signature=b"",
    )
    sig = pk.sign(canonical_payload(skeleton))
    return SignedRequest(
        agent_id=agent_id,
        nonce=nonce,
        timestamp=timestamp,
        method=method,
        body_hash=body_hash,
        signature=sig,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

async def test_verify_happy_path(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """verify() returns VerifiedIdentity for a valid signed request."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    req = _make_request(agent_id="alice", private_seed=private_seed)
    result = await verifier.verify(req, operation="send")
    assert isinstance(result, VerifiedIdentity)
    assert result.agent_id == "alice"
    assert result.verified_at == FIXED_TS


async def test_verify_with_connection_id(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """verify() includes connection_id in VerifiedIdentity."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    req = _make_request(agent_id="alice", private_seed=private_seed)
    result = await verifier.verify(req, operation="send", connection_id="conn-1")
    assert result.connection_id == "conn-1"


# ---------------------------------------------------------------------------
# §2 — sender overwrite
# ---------------------------------------------------------------------------

async def test_send_overwrites_sender_with_verified_id(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """bind_for_send() replaces caller-claimed sender with the verified agent_id."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    req = _make_request(agent_id="alice", method="send", private_seed=private_seed)
    send_input: dict[str, object] = {"channel": "test", "sender": "evil-impersonator"}
    result = await verifier.bind_for_send(req, send_input)
    assert result["sender"] == "alice"


async def test_client_cannot_inject_sender(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """bind_for_send() overwrites sender even when body.sender is forged."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    req = _make_request(agent_id="alice", method="send", private_seed=private_seed)
    # Caller tries to claim someone else's identity via body field
    send_input: dict[str, object] = {"channel": "ch", "sender": "bob-forged"}
    result = await verifier.bind_for_send(req, send_input)
    assert result["sender"] == "alice"


async def test_agent_id_not_in_send_input_schema(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """bind_for_send() tolerates send input without sender key — server injects it."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    req = _make_request(agent_id="alice", method="send", private_seed=private_seed)
    send_input: dict[str, object] = {"channel": "test"}  # no sender key
    result = await verifier.bind_for_send(req, send_input)
    assert result["sender"] == "alice"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------

async def test_unknown_agent_returns_identity_failure(
    verifier: IdentityVerifier,
    keypair: tuple[bytes, bytes],
) -> None:
    """UnknownAgentError raised for an agent not in the registry."""
    private_seed, _ = keypair
    req = _make_request(agent_id="ghost", private_seed=private_seed)
    with pytest.raises(UnknownAgentError):
        await verifier.verify(req, operation="send")


async def test_revoked_credential_rejected(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """RevokedCredentialError raised for a revoked agent."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    await reg.revoke("alice")
    req = _make_request(agent_id="alice", private_seed=private_seed)
    with pytest.raises(RevokedCredentialError):
        await verifier.verify(req, operation="send")


async def test_signature_mismatch_rejected(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """SignatureMismatchError when the payload has been tampered."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    req = _make_request(agent_id="alice", private_seed=private_seed)
    # Tamper with the signature
    tampered = SignedRequest(
        agent_id=req.agent_id,
        nonce=req.nonce,
        timestamp=req.timestamp,
        method=req.method,
        body_hash=req.body_hash,
        signature=b"\x00" * 64,
    )
    with pytest.raises(SignatureMismatchError):
        await verifier.verify(tampered, operation="send")


async def test_replay_within_window_rejected(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """Second use of the same nonce within replay_window raises ReplayDetectedError."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    # First request — succeeds
    req = _make_request(agent_id="alice", nonce="fixed-nonce", private_seed=private_seed)
    await verifier.verify(req, operation="send")
    # Second request with the same nonce — same timestamp, within window
    req2 = _make_request(agent_id="alice", nonce="fixed-nonce", private_seed=private_seed)
    with pytest.raises(ReplayDetectedError):
        await verifier.verify(req2, operation="send")


async def test_replay_outside_window_accepted(
    reg: InMemoryCredentialRegistry,
    audit: AuditLogWriter,
    keypair: tuple[bytes, bytes],
) -> None:
    """Nonce reuse after the replay window has expired is accepted."""
    private_seed, pub = keypair
    await reg.register("alice", pub)

    ts1 = 1_700_000_000.0
    ts2 = ts1 + 400.0  # beyond 300s window

    clock_state = [ts1]

    def clock() -> float:
        return clock_state[0]

    verifier = IdentityVerifier(reg, audit, replay_window_seconds=300.0, clock=clock)

    # First request at ts1
    req1 = _make_request(
        agent_id="alice", nonce="same-nonce", timestamp=ts1, private_seed=private_seed
    )
    await verifier.verify(req1, operation="send")

    # Advance clock past window, use same nonce with new timestamp
    clock_state[0] = ts2
    req2 = _make_request(
        agent_id="alice", nonce="same-nonce", timestamp=ts2, private_seed=private_seed
    )
    result = await verifier.verify(req2, operation="send")
    assert result.agent_id == "alice"


async def test_timestamp_too_old_raises_malformed(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """MalformedRequestError raised when request timestamp is outside replay window."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    # Timestamp is 1000s in the past (window is 300s)
    old_ts = FIXED_TS - 1000.0
    req = _make_request(agent_id="alice", timestamp=old_ts, private_seed=private_seed)
    with pytest.raises(MalformedRequestError):
        await verifier.verify(req, operation="send")


async def test_empty_agent_id_raises_malformed(
    verifier: IdentityVerifier,
    keypair: tuple[bytes, bytes],
) -> None:
    """MalformedRequestError raised for empty agent_id."""
    private_seed, _ = keypair
    req = _make_request(agent_id="x", private_seed=private_seed)
    # Manually build a request with empty agent_id
    bad_req = SignedRequest(
        agent_id="",
        nonce=req.nonce,
        timestamp=req.timestamp,
        method=req.method,
        body_hash=req.body_hash,
        signature=req.signature,
    )
    with pytest.raises(MalformedRequestError):
        await verifier.verify(bad_req, operation="send")


async def test_empty_nonce_raises_malformed(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """MalformedRequestError raised for empty nonce."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    req = _make_request(agent_id="alice", private_seed=private_seed)
    bad_req = SignedRequest(
        agent_id=req.agent_id,
        nonce="",
        timestamp=req.timestamp,
        method=req.method,
        body_hash=req.body_hash,
        signature=req.signature,
    )
    with pytest.raises(MalformedRequestError):
        await verifier.verify(bad_req, operation="send")


# ---------------------------------------------------------------------------
# Audit log integration
# ---------------------------------------------------------------------------

async def test_rejection_writes_audit_line(
    verifier: IdentityVerifier,
    audit_path: Path,
    keypair: tuple[bytes, bytes],
) -> None:
    """A rejected verify() writes exactly one JSONL line to the audit log."""
    private_seed, _ = keypair
    req = _make_request(agent_id="ghost", private_seed=private_seed)
    with pytest.raises(UnknownAgentError):
        await verifier.verify(req, operation="send")
    lines = [ln for ln in audit_path.read_text().strip().split("\n") if ln]
    assert len(lines) == 1


# ---------------------------------------------------------------------------
# No partial state on failure
# ---------------------------------------------------------------------------

async def test_no_partial_state_on_failure(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """Failed verify() does not mutate registry or replay cache invariants."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    # Tampered signature — should fail
    req = _make_request(agent_id="alice", nonce="unique-nonce", private_seed=private_seed)
    tampered = SignedRequest(
        agent_id=req.agent_id,
        nonce=req.nonce,
        timestamp=req.timestamp,
        method=req.method,
        body_hash=req.body_hash,
        signature=b"\x00" * 64,
    )
    with pytest.raises(SignatureMismatchError):
        await verifier.verify(tampered, operation="send")

    # The nonce should NOT be in the replay cache — a valid request with the same
    # nonce should succeed (failure did not poison the cache).
    valid_req = _make_request(agent_id="alice", nonce="unique-nonce", private_seed=private_seed)
    result = await verifier.verify(valid_req, operation="send")
    assert result.agent_id == "alice"


# ---------------------------------------------------------------------------
# Error message leakage
# ---------------------------------------------------------------------------

async def test_error_message_does_not_leak_other_agent_ids(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """UnknownAgentError message does not reveal other registered agents."""
    # Register a known agent
    _, pub = keypair
    await reg.register("alice", pub)

    # Attempt to verify an unknown agent
    priv2, _ = generate_keypair()
    req = _make_request(agent_id="ghost", private_seed=priv2)
    with pytest.raises(UnknownAgentError) as exc_info:
        await verifier.verify(req, operation="send")
    assert "alice" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Persistence across calls
# ---------------------------------------------------------------------------

def test_identity_failure_repr() -> None:
    """IdentityFailure.__repr__() includes the class name and reason."""
    from sox_protocol.core.identity.errors import UnknownAgentError
    exc = UnknownAgentError("no such agent")
    r = repr(exc)
    assert "UnknownAgentError" in r
    assert "no such agent" in r


async def test_verifier_persists_binding_across_calls(
    verifier: IdentityVerifier,
    reg: InMemoryCredentialRegistry,
    keypair: tuple[bytes, bytes],
) -> None:
    """Same connection_id with distinct nonces succeeds multiple times."""
    private_seed, pub = keypair
    await reg.register("alice", pub)
    for _ in range(3):
        req = _make_request(agent_id="alice", private_seed=private_seed)
        result = await verifier.verify(req, operation="recv", connection_id="conn-persistent")
        assert result.agent_id == "alice"


# ---------------------------------------------------------------------------
# Concurrency — TOCTOU regression test
# ---------------------------------------------------------------------------


async def test_concurrent_same_nonce_only_one_succeeds(
    reg: InMemoryCredentialRegistry,
    audit: AuditLogWriter,
    keypair: tuple[bytes, bytes],
) -> None:
    """Exactly one concurrent verify() with the same nonce succeeds; the rest raise ReplayDetectedError.

    Without the asyncio.Lock protecting the prune+check+insert sequence, two or
    more coroutines can each observe the nonce as absent (between the check and
    the insert of the first coroutine), causing multiple tasks to pass through
    the replay guard with the same nonce — violating the replay-protection
    invariant.

    This test fires N=32 concurrent verify() calls, all sharing a single nonce
    and a single valid signing key.  The asyncio.Lock in
    _check_and_insert_nonce() must ensure exactly 1 passes.
    """
    import asyncio as _asyncio

    private_seed, pub = keypair
    await reg.register("alice", pub)

    # Use a real (non-frozen) clock so the timestamp freshness check passes for
    # all tasks.  The nonce is fixed — every task presents the same envelope.
    import time as _time

    now = _time.time()
    fixed_nonce = "concurrent-replay-test-nonce"
    verifier = IdentityVerifier(reg, audit, replay_window_seconds=300.0)

    req = _make_request(
        agent_id="alice",
        nonce=fixed_nonce,
        timestamp=now,
        private_seed=private_seed,
    )

    N = 32
    successes: list[VerifiedIdentity] = []
    replay_errors: list[ReplayDetectedError] = []

    async def _attempt() -> None:
        try:
            result = await _asyncio.wait_for(
                verifier.verify(req, operation="send"),
                timeout=5.0,
            )
            successes.append(result)
        except ReplayDetectedError as exc:
            replay_errors.append(exc)

    await _asyncio.gather(*[_attempt() for _ in range(N)])

    assert len(successes) == 1, (
        f"Expected exactly 1 success, got {len(successes)}. "
        "The nonces lock is either absent or not covering the full check+insert."
    )
    assert len(replay_errors) == N - 1, (
        f"Expected {N - 1} replay rejections, got {len(replay_errors)}."
    )
