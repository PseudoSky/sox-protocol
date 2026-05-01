# SPDX-License-Identifier: Apache-2.0
"""AuthMiddleware — canonical middleware plugin for agent identity verification.

This is the **canonical** auth middleware for the pipeline.  The legacy
``sox_protocol.core.identity.middleware.IdentityMiddleware`` shim still exists
for backward compatibility but is deprecated; new code MUST import from here.

Credential seam (spec §6)
--------------------------
``spec/ports/identity.md §6`` requires that the agent credential lives on the
**connection seam** (MCP launch parameter ``SOX_CREDENTIAL`` or transport
context attribute), NOT inside any tool-call input dict.

The credential is delivered to this middleware through
``ctx.metadata["_connection_credential"]``, which is populated by the MCP
server or transport adapter at connection-establishment time (before the first
tool call is dispatched).  Tool-call input dicts MUST NOT carry a
``signed_request`` or any other credential field.

For backward-compatibility during the transition period this middleware will
also accept ``signed_request`` present directly in ``ctx.input``, but a
deprecation warning is logged and the input field is stripped before
forwarding.  This fallback will be removed in a future minor version.

``middleware_timings`` (spec ab1c954)
--------------------------------------
On every invocation :class:`AuthMiddleware` appends an entry to
``ctx._meta["middleware_timings"]``::

    {"middleware": "auth", "duration_ms": <int>, "verdict": "ok" | "reject"}

Downstream pipeline stages may include ``ctx._meta`` in the response
``_meta`` block.

Migration note
--------------
``sox_protocol.core.identity.middleware.IdentityMiddleware`` is a deprecated
shim.  New code MUST use :class:`AuthMiddleware` directly::

    from sox_protocol.core.middleware.plugins.auth import AuthMiddleware

Spec reference: ``spec/ports/middleware.md §4 (auth)``; ``spec/ports/identity.md §2, §4, §6``
"""

from __future__ import annotations

import logging
import time as _time_module

from sox_protocol.core.identity.envelope import SignedRequest
from sox_protocol.core.identity.errors import IdentityFailure
from sox_protocol.core.identity.verifier import IdentityVerifier
from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.errors import ShortCircuitResponse
from sox_protocol.core.middleware.protocol import CallNext

_log = logging.getLogger(__name__)

# Operations requiring identity verification per spec/ports/identity.md §4.
# list_agents was added as v1 MUST in commit 9f3e11e.
_IDENTITY_ENFORCED_OPERATIONS: frozenset[str] = frozenset(
    {"send", "recv", "subscribe", "list_agents"}
)


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


def _resolve_credential(ctx: MiddlewareContext) -> SignedRequest | None:
    """Resolve the :class:`SignedRequest` credential from the connection seam.

    Primary source (spec §6): ``ctx.metadata["_connection_credential"]`` —
    populated by the transport adapter at connection establishment time.

    Fallback (deprecated, transition only): ``ctx.input.get("signed_request")``
    — carried inside the tool-call dict.  A deprecation warning is logged and
    the field is stripped from ``ctx.input`` before forwarding so it does not
    appear in downstream tool-call surfaces.

    Args:
        ctx: The per-call middleware context.

    Returns:
        The :class:`SignedRequest` if found and valid, else ``None``.
    """
    # Primary: connection-bound seam.
    conn_cred = ctx.metadata.get("_connection_credential")
    if isinstance(conn_cred, SignedRequest):
        return conn_cred

    # Fallback: tool-call dict (deprecated).
    input_cred = ctx.input.get("signed_request")
    if isinstance(input_cred, SignedRequest):
        _log.warning(
            "signed_request found in tool-call input for operation %r — "
            "this is deprecated per spec §6; move credential to connection "
            "seam via ctx.metadata['_connection_credential'].",
            ctx.operation,
        )
        # Strip from input so the field does not leak into downstream stages.
        ctx.input.pop("signed_request", None)
        return input_cred

    return None


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

    On every invocation appends a ``middleware_timings`` entry to
    ``ctx._meta`` (spec ``ab1c954``)::

        {"middleware": "auth", "duration_ms": <int>, "verdict": "ok" | "reject"}

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

    def _record_timing(
        self,
        ctx: MiddlewareContext,
        verdict: str,
        duration_ms: int,
    ) -> None:
        """Append a middleware_timings entry to ``ctx._meta``.

        Args:
            ctx: The per-call context whose ``_meta`` dict is updated.
            verdict: ``"ok"`` on success or ``"reject"`` on identity failure.
            duration_ms: Wall-clock duration of the auth check in milliseconds.
        """
        timings = ctx._meta.setdefault("middleware_timings", [])
        if not isinstance(timings, list):  # pragma: no cover — defensive guard only
            return
        timings.append(
            {
                "middleware": "auth",
                "duration_ms": duration_ms,
                "verdict": verdict,
            }
        )

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: CallNext,
    ) -> dict[str, object]:
        """Verify identity and forward to *call_next* on success.

        Credential is read from the connection seam
        (``ctx.metadata["_connection_credential"]``), NOT from the tool-call
        input dict (spec §6).

        Args:
            ctx: The per-call context.
            call_next: Next pipeline stage.

        Returns:
            Response from *call_next*, or a sox-error dict on rejection.
        """
        operation = ctx.operation
        t_start = _time_module.monotonic()

        # Non-enforced operations pass through without credential check.
        if operation not in _IDENTITY_ENFORCED_OPERATIONS:
            return await call_next(ctx)

        signed_request = _resolve_credential(ctx)
        if signed_request is None:
            duration_ms = int((_time_module.monotonic() - t_start) * 1000)
            self._record_timing(ctx, "reject", duration_ms)
            raise ShortCircuitResponse(
                _make_identity_error(
                    "Identity verification required: credential missing. "
                    "Set SOX_CREDENTIAL in MCP launch parameters."
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
            duration_ms = int((_time_module.monotonic() - t_start) * 1000)
            self._record_timing(ctx, "reject", duration_ms)
            raise ShortCircuitResponse(_make_identity_error(exc.reason)) from exc

        duration_ms = int((_time_module.monotonic() - t_start) * 1000)
        self._record_timing(ctx, "ok", duration_ms)
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
