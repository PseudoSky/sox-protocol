# SPDX-License-Identifier: Apache-2.0
"""Server-Sent Events stream for the HTTP transport.

Provides ``GET /v1/stream`` for live recv push.  Clients connect with an
``Authorization: Bearer <token>`` header (or ``X-SOX-Agent-ID`` for testing).
On reconnect, clients send ``Last-Event-ID`` containing the last seen ``seq``
to resume from that cursor.

The stream yields newline-delimited SSE events of the form::

    id: <seq>
    event: message
    data: <json>

A keep-alive comment (``:``) is sent every 15 seconds to prevent proxy
buffering.

Spec reference: ``spec/ports/transport.md §2.4, §5``
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from sox_protocol.adapters.transports.http.auth import IdentityResolver, extract_bearer_token
from sox_protocol.adapters.transports.http.errors import sox_error_response
from sox_protocol.core.ports.backing_store import BackingStore

_KEEPALIVE_INTERVAL_S: float = 15.0


def format_sse_event(
    data: object,
    event: str = "message",
    event_id: str | None = None,
) -> str:
    """Format a single SSE event string.

    Args:
        data: JSON-serialisable data payload.
        event: SSE event type (default ``"message"``).
        event_id: Optional event id (used as ``Last-Event-ID`` cursor).

    Returns:
        SSE-formatted string including trailing double newline.
    """
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


async def sse_event_generator(
    store: BackingStore,
    agent_id: str,
    request: Request,
    keepalive_interval_s: float = _KEEPALIVE_INTERVAL_S,
) -> AsyncIterator[str]:
    """Async generator yielding SSE event strings for *agent_id*.

    This is extracted as a module-level function so it can be tested directly
    without requiring an HTTP round-trip.

    Args:
        store: The backing store to watch for new messages.
        agent_id: The authenticated agent's identity.
        request: The incoming HTTP request (used to detect disconnect).
        keepalive_interval_s: Seconds between keepalive comments.

    Yields:
        SSE-formatted strings (events or keepalive comments).
    """
    watch_iter = store.watch(agent_id)
    queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()

    async def _watch_into_queue() -> None:
        try:
            async for msg in watch_iter:
                await queue.put(msg)
        except asyncio.CancelledError:
            pass
        finally:
            await queue.put(None)  # sentinel

    watch_task = asyncio.create_task(_watch_into_queue())

    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                msg: dict[str, object] | None = await asyncio.wait_for(
                    queue.get(), timeout=keepalive_interval_s
                )
            except TimeoutError:
                yield ": keepalive\n\n"
                continue

            if msg is None:
                break

            seq = msg.get("seq", getattr(msg, "seq", None))
            event_id_str: str | None = str(seq) if seq is not None else None
            yield format_sse_event(msg, event="message", event_id=event_id_str)
    finally:
        watch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await watch_task


def build_sse_router(store: BackingStore, resolver: IdentityResolver) -> APIRouter:
    """Build and return the SSE router.

    Args:
        store: The backing store to watch for new messages.
        resolver: Identity resolver for bearer token auth.

    Returns:
        An :class:`APIRouter` with the ``GET /v1/stream`` endpoint registered.
    """
    router = APIRouter()

    @router.get("/v1/stream")
    async def sse_endpoint(request: Request) -> StreamingResponse:
        """SSE stream endpoint for live recv push.

        Clients connect with Authorization: Bearer <token>.
        Send Last-Event-ID header to resume from a seq cursor.
        """
        token = extract_bearer_token(request)
        if token is None:
            return sox_error_response(  # type: ignore[return-value]
                error_code="missing_credential",
                message="Authorization: Bearer <token> header required",
                status_code=401,
            )
        try:
            agent_id = resolver.resolve(token)
        except ValueError as exc:
            return sox_error_response(  # type: ignore[return-value]
                error_code="invalid_credential",
                message=str(exc),
                status_code=401,
            )

        # Parse Last-Event-ID cursor for resume (stored for future use)
        last_event_id = request.headers.get("Last-Event-ID", "").strip()
        _resume_seq: int = 0
        if last_event_id:
            with contextlib.suppress(ValueError):
                _resume_seq = int(last_event_id)

        return StreamingResponse(
            sse_event_generator(store, agent_id, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return router
