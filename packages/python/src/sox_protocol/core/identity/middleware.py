# SPDX-License-Identifier: Apache-2.0
"""MIGRATION SHIM — identity middleware compatibility layer.

After the hooks-middleware engagement, :class:`AuthMiddleware` in
``sox_protocol.core.middleware.plugins.auth`` is the canonical middleware for
the pipeline. This module provides:

1. :data:`IdentityMiddleware` — a backward-compatible wrapper that accepts the
   OLD dict-based ``(request: dict, call_next: Callable) -> dict`` signature
   so that existing code calling ``IdentityMiddleware(verifier)(request, call_next)``
   continues to work unchanged.

2. :func:`make_identity_error_response` — convenience helper kept for
   transport-layer callers.

.. deprecated::
    :class:`IdentityMiddleware` is a compatibility shim.  New code MUST import
    :class:`~sox_protocol.core.middleware.plugins.auth.AuthMiddleware` directly::

        from sox_protocol.core.middleware.plugins.auth import AuthMiddleware

Spec reference: ``spec/ports/middleware.md §4 (auth)``; ``spec/ports/identity.md §4``
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from sox_protocol.core.identity.errors import IdentityFailure
from sox_protocol.core.identity.verifier import IdentityVerifier


def _make_identity_error(reason: str) -> dict[str, object]:
    return {
        "error_code": "identity_failure",
        "message": reason,
        "detail": None,
        "retry_after": None,
    }


_IDENTITY_ENFORCED_OPERATIONS: frozenset[str] = frozenset(
    {"send", "recv", "subscribe", "list_agents"}
)


class IdentityMiddleware:
    """Backward-compatible dict-based identity middleware shim.

    Accepts the OLD calling convention::

        mw = IdentityMiddleware(verifier)
        response = await mw(request_dict, call_next)

    where ``request_dict`` is a plain :class:`dict` with at least
    ``"operation"`` and optionally ``"signed_request"``.

    .. deprecated::
        Use :class:`~sox_protocol.core.middleware.plugins.auth.AuthMiddleware`
        with the pipeline instead.  This class exists only for backward
        compatibility with pre-migration call sites.

    Args:
        verifier: The configured :class:`~sox_protocol.core.identity.verifier.IdentityVerifier`.
    """

    def __init__(self, verifier: IdentityVerifier) -> None:
        self._verifier = verifier

    async def __call__(
        self,
        request: dict[str, object],
        call_next: Callable[[dict[str, object]], Awaitable[dict[str, object]]],
    ) -> dict[str, object]:
        """Process *request* through identity verification then forward.

        Args:
            request: Tool-call input dict.  Must contain ``"operation"`` and,
                for enforced operations, ``"signed_request"``.
            call_next: Async callable forwarding to the next pipeline stage.

        Returns:
            Response from *call_next*, or a sox-error dict on rejection.
        """
        from sox_protocol.core.identity.envelope import SignedRequest

        operation = str(request.get("operation", ""))
        connection_id = request.get("connection_id")
        conn_str = str(connection_id) if connection_id is not None else None

        if operation not in _IDENTITY_ENFORCED_OPERATIONS:
            return await call_next(request)

        signed_request = request.get("signed_request")
        if not isinstance(signed_request, SignedRequest):
            return _make_identity_error(
                "Identity verification required: signed_request missing or invalid"
            )

        try:
            if operation == "send":
                mutated = await self._verifier.bind_for_send(signed_request, request)
                return await call_next(mutated)
            else:
                identity = await self._verifier.verify(
                    signed_request, operation=operation, connection_id=conn_str
                )
                mutated2 = {**request, "agent_id": identity.agent_id}
                return await call_next(mutated2)
        except IdentityFailure as exc:
            return _make_identity_error(exc.reason)


def make_identity_error_response(message: str) -> str:
    """Return a JSON-serialised sox-error envelope string for identity failures.

    Convenience helper for transports that need a pre-serialised error body.

    .. deprecated::
        Build the envelope directly or use
        :func:`sox_protocol.core.middleware.errors.make_internal_error`.

    Args:
        message: Human-readable failure message.

    Returns:
        JSON string of the sox-error envelope.
    """
    return json.dumps(_make_identity_error(message))


__all__ = ["IdentityMiddleware", "make_identity_error_response"]
