# SPDX-License-Identifier: Apache-2.0
"""v1 transitional credential resolver for the HTTP transport.

This module abstracts the credential-format question deferred in
implementation-plan.json risk R1.  In v1, the HTTP transport accepts a bearer
token in ``Authorization: Bearer <agent_id>`` (or ``X-SOX-Agent-ID`` for
testing).  The token is treated as the agent_id directly.

A synthetic Ed25519 keypair is generated once at app startup and stored on
``app.state``.  On each request, this module produces a fresh
:class:`~sox_protocol.core.identity.envelope.SignedRequest` signed with the
synthetic private key, allowing :class:`AuthMiddleware` to perform real
cryptographic verification without requiring external key material in v1.

v1.1 hardening:
    Replace this module's implementation with a path that reads a real
    Ed25519 private key from ``~/.sox/agents/<agent_id>/key.ed25519``
    (or from a SOX_CREDENTIAL env var), validates it matches the registry,
    and issues a proper per-request SignedRequest.  Alternatively, accept an
    ``X-Sox-Signed-Request`` header carrying a base64'd SignedRequest envelope
    for forward-compat.  No other module needs to change — only this function.

Spec reference: ``spec/ports/identity.md §6``
"""

from __future__ import annotations

import time
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sox_protocol.core.identity.envelope import SignedRequest, canonical_payload, compute_body_hash


def resolve_credential(
    agent_id: str,
    private_key: Ed25519PrivateKey,
    operation: str,
    body: dict[str, object] | None = None,
) -> SignedRequest:
    """Build a fresh :class:`SignedRequest` for *agent_id* using *private_key*.

    Produces a per-request signed envelope with a unique nonce, current
    timestamp, and the correct operation method name.  The body hash is
    computed over *body* (defaults to empty dict if ``None``).

    This is the v1 transitional credential path: the private key is a
    synthetic ephemeral keypair generated at app startup and stored in
    ``app.state._private_key``.  The corresponding public key is
    pre-registered in the in-memory credential registry under *agent_id*
    (auto-registered on first request via
    :func:`~sox_protocol.adapters.transports.http._credential.ensure_agent_registered`).

    For v1 the bearer token IS the agent_id (``Authorization: Bearer <agent_id>``).
    v1.1 will accept an ``X-Sox-Signed-Request`` header carrying a real
    per-client signed envelope and this function will no longer be called for
    those callers.

    Args:
        agent_id: The agent identifier resolved from the bearer token.
        private_key: The ephemeral Ed25519 private key generated at startup.
        operation: The SOX operation name (e.g. ``"send"``, ``"recv"``).
        body: The request body dict used to compute the body hash.  May
            be ``None`` for operations with no body (hash over ``{}``).

    Returns:
        A fully signed :class:`SignedRequest` ready for injection into
        ``ctx.metadata["_connection_credential"]``.
    """
    if body is None:
        body = {}

    nonce = str(uuid.uuid4())
    timestamp = time.time()
    body_hash = compute_body_hash(body)

    # Build a partially-constructed SignedRequest with a placeholder signature
    # so we can compute canonical_payload, then re-build with the real signature.
    placeholder = SignedRequest(
        agent_id=agent_id,
        nonce=nonce,
        timestamp=timestamp,
        method=operation,
        body_hash=body_hash,
        signature=b"",
    )
    payload = canonical_payload(placeholder)
    signature = private_key.sign(payload)

    return SignedRequest(
        agent_id=agent_id,
        nonce=nonce,
        timestamp=timestamp,
        method=operation,
        body_hash=body_hash,
        signature=signature,
    )
