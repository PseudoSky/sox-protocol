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
    kind: str = "store"
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

        Supported operations: all 15 SOX v1 MUST operations.
        Unsupported operations return an ``internal_error`` sox-error.

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
            message_id, sent_at, seq, backpressure = await self._store.send(
                channel, sender, body, corr_str
            )
            return {
                "message_id": message_id,
                "channel": channel,
                "sent_at": sent_at,
                "seq": seq,
                "backpressure": {
                    "queue_depth": backpressure.queue_depth,
                    "threshold": backpressure.threshold,
                    "state": backpressure.state,
                },
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

        elif op == "unsubscribe":
            agent_id = str(inp.get("agent_id", ctx.agent_id or ""))
            patterns_raw = inp.get("patterns", [])
            patterns: list[str] = (
                [str(p) for p in patterns_raw]
                if isinstance(patterns_raw, list)
                else []
            )
            removed, pending_cleared = await self._store.unsubscribe(agent_id, patterns)
            return {"removed": removed, "pending_cleared": pending_cleared}

        elif op == "list_channels":
            since_raw = inp.get("since")
            since: float | None = (
                float(since_raw)
                if isinstance(since_raw, (int, float, str))
                else None
            )
            channels_list = await self._store.list_channels(since)
            return {"channels": channels_list}

        elif op == "list_agents":
            status_filter_raw = inp.get("status_filter")
            status_filter: list[str] | None = (
                [str(s) for s in status_filter_raw]
                if isinstance(status_filter_raw, list)
                else None
            )
            namespace_raw = inp.get("namespace")
            namespace: str | None = str(namespace_raw) if namespace_raw is not None else None
            agents = await self._store.list_agents(status_filter, namespace)
            return {"agents": agents}

        elif op == "channels_ack":
            agent_id = str(inp.get("agent_id", ctx.agent_id or ""))
            message_id = str(inp.get("message_id", ""))
            status = str(inp.get("status", "ack"))
            reason_raw = inp.get("reason")
            reason: str | None = str(reason_raw) if reason_raw is not None else None
            return await self._store.ack(agent_id, message_id, status, reason)

        elif op == "channels_heartbeat":
            agent_id = str(inp.get("agent_id", ctx.agent_id or ""))
            status = str(inp.get("status", "active"))
            ttl_raw = inp.get("ttl")
            ttl: int | None = int(ttl_raw) if isinstance(ttl_raw, (int, float)) else None
            return await self._store.heartbeat(agent_id, status, ttl)

        elif op == "channels_collect":
            agent_id = str(inp.get("agent_id", ctx.agent_id or ""))
            channels_raw = inp.get("channels")
            collect_channels: list[str] | None = (
                [str(c) for c in channels_raw]
                if isinstance(channels_raw, list)
                else None
            )
            max_messages_raw = inp.get("max_messages", 50)
            max_messages_c: int = (
                int(max_messages_raw)
                if isinstance(max_messages_raw, (int, float, str))
                else 50
            )
            messages_c = await self._store.recv(agent_id, collect_channels, max_messages_c)
            for i, msg in enumerate(messages_c):
                if "seq" not in msg:
                    msg["seq"] = i + 1
            return {"drained_at": time.time(), "messages": messages_c}

        elif op == "replay":
            channel = str(inp.get("channel", ""))
            since_seq_raw = inp.get("since", 0)
            since_seq: int = (
                int(since_seq_raw) if isinstance(since_seq_raw, (int, float)) else 0
            )
            until_raw = inp.get("until")
            until: int | None = (
                int(until_raw) if isinstance(until_raw, (int, float)) else None
            )
            limit_raw = inp.get("limit", 100)
            limit: int = int(limit_raw) if isinstance(limit_raw, (int, float)) else 100
            replay_msgs, has_more = await self._store.replay(
                channel, since_seq, until, limit
            )
            return {"messages": replay_msgs, "has_more": has_more}

        elif op == "group_create":
            creator_id = str(inp.get("creator_id", ctx.agent_id or ""))
            group_id_raw = inp.get("group_id")
            group_id_str: str | None = (
                str(group_id_raw) if group_id_raw is not None else None
            )
            return await self._store.group_create(creator_id, group_id_str)

        elif op == "group_invite":
            inviter_id = str(inp.get("inviter_id", ctx.agent_id or ""))
            group_id = str(inp.get("group_id", ""))
            invitee_id = str(inp.get("invitee_id", ""))
            return await self._store.group_invite(inviter_id, group_id, invitee_id)

        elif op == "group_join":
            agent_id = str(inp.get("agent_id", ctx.agent_id or ""))
            group_id = str(inp.get("group_id", ""))
            return await self._store.group_join(agent_id, group_id)

        elif op == "group_leave":
            agent_id = str(inp.get("agent_id", ctx.agent_id or ""))
            group_id = str(inp.get("group_id", ""))
            return await self._store.group_leave(agent_id, group_id)

        elif op == "group_list_members":
            agent_id = str(inp.get("agent_id", ctx.agent_id or ""))
            group_id = str(inp.get("group_id", ""))
            return await self._store.group_list_members(agent_id, group_id)

        else:
            return make_internal_error(f"Unsupported operation: {op!r}")
