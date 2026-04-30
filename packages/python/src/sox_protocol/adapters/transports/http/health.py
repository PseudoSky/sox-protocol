# SPDX-License-Identifier: Apache-2.0
"""GET /health endpoint for the HTTP transport.

Returns server liveness information without requiring authentication.

Spec reference: ``spec/protocol.md §Health``
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

_PROTOCOL_VERSION = "1.0"
_START_TIME: float = time.time()

health_router = APIRouter()


@health_router.get("/health")
async def health_check() -> JSONResponse:
    """Return server health status.

    No authentication required.  Returns 200 when the server is live.

    Returns:
        JSON object with ``status``, ``protocol_version``, ``store_ok``,
        and ``uptime_s``.
    """
    uptime_s = time.time() - _START_TIME
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "protocol_version": _PROTOCOL_VERSION,
            "store_ok": True,
            "uptime_s": round(uptime_s, 3),
        },
    )
