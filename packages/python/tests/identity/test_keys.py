# SPDX-License-Identifier: Apache-2.0
"""Tests for sox_protocol.core.identity.keys.

Spec reference: docs/adr/0002-agent-identity-primitive.md §Operational
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sox_protocol.core.identity.keys import (
    generate_keypair,
    load_private_key,
    sign,
    verify_signature,
)


def test_generate_keypair_returns_32_byte_keys() -> None:
    """generate_keypair() produces 32-byte private seed and 32-byte public key."""
    private_seed, public_key = generate_keypair()
    assert len(private_seed) == 32
    assert len(public_key) == 32


def test_generate_keypair_produces_distinct_keys() -> None:
    """Two successive generate_keypair() calls produce different keys."""
    a_priv, a_pub = generate_keypair()
    b_priv, b_pub = generate_keypair()
    assert a_priv != b_priv
    assert a_pub != b_pub


def test_ed25519_sign_verify_roundtrip() -> None:
    """sign() + verify_signature() roundtrip succeeds with matching keypair."""
    private_seed, public_key = generate_keypair()
    pk = Ed25519PrivateKey.from_private_bytes(private_seed)
    payload = b"test payload"
    signature = sign(pk, payload)
    assert verify_signature(public_key, payload, signature) is True


def test_verify_signature_rejects_tampered_payload() -> None:
    """verify_signature() returns False when the payload has been tampered."""
    private_seed, public_key = generate_keypair()
    pk = Ed25519PrivateKey.from_private_bytes(private_seed)
    payload = b"original payload"
    signature = sign(pk, payload)
    assert verify_signature(public_key, b"tampered payload", signature) is False


def test_verify_signature_rejects_wrong_key() -> None:
    """verify_signature() returns False when verified with a different public key."""
    private_seed, _ = generate_keypair()
    _, other_public_key = generate_keypair()
    pk = Ed25519PrivateKey.from_private_bytes(private_seed)
    payload = b"test"
    signature = sign(pk, payload)
    assert verify_signature(other_public_key, payload, signature) is False


def test_verify_signature_rejects_bad_signature_bytes() -> None:
    """verify_signature() returns False for a garbage signature."""
    _, public_key = generate_keypair()
    assert verify_signature(public_key, b"payload", b"not-a-valid-signature") is False


def test_load_private_key_rejects_world_readable(tmp_path: Path) -> None:
    """load_private_key() raises PermissionError if file mode is not 0600."""
    key_file = tmp_path / "key.ed25519"
    private_seed, _ = generate_keypair()
    key_file.write_bytes(private_seed)
    key_file.chmod(0o644)
    with pytest.raises(PermissionError, match="0600"):
        load_private_key(key_file)


def test_load_private_key_accepts_0600(tmp_path: Path) -> None:
    """load_private_key() succeeds when file mode is exactly 0600."""
    key_file = tmp_path / "key.ed25519"
    private_seed, _ = generate_keypair()
    key_file.write_bytes(private_seed)
    key_file.chmod(0o600)
    loaded = load_private_key(key_file)
    assert isinstance(loaded, Ed25519PrivateKey)


def test_load_private_key_rejects_wrong_size(tmp_path: Path) -> None:
    """load_private_key() raises ValueError for a file that isn't exactly 32 bytes."""
    key_file = tmp_path / "key.ed25519"
    key_file.write_bytes(b"short")
    key_file.chmod(0o600)
    with pytest.raises(ValueError, match="32 bytes"):
        load_private_key(key_file)


def test_load_private_key_file_not_found(tmp_path: Path) -> None:
    """load_private_key() raises FileNotFoundError for a missing file."""
    with pytest.raises(FileNotFoundError):
        load_private_key(tmp_path / "nonexistent.ed25519")


def test_loaded_key_sign_verify_roundtrip(tmp_path: Path) -> None:
    """A key loaded via load_private_key() produces verifiable signatures."""
    key_file = tmp_path / "key.ed25519"
    private_seed, public_key = generate_keypair()
    key_file.write_bytes(private_seed)
    key_file.chmod(0o600)
    loaded = load_private_key(key_file)
    payload = b"roundtrip test"
    sig = sign(loaded, payload)
    assert verify_signature(public_key, payload, sig) is True
