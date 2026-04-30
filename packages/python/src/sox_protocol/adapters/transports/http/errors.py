# SPDX-License-Identifier: Apache-2.0
"""Error mapping for the HTTP transport.

Maps internal exceptions to sox-error envelopes and HTTP status codes.

Spec reference: ``spec/envelopes/sox-error.schema.json``
"""

from __future__ import annotations

from fastapi.responses import JSONResponse


def sox_error_response(
    error_code: str,
    message: str,
    status_code: int = 400,
    detail: object = None,
    retry_after: int | None = None,
) -> JSONResponse:
    """Build a JSONResponse with a sox-error envelope.

    Args:
        error_code: Machine-readable error code string.
        message: Human-readable error description.
        status_code: HTTP status code to use.
        detail: Optional structured detail object.
        retry_after: Optional seconds hint for retryable errors.

    Returns:
        A :class:`JSONResponse` with the sox-error body.
    """
    body = {
        "error_code": error_code,
        "message": message,
        "detail": detail,
        "retry_after": retry_after,
    }
    return JSONResponse(status_code=status_code, content=body)


def validation_error_response(message: str) -> JSONResponse:
    """Return a 400 validation-error response.

    Args:
        message: Human-readable description of the validation failure.

    Returns:
        A :class:`JSONResponse` with status 400.
    """
    return sox_error_response(
        error_code="validation_error",
        message=message,
        status_code=400,
    )


def internal_error_response(message: str) -> JSONResponse:
    """Return a 500 internal-error response.

    Args:
        message: Human-readable description of the internal failure.

    Returns:
        A :class:`JSONResponse` with status 500.
    """
    return sox_error_response(
        error_code="internal_error",
        message=message,
        status_code=500,
    )
