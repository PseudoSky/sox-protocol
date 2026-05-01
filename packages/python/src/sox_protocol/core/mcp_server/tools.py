# SPDX-License-Identifier: Apache-2.0
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

import re
import time
from typing import Any

from fastmcp import Context, FastMCP

from sox_protocol.core.mcp_server.listener import Listener
from sox_protocol.core.ports.backing_store import BackingStore

# Reject wildcard subscriptions on reserved prefixes dm/ and group/.
_RESERVED_WILDCARD: re.Pattern[str] = re.compile(r"^(dm|group)/.*\*")


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
            ``{"sent_at": <float>, "message_id": <str>, "seq": <int>, "backpressure": {...}}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agent_id: str = lc["agent_id"]
        message_id, sent_at, seq, backpressure = await store.send(
            channel, agent_id, body, correlation_id
        )
        return {
            "sent_at": sent_at,
            "message_id": message_id,
            "seq": seq,
            "backpressure": {
                "queue_depth": backpressure.queue_depth,
                "threshold": backpressure.threshold,
                "state": backpressure.state,
            },
        }

    # ------------------------------------------------------------------
    # channels__recv
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__recv")
    async def channels__recv(
        ctx: Context,
        channels: list[str] | None = None,
        max_messages: int = 50,
        thread_depth: int = 0,
        include_meta: bool = True,
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
            thread_depth: Ancestor expansion depth (0 = none, -1 = full).
                Accepted but not expanded in v1; ancestor expansion is not
                yet implemented.
            include_meta: When ``False``, strip ``_meta`` from every
                returned message.  When ``True`` (default), ``_meta`` is
                included as-is (currently ``null`` from the store).
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

        # TODO(v1): ancestor expansion not yet implemented; thread_depth accepted but ignored beyond 0
        if not include_meta:
            for msg in buffered:
                msg.pop("_meta", None)

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
        if _RESERVED_WILDCARD.match(pattern):
            raise ValueError(
                f"Wildcard subscriptions on reserved prefixes 'dm/' and 'group/' are forbidden. "
                f"Use an exact channel name or a group lifecycle verb. Got: {pattern!r}"
            )
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agent_id: str = lc["agent_id"]
        matched = await store.subscribe(agent_id, pattern)
        return {"subscribed": matched}

    # ------------------------------------------------------------------
    # channels__unsubscribe
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__unsubscribe")
    async def channels__unsubscribe(patterns: list[str], ctx: Context) -> dict[str, Any]:
        """Remove subscriptions matching patterns for the calling agent.

        Args:
            patterns: List of subscription patterns to remove.
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"unsubscribed": [removed patterns], "pending_cleared": int}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agent_id: str = lc["agent_id"]
        removed, pending_cleared = await store.unsubscribe(agent_id, patterns)
        return {"unsubscribed": removed, "pending_cleared": pending_cleared}

    # ------------------------------------------------------------------
    # channels__ack
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__ack")
    async def channels__ack(
        message_id: str,
        status: str,
        ctx: Context,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Acknowledge or NACK a message (control-plane only).

        Args:
            message_id: The message to acknowledge.
            status: One of received/processing/done/nack.
            reason: Optional reason (for nack).
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"message_id": str, "status": str, "acked_at": float}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agent_id: str = lc["agent_id"]
        result = await store.ack(agent_id, message_id, status, reason)
        return result

    # ------------------------------------------------------------------
    # channels__heartbeat
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__heartbeat")
    async def channels__heartbeat(
        status: str,
        ctx: Context,
        ttl: int | None = None,
    ) -> dict[str, Any]:
        """Update agent liveness record.

        Args:
            status: One of online/busy/offline.
            ttl: Optional TTL in seconds (default 30).
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"agent_id": str, "status": str, "recorded_at": float, "expires_at": float}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agent_id: str = lc["agent_id"]
        result = await store.heartbeat(agent_id, status, ttl)
        return result

    # ------------------------------------------------------------------
    # channels__list_agents
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__list_agents")
    async def channels__list_agents(
        ctx: Context,
        status_filter: list[str] | None = None,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """Return liveness table for all known agents.

        Args:
            status_filter: Optional list of statuses to filter by.
            namespace: Optional agent_id prefix filter.
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"agents": [...]}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agents = await store.list_agents(status_filter, namespace)
        return {"agents": agents}

    # ------------------------------------------------------------------
    # channels__replay
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__replay")
    async def channels__replay(
        channel: str,
        ctx: Context,
        since: int = 0,
        until: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Replay messages from a channel since a given seq cursor.

        Args:
            channel: Channel name to replay from.
            since: Seq number to replay from (inclusive, default 0).
            until: Seq number to replay until (inclusive, default None).
            limit: Maximum messages to return (default 100).
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"messages": [...], "has_more": bool}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        messages, has_more = await store.replay(channel, since, until, limit)
        return {"messages": messages, "has_more": has_more}

    # ------------------------------------------------------------------
    # channels__collect  (planned — not implemented in v1)
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__collect")
    async def channels__collect(
        reply_to: str,
        count: int,
        timeout: float,
        ctx: Context,
        status_filter: list[str] | None = None,
    ) -> dict[str, Any]:
        """Collect N replies on a channel within a timeout window.

        Args:
            reply_to: Channel to collect replies from.
            count: Number of replies to wait for.
            timeout: Timeout in seconds.
            status_filter: Optional status filter.
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"received": [], "missing": [], "timed_out": bool}``
        """
        # planned: not implemented in v1
        return {"received": [], "missing": [], "timed_out": True}

    # ------------------------------------------------------------------
    # group__create
    # ------------------------------------------------------------------

    @mcp.tool(name="group__create")
    async def group__create(
        ctx: Context,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new group channel.

        Args:
            group_id: Optional group identifier (bare name, no 'group/' prefix).
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"group_id": str, "created_at": float}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agent_id: str = lc["agent_id"]
        result = await store.group_create(agent_id, group_id)
        return result

    # ------------------------------------------------------------------
    # group__invite
    # ------------------------------------------------------------------

    @mcp.tool(name="group__invite")
    async def group__invite(
        group_id: str,
        agent_id: str,
        ctx: Context,
    ) -> dict[str, Any]:
        """Invite an agent to a group.

        Args:
            group_id: Full group channel name (e.g. 'group/eng').
            agent_id: Agent to invite.
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"invited": bool, "agent_id": str, "invited_at": float}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        caller_id: str = lc["agent_id"]
        result = await store.group_invite(caller_id, group_id, agent_id)
        return result

    # ------------------------------------------------------------------
    # group__join
    # ------------------------------------------------------------------

    @mcp.tool(name="group__join")
    async def group__join(
        group_id: str,
        ctx: Context,
    ) -> dict[str, Any]:
        """Accept a group invitation and join the group.

        Args:
            group_id: Full group channel name (e.g. 'group/eng').
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"joined": bool, "group_id": str, "member_count": int, "joined_at": float}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agent_id: str = lc["agent_id"]
        result = await store.group_join(agent_id, group_id)
        return result

    # ------------------------------------------------------------------
    # group__leave
    # ------------------------------------------------------------------

    @mcp.tool(name="group__leave")
    async def group__leave(
        group_id: str,
        ctx: Context,
    ) -> dict[str, Any]:
        """Leave a group.

        Args:
            group_id: Full group channel name (e.g. 'group/eng').
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"left": bool, "group_id": str, "left_at": float}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agent_id: str = lc["agent_id"]
        result = await store.group_leave(agent_id, group_id)
        return result

    # ------------------------------------------------------------------
    # group__list_members
    # ------------------------------------------------------------------

    @mcp.tool(name="group__list_members")
    async def group__list_members(
        group_id: str,
        ctx: Context,
    ) -> dict[str, Any]:
        """List members of a group.

        Args:
            group_id: Full group channel name (e.g. 'group/eng').
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"group_id": str, "members": [...]}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        agent_id: str = lc["agent_id"]
        result = await store.group_list_members(agent_id, group_id)
        return result

    # ------------------------------------------------------------------
    # channels__list_channels
    # ------------------------------------------------------------------

    @mcp.tool(name="channels__list_channels")
    async def channels__list_channels(ctx: Context) -> dict[str, Any]:
        """List all discoverable channels.

        Returns channels that have at least one subscriber or at least one
        message stored in the last 24 hours, plus version negotiation metadata
        in the ``_sox_protocol`` block.  Clients MUST read ``_sox_protocol``
        on first call and fail-fast if their supported version range does not
        intersect with the server's (``CONTRACTS.md §8``).

        Args:
            ctx: FastMCP context (injected automatically).

        Returns:
            ``{"channels": [...], "_sox_protocol": {"server_version": "1.0", ...}}``
        """
        lc = ctx.fastmcp._lifespan_result or {}
        store: BackingStore = lc["store"]
        raw_channels = await store.list_channels()
        return {
            "channels": raw_channels,
            "_sox_protocol": {
                "server_version": "1.0",
                "supported_versions": ["1.0"],
                "min_client_version": "1.0",
            },
        }
