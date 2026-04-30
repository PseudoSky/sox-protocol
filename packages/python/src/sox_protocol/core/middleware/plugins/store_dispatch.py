# SPDX-License-Identifier: Apache-2.0
"""StoreDispatchMiddleware — terminal backing-store dispatcher.

This is the only chain link permitted to perform persistence.  It maps the
``ctx.operation`` name to the corresponding :class:`BackingStore` method and
returns the response dict in the shape expected by the matching operation
output schema.

Spec reference: ``spec/ports/middleware.md §4 (store_dispatch)``
"""

from __future__ import annotations

import time

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.errors import make_internal_error
from sox_protocol.core.middleware.protocol import CallNext
from sox_protocol.core.ports.backing_store import BackingStore


class StoreDispatchMiddleware:
    """Terminal middleware that dispatches to the BackingStore.

    This middleware calls ``call_next`` after its own logic, but in the default
    chain it IS the terminal — callers must pass a no-op terminal or use it as
    the terminal directly.

    For use as the terminal in :class:`~sox_protocol.core.middleware.pipeline.Pipeline`,
    pass it as both the last middleware and as the terminal::

        pipeline = Pipeline(middlewares=[..., store_mw], terminal=store_mw)

    Args:
        store: The configured :class:`~sox_protocol.core.ports.backing_store.BackingStore`.

    Attributes:
        name: Always ``'store_dispatch'``.
        must_run_before: Empty — this is the terminal.
        must_run_after: Empty — ordering is controlled by other middlewares.
    """

    name: str = "store_dispatch"
    must_run_before: tuple[str, ...] = ()
    must_run_after: tuple[str, ...] = ()

    def __init__(self, store: BackingStore) -> None:
        self._store = store

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: CallNext,
    ) -> dict[str, object]:
        """Dispatch *ctx.operation* to the backing store.

        Supported operations: ``send``, ``recv``, ``subscribe``,
        ``list_channels``.  Unsupported operations return an
        ``internal_error`` sox-error.

        Args:
            ctx: The per-call context.
            call_next: Ignored by the terminal; present for protocol
                conformance.

        Returns:
            Operation output dict conforming to the relevant output schema.
        """
        op = ctx.operation
        inp = ctx.input

        if op == "send":
            channel = str(inp.get("channel", ""))
            sender = str(inp.get("sender", ctx.agent_id or ""))
            body = inp.get("body", {})
            if not isinstance(body, dict):
                body = {}
            correlation_id = inp.get("correlation_id")
            corr_str = str(correlation_id) if correlation_id is not None else None
            message_id, sent_at = await self._store.send(
                channel, sender, body, corr_str
            )
            return {
                "message_id": message_id,
                "channel": channel,
                "sent_at": sent_at,
            }

        elif op == "recv":
            agent_id = str(inp.get("agent_id", ctx.agent_id or ""))
            channels_raw = inp.get("channels")
            channels: list[str] | None = None
            if isinstance(channels_raw, list):
                channels = [str(c) for c in channels_raw]
            max_messages_raw = inp.get("max_messages", 50)
            if isinstance(max_messages_raw, (int, float, str)):
                max_messages = int(max_messages_raw)
            else:
                max_messages = 50
            messages = await self._store.recv(agent_id, channels, max_messages)
            # Attach seq (position in messages list + 1) if not already present.
            for i, msg in enumerate(messages):
                if "seq" not in msg:
                    msg["seq"] = i + 1
            return {"drained_at": time.time(), "messages": messages}

        elif op == "subscribe":
            agent_id = str(inp.get("agent_id", ctx.agent_id or ""))
            pattern = str(inp.get("pattern", ""))
            matched = await self._store.subscribe(agent_id, pattern)
            return {"subscribed": True, "matched_channels": matched}

        elif op == "list_channels":
            since_raw = inp.get("since")
            since: float | None = (
                float(since_raw)
                if isinstance(since_raw, (int, float, str))
                else None
            )
            channels_list = await self._store.list_channels(since)
            return {"channels": channels_list}

        else:
            return make_internal_error(f"Unsupported operation: {op!r}")
