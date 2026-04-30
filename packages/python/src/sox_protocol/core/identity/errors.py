# SPDX-License-Identifier: Apache-2.0
"""Typed exception hierarchy for SOX identity failures.

Every exception carries a stable ``error_code`` matching the values in
``spec/envelopes/sox-error.schema.json`` so callers can translate directly to
the wire error envelope without string-matching messages.

Spec reference: ``spec/ports/identity.md §5``
"""

from __future__ import annotations


class IdentityFailure(Exception):
    """Base class for all identity-verification failures.

    Attributes:
        error_code: Machine-readable code; always ``"identity_failure"`` for
            the base class and all subclasses (matching sox-error envelope).
        reason: Human-readable description of *why* verification failed.
            MUST NOT leak credentials, other agents' existence, or stack
            traces (``spec/ports/identity.md §5``).
    """

    error_code: str = "identity_failure"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason: str = reason

    def __repr__(self) -> str:
        return f"{type(self).__name__}(reason={self.reason!r})"


class UnknownAgentError(IdentityFailure):
    """Raised when the credential presents an agent_id not in the registry.

    The error message MUST NOT reveal which agent IDs *are* registered
    (``spec/ports/identity.md §5`` — no information leakage).
    """


class RevokedCredentialError(IdentityFailure):
    """Raised when the agent is known but its credential has been revoked."""


class SignatureMismatchError(IdentityFailure):
    """Raised when the Ed25519 signature does not verify against the payload."""


class ReplayDetectedError(IdentityFailure):
    """Raised when a nonce has already been seen within the replay window."""


class MalformedRequestError(IdentityFailure):
    """Raised when the signed-request envelope is structurally invalid.

    Examples: empty agent_id, missing nonce, timestamp too old/future.
    """
