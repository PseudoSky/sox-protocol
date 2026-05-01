# SPDX-License-Identifier: Apache-2.0
"""v1 transitional credential resolver for the stdio MCP transport.

This module abstracts the credential-format question deferred in
implementation-plan.json risk R1.  In v1, the MCP server resolves the
agent identity from environment variables at startup (SOX_AGENT_ID /
SOX_AGENT_ID_SOURCE).  A synthetic Ed25519 keypair is generated at lifespan
startup and the agent_id is pre-registered in the in-memory credential
registry with that keypair.

Every tool call then uses ``resolve_credential()`` to produce a fresh
:class:`~sox_protocol.core.identity.envelope.SignedRequest` signed with the
synthetic private key.  This allows ``AuthMiddleware`` to perform real
cryptographic verification without requiring external key material in v1.

v1.1 hardening:
    Replace this module's implementation with a path that reads a real
    Ed25519 private key from ``~/.sox/agents/<agent_id>/key.ed25519``
    (or from a SOX_CREDENTIAL env var), validates it matches the registry,
    and issues a proper per-request SignedRequest.  No other module needs
    to change — only this function.

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

    Produces a per-call signed envelope with a unique nonce, current
    timestamp, and the correct operation method name.  The body hash is
    computed over *body* (defaults to empty dict if ``None``).

    This is the v1 transitional credential path: the private key is a
    synthetic ephemeral keypair generated at lifespan startup and stored in
    ``lifespan_result["_private_key"]``.  The corresponding public key is
    pre-registered in the in-memory credential registry under *agent_id*.

    Args:
        agent_id: The agent identifier resolved from the environment.
        private_key: The ephemeral Ed25519 private key generated at startup.
        operation: The SOX operation name (e.g. ``"send"``, ``"recv"``).
        body: The tool-call body dict used to compute the body hash.  May
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
