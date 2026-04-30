# SPDX-License-Identifier: Apache-2.0
"""Typed exception and response classes for the middleware pipeline.

Short-circuit responses and error envelopes defined here are used throughout
the pipeline to halt execution and return a sox-error-shaped dict to the
caller without leaking implementation details.

Spec reference: ``spec/ports/middleware.md §7``; ``spec/envelopes/sox-error.schema.json``
"""

from __future__ import annotations


def make_internal_error(reason: str) -> dict[str, object]:
    """Build a sox-error envelope for an internal (non-caller) error.

    The message deliberately omits stack traces and internal details
    per ``spec/ports/middleware.md §7``.

    Args:
        reason: Short human-readable explanation (safe for external exposure).

    Returns:
        Dict conforming to ``spec/envelopes/sox-error.schema.json`` with
        ``error_code="internal_error"``.
    """
    return {
        "error_code": "internal_error",
        "message": reason,
        "detail": None,
        "retry_after": None,
    }


class MiddlewareError(Exception):
    """Base class for all middleware pipeline errors.

    Subclasses are caught by :class:`~sox_protocol.core.middleware.pipeline.Pipeline`
    and converted to appropriate sox-error response dicts.
    """


class ChainConfigurationError(MiddlewareError):
    """Raised when the middleware chain cannot be assembled due to constraint violations.

    Examples: must_run_before/must_run_after conflicts, missing required links,
    duplicate middleware names.
    """


class ShortCircuitResponse(MiddlewareError):
    """Raised by a middleware to immediately return a response without forwarding.

    The wrapped *response* MUST conform to the relevant operation output schema
    (success) or ``spec/envelopes/sox-error.schema.json`` (rejection).

    Spec reference: ``spec/ports/middleware.md §5``

    Args:
        response: The complete response dict to return to the caller.
    """

    def __init__(self, response: dict[str, object]) -> None:
        super().__init__("short-circuit")
        self.response: dict[str, object] = response
