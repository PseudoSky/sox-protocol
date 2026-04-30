# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol identity layer — public API.

This package implements the Identity port (``spec/ports/identity.md``),
providing:

- Credential registry with Ed25519 public-key storage.
- Canonical signed-request envelope and body-hash computation.
- Identity verifier with replay-attack protection.
- Append-only audit-log writer for identity failures.
- Standalone middleware adapter (see migration note below).

Migration note
--------------
The :class:`IdentityMiddleware` in this package is a standalone adapter
for use before the hooks-middleware pipeline is wired.  During the
``hooks-middleware`` engagement it will be replaced by a re-export shim
pointing at ``sox_protocol.core.middleware.plugins.auth.AuthMiddleware``.
Existing imports will continue to work.

This package MUST NOT import from ``sox_protocol.adapters`` (import-linter
enforced; see ``pyproject.toml``).
"""

from sox_protocol.core.identity.audit import AuditLogWriter
from sox_protocol.core.identity.envelope import SignedRequest, VerifiedIdentity
from sox_protocol.core.identity.errors import (
    IdentityFailure,
    MalformedRequestError,
    ReplayDetectedError,
    RevokedCredentialError,
    SignatureMismatchError,
    UnknownAgentError,
)
from sox_protocol.core.identity.middleware import IdentityMiddleware
from sox_protocol.core.identity.registry import (
    CredentialRecord,
    CredentialRegistry,
    InMemoryCredentialRegistry,
)
from sox_protocol.core.identity.verifier import IdentityVerifier

__all__ = [
    # Errors
    "IdentityFailure",
    "UnknownAgentError",
    "RevokedCredentialError",
    "SignatureMismatchError",
    "ReplayDetectedError",
    "MalformedRequestError",
    # Envelope
    "SignedRequest",
    "VerifiedIdentity",
    # Registry
    "CredentialRecord",
    "CredentialRegistry",
    "InMemoryCredentialRegistry",
    # Verifier
    "IdentityVerifier",
    # Audit
    "AuditLogWriter",
    # Middleware adapter
    "IdentityMiddleware",
]
