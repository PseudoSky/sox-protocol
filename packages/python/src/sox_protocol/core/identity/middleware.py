# SPDX-License-Identifier: Apache-2.0
"""Standalone identity middleware adapter.

This module provides :class:`IdentityMiddleware`, which wraps
:class:`~sox_protocol.core.identity.verifier.IdentityVerifier` with a
``handle(request, call_next)`` signature compatible with the upcoming
middleware pipeline defined in ``spec/ports/middleware.md``.

Migration seam
--------------
During the **hooks-middleware** engagement, this module will be rewritten as a
re-export shim::

    from sox_protocol.core.middleware.plugins.auth import AuthMiddleware as IdentityMiddleware
    __all__ = ["IdentityMiddleware"]

Existing imports of ``sox_protocol.core.identity.middleware.IdentityMiddleware``
will continue to work unchanged.  New code MUST import
``AuthMiddleware`` from ``sox_protocol.core.middleware.plugins.auth``.

Spec reference: ``spec/ports/identity.md §4``; ``spec/ports/middleware.md §4 (auth)``
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from sox_protocol.core.identity.errors import IdentityFailure
from sox_protocol.core.identity.verifier import IdentityVerifier


def _make_identity_error(reason: str) -> dict[str, object]:
    """Build a sox-error envelope for an identity failure.

    The message deliberately omits internal details to avoid leaking
    implementation specifics (``spec/ports/identity.md §5``).

    Args:
        reason: Short human-readable explanation.

    Returns:
        Dict conforming to ``spec/envelopes/sox-error.schema.json``.
    """
    return {
        "error_code": "identity_failure",
        "message": reason,
        "detail": None,
        "retry_after": None,
    }


_IDENTITY_ENFORCED_OPERATIONS = {"send", "recv", "subscribe"}
"""Operations that require identity verification per ``spec/ports/identity.md §4``."""


class IdentityMiddleware:
    """Short-circuit middleware that enforces identity on every mutating call.

    For operations listed in ``spec/ports/identity.md §4`` (``send``,
    ``subscribe``, ``recv``), a :class:`SignedRequest` MUST be present in
    ``request["signed_request"]``.  If verification fails, the response is a
    sox-error and ``call_next`` is never awaited — ensuring no backing-store
    access occurs on rejection.

    For ``list_channels`` (informational), verification is RECOMMENDED but not
    required (``spec/ports/identity.md §4``).  This middleware passes
    ``list_channels`` through without checking credentials.

    For ``send`` operations, the verified ``agent_id`` is injected into
    ``request["sender"]`` via
    :meth:`~sox_protocol.core.identity.verifier.IdentityVerifier.bind_for_send`.

    Usage::

        verifier = IdentityVerifier(registry, audit)
        mw = IdentityMiddleware(verifier)
        response = await mw(request_dict, call_next)

    Args:
        verifier: The configured :class:`IdentityVerifier`.
    """

    def __init__(self, verifier: IdentityVerifier) -> None:
        self._verifier = verifier

    async def __call__(
        self,
        request: dict[str, object],
        call_next: Callable[[dict[str, object]], Awaitable[dict[str, object]]],
    ) -> dict[str, object]:
        """Process *request* through identity verification then forward to *call_next*.

        Args:
            request: Tool-call input dict.  Must contain:
                - ``"operation"`` (str): the SOX operation name.
                - ``"signed_request"``: a
                  :class:`~sox_protocol.core.identity.envelope.SignedRequest`
                  instance (required for enforced operations).
            call_next: Async callable that forwards the (possibly mutated)
                request to the next pipeline stage.

        Returns:
            The response from ``call_next``, or a sox-error dict on rejection.
        """
        from sox_protocol.core.identity.envelope import SignedRequest

        operation = str(request.get("operation", ""))
        connection_id = request.get("connection_id")
        conn_str = str(connection_id) if connection_id is not None else None

        # Informational operations pass through without credential check.
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

    Args:
        message: Human-readable failure message.

    Returns:
        JSON string of the sox-error envelope.
    """
    return json.dumps(_make_identity_error(message))
