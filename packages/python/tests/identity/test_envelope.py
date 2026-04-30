# SPDX-License-Identifier: Apache-2.0
"""Tests for sox_protocol.core.identity.envelope.

Spec reference: spec/ports/identity.md §7; docs/adr/0002
"""

from __future__ import annotations

from sox_protocol.core.identity.envelope import (
    SignedRequest,
    VerifiedIdentity,
    canonical_payload,
    compute_body_hash,
)


def test_compute_body_hash_is_deterministic() -> None:
    """compute_body_hash() returns the same value for the same content."""
    body = {"channel": "test", "body": {"msg": "hello"}}
    assert compute_body_hash(body) == compute_body_hash(body)


def test_canonical_payload_is_deterministic_across_key_reorderings() -> None:
    """Reordering body keys does not change body_hash (spec §7)."""
    body_a = {"b": 1, "a": 2}
    body_b = {"a": 2, "b": 1}
    assert compute_body_hash(body_a) == compute_body_hash(body_b)


def test_compute_body_hash_differs_for_different_content() -> None:
    """Different bodies produce different hashes."""
    h1 = compute_body_hash({"key": "value1"})
    h2 = compute_body_hash({"key": "value2"})
    assert h1 != h2


def test_compute_body_hash_is_64_hex_chars() -> None:
    """SHA-256 hex digest is always 64 lowercase hex characters."""
    h = compute_body_hash({})
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_body_hash_empty_body() -> None:
    """Empty body produces a stable hash (not empty string)."""
    h = compute_body_hash({})
    assert len(h) == 64


def test_canonical_payload_format() -> None:
    """canonical_payload() produces newline-separated fields in expected order."""
    req = SignedRequest(
        agent_id="alice",
        nonce="abc123",
        timestamp=1_700_000_000.0,
        method="send",
        body_hash="deadbeef" * 8,
        signature=b"sig",
    )
    payload = canonical_payload(req)
    lines = payload.decode("utf-8").split("\n")
    assert lines[0] == "alice"
    assert lines[1] == "abc123"
    assert lines[2] == "1700000000.000000"
    assert lines[3] == "send"
    assert lines[4] == "deadbeef" * 8


def test_canonical_payload_is_bytes() -> None:
    """canonical_payload() returns bytes, not str."""
    req = SignedRequest(
        agent_id="agent",
        nonce="nonce",
        timestamp=0.0,
        method="recv",
        body_hash="a" * 64,
        signature=b"",
    )
    assert isinstance(canonical_payload(req), bytes)


def test_canonical_payload_timestamp_precision() -> None:
    """Timestamp is serialised with 6 decimal places."""
    req = SignedRequest(
        agent_id="a",
        nonce="n",
        timestamp=1.5,
        method="m",
        body_hash="b" * 64,
        signature=b"",
    )
    payload = canonical_payload(req).decode()
    assert "1.500000" in payload


def test_signed_request_is_frozen() -> None:
    """SignedRequest is a frozen dataclass (immutable)."""
    req = SignedRequest(
        agent_id="alice",
        nonce="nonce",
        timestamp=0.0,
        method="send",
        body_hash="a" * 64,
        signature=b"",
    )
    try:
        req.agent_id = "bob"  # type: ignore[misc]
        raise AssertionError("Should have raised FrozenInstanceError")
    except AssertionError:
        raise
    except Exception as exc:
        assert "frozen" in str(exc).lower() or "cannot assign" in str(exc).lower()


def test_verified_identity_is_frozen() -> None:
    """VerifiedIdentity is a frozen dataclass (immutable)."""
    vi = VerifiedIdentity(agent_id="alice", verified_at=0.0, connection_id=None)
    try:
        vi.agent_id = "bob"  # type: ignore[misc]
        raise AssertionError("Should have raised FrozenInstanceError")
    except AssertionError:
        raise
    except Exception as exc:
        assert "frozen" in str(exc).lower() or "cannot assign" in str(exc).lower()


def test_verified_identity_connection_id_optional() -> None:
    """VerifiedIdentity accepts None for connection_id."""
    vi = VerifiedIdentity(agent_id="alice", verified_at=1.0, connection_id=None)
    assert vi.connection_id is None
