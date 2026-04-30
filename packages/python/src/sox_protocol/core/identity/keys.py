# SPDX-License-Identifier: Apache-2.0
"""Ed25519 key-management helpers.

Wraps the ``cryptography`` library so that the rest of the identity package
stays algorithm-agnostic.  All callers import from this module; only this
module touches ``cryptography`` primitives directly.

Spec reference: ``docs/adr/0002-agent-identity-primitive.md §Operational``

Runtime key path convention (documented here; NOT created by this module):
    Private key: ``~/.sox/agents/<agent_id>/key.ed25519`` (mode 0600)
    Public key:  ``~/.sox/agents/<agent_id>/key.ed25519.pub``

The module does NOT create these directories at import time.  Callers that
need the default path must create it themselves (see :func:`load_private_key`).
"""

from __future__ import annotations

import stat
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def generate_keypair() -> tuple[bytes, bytes]:
    """Generate a fresh Ed25519 keypair.

    Returns:
        A ``(private_seed, public_key_bytes)`` tuple where:
        - ``private_seed`` is the 32-byte raw private seed (store mode 0600).
        - ``public_key_bytes`` is the 32-byte raw public key (safe to share).
    """
    private_key = Ed25519PrivateKey.generate()
    private_seed = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )
    return private_seed, public_key_bytes


def load_private_key(path: Path) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from a raw-seed file, enforcing mode 0600.

    The file must contain exactly 32 bytes (the raw Ed25519 private seed).
    Mode 0600 is enforced: if the file is readable by group or other, this
    function raises :class:`PermissionError` rather than loading the key.

    Args:
        path: Absolute path to the private-key file.

    Returns:
        A loaded :class:`~cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey`.

    Raises:
        FileNotFoundError: If *path* does not exist.
        PermissionError: If the file permissions are not exactly 0600.
        ValueError: If the file does not contain exactly 32 bytes.
    """
    file_stat = path.stat()
    # Check only the permission bits (mask off file-type bits).
    mode_bits = stat.S_IMODE(file_stat.st_mode)
    if mode_bits != 0o600:
        raise PermissionError(
            f"Private key at {path} must have mode 0600, "
            f"got {oct(mode_bits)}. "
            "Run: chmod 0600 " + str(path)
        )

    raw = path.read_bytes()
    if len(raw) != 32:
        raise ValueError(
            f"Private key file {path} must contain exactly 32 bytes "
            f"(raw Ed25519 seed), got {len(raw)}."
        )
    return Ed25519PrivateKey.from_private_bytes(raw)


def sign(private_key: Ed25519PrivateKey, payload: bytes) -> bytes:
    """Sign *payload* with *private_key* and return the 64-byte signature.

    Args:
        private_key: The agent's Ed25519 private key.
        payload: The bytes to sign (typically :func:`~envelope.canonical_payload`
            output).

    Returns:
        64-byte Ed25519 signature.
    """
    return private_key.sign(payload)


def verify_signature(public_key_bytes: bytes, payload: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 *signature* over *payload* using *public_key_bytes*.

    Args:
        public_key_bytes: 32-byte raw public key.
        payload: The signed bytes.
        signature: 64-byte signature to verify.

    Returns:
        ``True`` if the signature is valid, ``False`` otherwise.  Never raises
        on an invalid signature — callers check the return value.
    """
    try:
        pub: Ed25519PublicKey = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        pub.verify(signature, payload)
        return True
    except Exception:
        return False
