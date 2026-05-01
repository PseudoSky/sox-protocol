# SPDX-License-Identifier: Apache-2.0
"""Canonical signed-request envelope and body-hash utilities.

This module defines the exact bytes that get signed over the wire, ensuring
that the signature covers a deterministic, canonical representation of every
relevant request field.

Spec reference: ``spec/ports/identity.md §7``;
``docs/adr/0002-agent-identity-primitive.md`` (signed_request envelope:
agent_id, nonce, timestamp, method, body-hash).

The canonical payload is::

    <agent_id>\\n<nonce>\\n<timestamp>\\n<method>\\n<body_hash>

where ``body_hash`` is the hex-encoded SHA-256 digest of the JSON-serialised
request body with keys in sorted order (deterministic regardless of insertion
order).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class SignedRequest:
    """Immutable signed-request envelope presented by a client at every call.

    Attributes:
        agent_id: The caller's claimed identity (server verifies this claim).
        nonce: Unique per-request random token; prevents replay.
        timestamp: Unix epoch seconds (float) at which the client created
            this request. The server validates it is within the replay window.
        method: The SOX operation name (e.g. ``"send"``, ``"recv"``).
        body_hash: Hex-encoded SHA-256 of the canonical JSON body (keys sorted,
            no extra whitespace). Use :func:`compute_body_hash` to produce.
        signature: Ed25519 signature over :func:`canonical_payload` bytes,
            produced with the agent's private key.
    """

    agent_id: str
    nonce: str
    timestamp: float
    method: str
    body_hash: str
    signature: bytes


@dataclass(frozen=True)
class VerifiedIdentity:
    """Result returned by :class:`~sox_protocol.core.identity.verifier.IdentityVerifier`
    after a successful verification.

    Attributes:
        agent_id: The server-certified identity (never the client-claimed value
            — the verifier matches against the registry record).
        verified_at: Unix epoch seconds at which the verification succeeded.
        connection_id: Opaque connection identifier, if provided by the
            transport layer. ``None`` for in-process / test usage.
        origin_server: Originating SOX server node identifier.  Always
            ``None`` in v1.0 single-server deployments.  Reserved for
            federated v2 deployments where agent IDs take the form
            ``<server-id>/<agent-id>``.  See ``spec/ports/identity.md §7``.
    """

    agent_id: str
    verified_at: float
    connection_id: str | None
    origin_server: str | None = None


def compute_body_hash(body: dict[str, object]) -> str:
    """Return the hex-encoded SHA-256 of the canonical JSON serialisation of *body*.

    Keys are sorted recursively so that insertion order does not affect the
    hash.  The JSON is encoded as UTF-8 with no extra whitespace.

    Args:
        body: Arbitrary JSON-serialisable dict representing the request body.

    Returns:
        Lowercase hex string (64 chars) of the SHA-256 digest.

    Example::

        >>> compute_body_hash({"b": 1, "a": 2}) == compute_body_hash({"a": 2, "b": 1})
        True
    """
    serialised = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def canonical_payload(req: SignedRequest) -> bytes:
    """Build the exact byte string that is signed (and verified) for *req*.

    The format is newline-separated fields::

        <agent_id>\\n<nonce>\\n<timestamp>\\n<method>\\n<body_hash>

    The timestamp is formatted as a fixed-precision decimal string (6 decimal
    places) so floating-point representation differences between runtimes do
    not silently produce different payloads.

    Args:
        req: The signed-request envelope.

    Returns:
        UTF-8 encoded bytes ready to pass to an Ed25519 sign or verify call.
    """
    payload = "\n".join(
        [
            req.agent_id,
            req.nonce,
            f"{req.timestamp:.6f}",
            req.method,
            req.body_hash,
        ]
    )
    return payload.encode("utf-8")
