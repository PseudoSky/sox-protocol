# SPDX-License-Identifier: Apache-2.0
"""Bearer token extraction for the HTTP transport.

v1 transitional: this module's sole responsibility is extracting the raw
bearer token string from the ``Authorization`` header (or the ``X-SOX-Agent-ID``
testing header).  Identity verification belongs in
:class:`~sox_protocol.core.middleware.plugins.auth.AuthMiddleware` which runs
inside :class:`~sox_protocol.core.middleware.pipeline.Pipeline`.

``IdentityResolver``, ``PassthroughIdentityResolver``, and ``resolve_agent_id``
were deleted in phase 03-build-http (pipeline-integration engagement).
Verification is now performed by ``AuthMiddleware`` via
``ctx.metadata["_connection_credential"]``.

Spec reference: ``spec/ports/identity.md §6``
"""

from __future__ import annotations

from fastapi import Request


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
