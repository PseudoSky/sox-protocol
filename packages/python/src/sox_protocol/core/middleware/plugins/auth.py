# SPDX-License-Identifier: Apache-2.0
"""AuthMiddleware — thin shim over IdentityVerifier for the middleware pipeline.

This plugin is the migration target for the standalone
``sox_protocol.core.identity.middleware.IdentityMiddleware``.  It wraps the
identity-primitive's public API without duplicating any identity logic.

Migration note
--------------
``sox_protocol.core.identity.middleware`` is rewritten as a re-export shim
pointing at :class:`AuthMiddleware`.  Existing imports continue to work.
New code MUST import from ``sox_protocol.core.middleware.plugins.auth``.

Spec reference: ``spec/ports/middleware.md §4 (auth)``; ``spec/ports/identity.md §2, §4``
"""

from __future__ import annotations

from sox_protocol.core.identity.envelope import SignedRequest
from sox_protocol.core.identity.errors import IdentityFailure
from sox_protocol.core.identity.verifier import IdentityVerifier
from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.errors import ShortCircuitResponse
from sox_protocol.core.middleware.protocol import CallNext

# Operations requiring identity verification per spec/ports/identity.md §4.
_IDENTITY_ENFORCED_OPERATIONS: frozenset[str] = frozenset({"send", "recv", "subscribe"})


def _make_identity_error(reason: str) -> dict[str, object]:
    """Build a sox-error envelope for an identity failure.

    Args:
        reason: Human-readable failure message (no secrets or stack traces).

    Returns:
        Dict conforming to ``spec/envelopes/sox-error.schema.json`` with
        ``error_code="identity_failure"``.
    """
    return {
        "error_code": "identity_failure",
        "message": reason,
        "detail": None,
        "retry_after": None,
    }


class AuthMiddleware:
    """Middleware that verifies agent identity on enforced operations.

    Calls :meth:`~sox_protocol.core.identity.verifier.IdentityVerifier.verify`
    to populate ``ctx.agent_id``; calls
    :meth:`~sox_protocol.core.identity.verifier.IdentityVerifier.bind_for_send`
    on ``send`` operations to overwrite ``ctx.input["sender"]`` with the
    server-certified identity.

    Short-circuits with ``error_code="identity_failure"`` on any
    :class:`~sox_protocol.core.identity.errors.IdentityFailure` subclass.

    Non-enforced operations (e.g. ``list_channels``) pass through without
    credential check.

    Attributes:
        name: Always ``'auth'``.
        must_run_after: Must follow ``namespace_resolver`` in the chain.
        must_run_before: Must precede ``rate_limit``, ``schema_validator``,
            ``idempotency``, and ``store_dispatch``.

    Args:
        verifier: The configured :class:`~sox_protocol.core.identity.verifier.IdentityVerifier`.
    """

    name: str = "auth"
    must_run_after: tuple[str, ...] = ("namespace_resolver",)
    must_run_before: tuple[str, ...] = (
        "rate_limit",
        "schema_validator",
        "idempotency",
        "store_dispatch",
    )

    def __init__(self, verifier: IdentityVerifier) -> None:
        self._verifier = verifier

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: CallNext,
    ) -> dict[str, object]:
        """Verify identity and forward to *call_next* on success.

        Args:
            ctx: The per-call context.  ``ctx.input`` must contain
                ``"signed_request"`` (a :class:`SignedRequest`) for enforced
                operations.
            call_next: Next pipeline stage.

        Returns:
            Response from *call_next*, or a sox-error dict on rejection.
        """
        operation = ctx.operation

        # Non-enforced operations pass through without credential check.
        if operation not in _IDENTITY_ENFORCED_OPERATIONS:
            return await call_next(ctx)

        signed_request = ctx.input.get("signed_request")
        if not isinstance(signed_request, SignedRequest):
            raise ShortCircuitResponse(
                _make_identity_error(
                    "Identity verification required: signed_request missing or invalid"
                )
            )

        try:
            if operation == "send":
                # bind_for_send verifies AND overwrites sender — returns updated dict.
                updated_input = await self._verifier.bind_for_send(
                    signed_request, dict(ctx.input)
                )
                # Bind agent_id from verified identity.
                sender = str(updated_input.get("sender", ""))
                ctx.input.update(updated_input)
                ctx.agent_id = sender
            else:
                identity = await self._verifier.verify(
                    signed_request,
                    operation=operation,
                    connection_id=ctx.connection_id,
                )
                ctx.agent_id = identity.agent_id

        except IdentityFailure as exc:
            raise ShortCircuitResponse(_make_identity_error(exc.reason)) from exc

        return await call_next(ctx)


def build_auth_middleware(verifier: IdentityVerifier) -> AuthMiddleware:
    """Factory function for use as an entry-point or registry factory.

    Args:
        verifier: The :class:`~sox_protocol.core.identity.verifier.IdentityVerifier`
            to wrap.

    Returns:
        A configured :class:`AuthMiddleware` instance.
    """
    return AuthMiddleware(verifier)
