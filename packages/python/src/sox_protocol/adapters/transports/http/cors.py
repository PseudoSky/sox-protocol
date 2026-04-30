# SPDX-License-Identifier: Apache-2.0
"""CORS middleware factory for the HTTP transport.

Honours SOX_HTTP_CORS_ORIGINS; defaults to localhost origins.
MUST NOT emit Access-Control-Allow-Origin: * when credentials are present.

Spec reference: ``spec/ports/transport.md §4``
"""

from __future__ import annotations

from starlette.middleware.cors import CORSMiddleware


def build_cors_middleware(
    origins: list[str],
) -> tuple[type[CORSMiddleware], dict[str, object]]:
    """Return the CORS middleware class and its kwargs for use with FastAPI.

    The returned tuple is consumed by ``app.add_middleware(*build_cors_middleware(...))``.

    Credentials (Authorization headers) are always allowed.  Because credentials
    are enabled, the origin allow-list MUST NOT contain ``"*"``; if ``"*"`` is
    passed it is removed and replaced with the localhost defaults.

    Args:
        origins: List of allowed origin strings (e.g. ``["http://localhost:3000"]``).

    Returns:
        ``(CORSMiddleware, kwargs_dict)`` ready for ``app.add_middleware``.
    """
    # Ensure wildcard is never used with credentials
    safe_origins = [o for o in origins if o != "*"]
    if not safe_origins:
        safe_origins = ["http://localhost", "http://127.0.0.1"]

    kwargs: dict[str, object] = {
        "allow_origins": safe_origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
        "expose_headers": ["X-SOX-Seq", "Last-Event-ID"],
    }
    return CORSMiddleware, kwargs
