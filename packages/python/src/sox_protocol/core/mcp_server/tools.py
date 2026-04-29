"""SOX MCP tool implementations.

The four tools registered here implement the SOX wire protocol
(``CONTRACTS.md §5``).  Each tool:

1. Receives its arguments via FastMCP's normal parameter injection.
2. Accesses the ``BackingStore`` and ``Listener`` through the FastMCP
   ``Context.lifespan_context`` dict (keys ``"store"`` and ``"listener"``).
3. Returns a plain ``dict`` whose shape matches the corresponding
   ``spec/schemas/tools/*.output.schema.json``.

Tool semantics summary
-----------------------
``channels__send``
    Non-blocking.  Persists the message in the backing store and returns
    ``{sent_at, message_id}`` immediately.

``channels__recv``
    **Non-blocking (timeout=0 semantics).**  Drains the listener's local
    in-memory buffer.  Returns ``{drained_at, messages}`` immediately even
    when the buffer is empty.

``channels__subscribe``
    Registers a subscription pattern in the backing store.  Idempotent.
    Returns ``{subscribed: [currently-matching channels]}``.

``channels__list_channels``
    Returns ``{channels: [...], protocol_version: "1.0"}``.  The
    ``protocol_version`` field lets adapters detect major-version mismatches
    (``CONTRACTS.md §8``).

This module MUST NOT import from ``sox_protocol.adapters`` (import-linter
enforced).
"""

from __future__ import annotations

import time
from typing import Any

from fastmcp import Context, FastMCP

from sox_protocol.core.mcp_server.listener import Listener
from sox_protocol.core.ports.backing_store import BackingStore

# Protocol version announced in list_channels.
_PROTOCOL_VERSION: str = "1.0"


def register_tools(mcp: FastMCP[Any]) -> None:
    """Register all four SOX tools on *mcp*.

    Called once from ``server.py`` during server construction so the
    tools share the same ``FastMCP`` instance and therefore the same
    lifespan context.

    Args:
        mcp: A ``FastMCP`` instance that has not yet started.
    """

    # ------------------------------------------------------------------
    # channels__send
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__send")
    async def channels__send(
        channel: str,
        body: dict[str, Any],
        ctx: Context,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to a channel.

        Non-blocking: returns as soon as the message is durably accepted
        by the backing store.

        Args:
            channel: Target channel name (1–256 chars).
            body: Opaque JSON-object payload.
            correlation_id: Optional caller-supplied correlation token
                (max 128 chars, or null).
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"sent_at": <float>, "message_id": <str>}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agent_id: str = lc["agent_id"]
        message_id, sent_at = await store.send(channel, agent_id, body, correlation_id)
        return {"sent_at": sent_at, "message_id": message_id}

    # ------------------------------------------------------------------
    # channels__recv
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__recv")
    async def channels__recv(
        ctx: Context,
        channels: list[str] | None = None,
        max_messages: int = 50,
    ) -> dict[str, Any]:
        """Drain the local message buffer (non-blocking).

        Returns immediately with whatever messages have accumulated in the
        background listener's queue since the last drain.  If the queue
        is empty, returns ``{"messages": [], "drained_at": <now>}``.

        The listener task pushes messages into the queue continuously in
        the background; this call never blocks waiting for new messages.

        Args:
            channels: Optional list of channel names to filter.  When
                ``None`` (or omitted), all buffered messages are returned
                regardless of channel.  **Note:** channel-level filtering
                here is done on the already-buffered messages; messages
                not matching the filter remain in the queue.
            max_messages: Maximum number of messages to return (1–1000,
                default 50).
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"drained_at": <float>, "messages": [...]}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        listener: Listener = lc["listener"]

        # Drain the unbounded local buffer synchronously.
        buffered = listener.drain(max_messages=max_messages)

        # Optional channel filter (messages not matching stay... but they
        # have already been popped from the queue; re-queue them at front
        # isn't safe without a deque.  Per spec, channels filter applies
        # to what the recv returns — unmatched messages are discarded from
        # the local buffer.  The watch loop pushes them again if undelivered
        # in the backing store, but they are already buffered here, so we
        # must decide: drop or re-queue.
        #
        # Spec §5.2: "If channels is null, drains all subscribed channels."
        # The listener already respects subscriptions; the channels param
        # is an additional filter.  We keep only matching messages and
        # re-queue the rest so they are not lost.
        if channels is not None:
            channel_set = set(channels)
            kept: list[dict[str, object]] = []
            requeue: list[dict[str, object]] = []
            for msg in buffered:
                if msg.get("channel") in channel_set:
                    kept.append(msg)
                else:
                    requeue.append(msg)
            # Re-insert unmatched messages at the front (best-effort LIFO
            # prepend: put them back in original order by iterating in
            # reverse and using put_nowait; the queue is unbounded so this
            # never blocks).
            for msg in reversed(requeue):
                listener.queue.put_nowait(msg)
            buffered = kept

        drained_at = time.time()
        return {"drained_at": drained_at, "messages": buffered}

    # ------------------------------------------------------------------
    # channels__subscribe
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__subscribe")
    async def channels__subscribe(
        pattern: str,
        ctx: Context,
    ) -> dict[str, Any]:
        """Subscribe to channels matching a pattern.

        Registers the calling agent's interest in channels matching
        *pattern*.  Subscription persists in the backing store (survives
        server restarts).  Idempotent.

        Pattern syntax: ``*`` glob (``ticket:ENGI-*``) or exact match.

        Args:
            pattern: Channel name pattern (1–256 chars).
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"subscribed": [<currently-matching channel names>]}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agent_id: str = lc["agent_id"]
        matched = await store.subscribe(agent_id, pattern)
        return {"subscribed": matched}

    # ------------------------------------------------------------------
    # channels__list_channels
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__list_channels")
    async def channels__list_channels(ctx: Context) -> dict[str, Any]:
        """List all discoverable channels.

        Returns channels that have at least one subscriber or at least one
        message stored in the last 24 hours, plus the protocol version of
        this MCP server node.  Adapters use ``protocol_version`` to detect
        major-version mismatches (``CONTRACTS.md §8``).

        Args:
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"channels": [...], "protocol_version": "1.0"}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        raw_channels = await store.list_channels()
        return {
            "channels": raw_channels,
            "protocol_version": _PROTOCOL_VERSION,
        }
