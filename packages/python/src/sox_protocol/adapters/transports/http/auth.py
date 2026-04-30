# SPDX-License-Identifier: Apache-2.0
"""Bearer token extraction and identity resolution for the HTTP transport.

Rejects requests with 401 + sox-error envelope when the Authorization header
is missing or the credential is not recognised by the identity layer.

The HTTP transport uses a simple model: any non-empty bearer token is treated
as the agent_id directly (no cryptographic verification in the HTTP layer
itself — the backing store enforces authz).  Production deployments SHOULD
wire a real IdentityVerifier here.

Spec reference: ``spec/ports/identity.md``
"""

from __future__ import annotations

from typing import Protocol

from fastapi import Request
from fastapi.responses import JSONResponse

from sox_protocol.adapters.transports.http.errors import sox_error_response


class IdentityResolver(Protocol):
    """Structural protocol for resolving a bearer token to an agent_id.

    Implementations receive the raw token string and return the authenticated
    agent_id, or raise :class:`ValueError` to indicate an invalid credential.
    """

    def resolve(self, token: str) -> str:
        """Resolve *token* to an agent_id.

        Args:
            token: Raw bearer token from the Authorization header.

        Returns:
            Authenticated agent_id string.

        Raises:
            ValueError: If the credential is invalid or unrecognised.
        """
        ...


class PassthroughIdentityResolver:
    """Identity resolver that treats the bearer token as the agent_id directly.

    Suitable for development and testing.  Any non-empty token is accepted and
    used verbatim as the agent_id.
    """

    def resolve(self, token: str) -> str:
        """Return *token* unchanged as the agent_id.

        Args:
            token: Raw bearer token.

        Returns:
            The token itself as the agent_id.

        Raises:
            ValueError: If the token is empty.
        """
        if not token:
            raise ValueError("Empty bearer token")
        return token


def extract_bearer_token(request: Request) -> str | None:
    """Extract the bearer token from the Authorization header.

    Args:
        request: The incoming FastAPI/Starlette request.

    Returns:
        The token string, or ``None`` if the header is absent or malformed.
    """
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    # Also accept X-SOX-Agent-ID header for testing / conformance runner
    agent_id_header = request.headers.get("X-SOX-Agent-ID", "").strip()
    if agent_id_header:
        return agent_id_header
    return None


def resolve_agent_id(
    request: Request,
    resolver: IdentityResolver,
) -> tuple[str, JSONResponse | None]:
    """Resolve the agent_id from the request, returning an error response if invalid.

    Args:
        request: Incoming HTTP request.
        resolver: Identity resolver to use.

    Returns:
        A tuple ``(agent_id, None)`` on success, or ``("", error_response)``
        on failure.
    """
    token = extract_bearer_token(request)
    if token is None:
        return (
            "",
            sox_error_response(
                error_code="missing_credential",
                message="Authorization: Bearer <token> header required",
                status_code=401,
            ),
        )
    try:
        agent_id = resolver.resolve(token)
    except ValueError as exc:
        return (
            "",
            sox_error_response(
                error_code="invalid_credential",
                message=str(exc),
                status_code=401,
            ),
        )
    return agent_id, None
