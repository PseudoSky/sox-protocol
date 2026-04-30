# SPDX-License-Identifier: Apache-2.0
"""Shared fixtures for the identity test suite."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sox_protocol.core.identity.audit import AuditLogWriter
from sox_protocol.core.identity.envelope import SignedRequest, compute_body_hash
from sox_protocol.core.identity.keys import generate_keypair
from sox_protocol.core.identity.registry import InMemoryCredentialRegistry
from sox_protocol.core.identity.verifier import IdentityVerifier

# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@pytest.fixture
def fixed_clock() -> Callable[[], float]:
    """A deterministic clock that always returns the same timestamp."""
    _now = [1_700_000_000.0]

    def _clock() -> float:
        return _now[0]

    return _clock


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    """A temporary path for the audit log (isolated per test)."""
    return tmp_path / "identity-failures.jsonl"


@pytest.fixture
def audit_writer(audit_path: Path, fixed_clock: Callable[[], float]) -> AuditLogWriter:
    """An AuditLogWriter writing to a tmp path with a fixed clock."""
    return AuditLogWriter(path=audit_path, clock=fixed_clock)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@pytest.fixture
def registry(fixed_clock: Callable[[], float]) -> InMemoryCredentialRegistry:
    """A fresh InMemoryCredentialRegistry with a fixed clock."""
    return InMemoryCredentialRegistry(clock=fixed_clock)


# ---------------------------------------------------------------------------
# Keypair
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_keypair() -> tuple[bytes, bytes]:
    """A freshly generated (private_seed, public_key) tuple."""
    return generate_keypair()


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------

@pytest.fixture
def verifier(
    registry: InMemoryCredentialRegistry,
    audit_writer: AuditLogWriter,
    fixed_clock: Callable[[], float],
) -> IdentityVerifier:
    """An IdentityVerifier backed by the tmp registry and audit writer."""
    return IdentityVerifier(
        registry,
        audit_writer,
        replay_window_seconds=300.0,
        clock=fixed_clock,
    )


# ---------------------------------------------------------------------------
# Helper: build SignedRequest
# ---------------------------------------------------------------------------

@pytest.fixture
def sign_request(
    sample_keypair: tuple[bytes, bytes],
) -> Callable[..., SignedRequest]:
    """Return a helper that builds a valid SignedRequest from a body dict.

    Usage::

        req = sign_request(agent_id="alice", method="send", body={"channel": "c"})
    """
    private_seed, _pub = sample_keypair

    def _build(
        *,
        agent_id: str = "alice",
        method: str = "send",
        body: dict[str, object] | None = None,
        nonce: str | None = None,
        timestamp: float = 1_700_000_000.0,
        private_seed_override: bytes | None = None,
    ) -> SignedRequest:
        if body is None:
            body = {"channel": "test"}
        seed = private_seed_override if private_seed_override is not None else private_seed
        pk = Ed25519PrivateKey.from_private_bytes(seed)
        body_hash = compute_body_hash(body)
        actual_nonce = nonce if nonce is not None else uuid.uuid4().hex
        req = SignedRequest(
            agent_id=agent_id,
            nonce=actual_nonce,
            timestamp=timestamp,
            method=method,
            body_hash=body_hash,
            signature=b"",  # placeholder; we'll sign below
        )
        from sox_protocol.core.identity.envelope import canonical_payload
        payload = canonical_payload(req)
        sig = pk.sign(payload)
        return SignedRequest(
            agent_id=agent_id,
            nonce=actual_nonce,
            timestamp=timestamp,
            method=method,
            body_hash=body_hash,
            signature=sig,
        )

    return _build
