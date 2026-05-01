# SPDX-License-Identifier: Apache-2.0
"""SOX MCP tool implementations.

All 15 tool handlers registered here dispatch exclusively through
:class:`~sox_protocol.core.middleware.pipeline.Pipeline` rather than calling
the :class:`~sox_protocol.core.ports.backing_store.BackingStore` directly.
The pipeline is constructed once in the lifespan (``server.py``) and stashed
in ``lifespan_result["pipeline"]``.

Every handler:

1. Reads ``pipeline`` and ``agent_id`` from the lifespan context.
2. Builds a per-call :class:`~sox_protocol.core.identity.envelope.SignedRequest`
   via :func:`~sox_protocol.core.mcp_server._credential.resolve_credential`
   (the v1 transitional credential path).
3. Calls ``await pipeline.dispatch(operation, input_dict, connection_id, metadata)``
   and returns the result directly.

The pipeline carries auth verification (AuthMiddleware) and persistence
(StoreDispatchMiddleware) as its middleware chain, so each tool call is
fully mediated by the middleware stack.

``channels__recv`` semantics
----------------------------
``channels__recv`` retains its direct listener drain because it reads from the
background listener's in-process queue rather than dispatching an operation
to the backing store.  The underlying store operation is ``"recv"`` but the
MCP implementation drains the local buffer maintained by the Listener task.
The pipeline dispatch for ``recv`` is used ONLY to pass through auth and
middleware; the actual message list comes from the listener queue.

``channels__collect`` semantics
--------------------------------
``channels__collect`` in v1 is a planned-but-stub operation that returns an
empty ``{"received": [], "missing": [], "timed_out": True}`` response.
Per implementation-plan.json: for phase 02, each collect iteration dispatches
ONCE through the pipeline (matching store_dispatch's ``channels_collect``
handling).  The multi-message loop structure is preserved here so that when
the store implements collect, it can be extended without a tools.py rewrite.
Currently a single dispatch is made since the stub returns immediately.

This module MUST NOT import from ``sox_protocol.adapters`` (import-linter
enforced).
"""

from __future__ import annotations

import re
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastmcp import Context, FastMCP

from sox_protocol.core.identity.envelope import SignedRequest
from sox_protocol.core.mcp_server._credential import resolve_credential
from sox_protocol.core.mcp_server.listener import Listener
from sox_protocol.core.middleware.pipeline import Pipeline

# Reject wildcard subscriptions on reserved prefixes dm/ and group/.
_RESERVED_WILDCARD: re.Pattern[str] = re.compile(r"^(dm|group)/.*\*")


def _get_pipeline_and_credential(
    lc: dict[str, Any],
    operation: str,
    body: dict[str, object] | None = None,
) -> tuple[Pipeline, str, SignedRequest]:
    """Extract pipeline, agent_id, and a fresh credential from lifespan context.

    Args:
        lc: The lifespan context dict (``ctx.fastmcp._lifespan_result``).
        operation: The SOX operation name for signing.
        body: Optional body dict used to compute the SignedRequest body hash.

    Returns:
        Tuple of (pipeline, agent_id, signed_request).
    """
    pipeline: Pipeline = lc["pipeline"]
    agent_id: str = lc["agent_id"]
    private_key: Ed25519PrivateKey = lc["_private_key"]
    credential = resolve_credential(agent_id, private_key, operation, body)
    return pipeline, agent_id, credential


def register_tools(mcp: FastMCP[Any]) -> None:
    """Register all 15 SOX tools on *mcp*.

    Called once from ``server.py`` during server construction so the
    tools share the same ``FastMCP`` instance and therefore the same
    lifespan context.

    All handlers dispatch through ``pipeline.dispatch`` rather than
    calling the backing store directly.

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
        input_dict: dict[str, object] = {
            "channel": channel,
            "body": body,
            "correlation_id": correlation_id,
        }
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "send", input_dict)
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        result = await pipeline.dispatch(
            "send",
            input_dict,
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )
        # Normalize: store_dispatch includes "channel" in the send response but
        # spec/schemas/tools/send.output.schema.json does not allow it (additionalProperties: false).
        if isinstance(result, dict):
            result.pop("channel", None)
        return result

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
        # Drain the in-process listener queue directly (no store round-trip).
        listener: Listener = lc["listener"]
        buffered = listener.drain(max_messages=max_messages)

        # Optional channel filter — re-queue unmatched messages.
        if channels is not None:
            channel_set = set(channels)
            kept: list[dict[str, object]] = []
            requeue: list[dict[str, object]] = []
            for msg in buffered:
                if msg.get("channel") in channel_set:
                    kept.append(msg)
                else:
                    requeue.append(msg)
            for msg in reversed(requeue):
                listener.queue.put_nowait(msg)
            buffered = kept

        # TODO(v1): ancestor expansion not yet implemented; thread_depth accepted but ignored beyond 0
        if not include_meta:
            for msg in buffered:
                msg.pop("_meta", None)

        # Pass through pipeline for auth + middleware (input carries agent_id
        # for the recv op so AuthMiddleware can bind ctx.agent_id).
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "recv")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        await pipeline.dispatch(
            "recv",
            {"agent_id": agent_id, "channels": channels, "max_messages": max_messages},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )

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
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "subscribe")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        result = await pipeline.dispatch(
            "subscribe",
            {"agent_id": agent_id, "pattern": pattern},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )
        # Normalize: store_dispatch returns {"subscribed": True, "matched_channels": [...]}
        # but spec/schemas/tools/subscribe.output.schema.json requires {"subscribed": [...]}.
        if isinstance(result, dict) and isinstance(result.get("matched_channels"), list):
            return {"subscribed": result["matched_channels"]}
        return result

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
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "unsubscribe")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        result = await pipeline.dispatch(
            "unsubscribe",
            {"agent_id": agent_id, "patterns": patterns},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )
        # Normalize: store_dispatch returns {"removed": [...], "pending_cleared": int}
        # but the tool contract uses {"unsubscribed": [...], "pending_cleared": int}.
        if isinstance(result, dict) and "removed" in result and "unsubscribed" not in result:
            return {"unsubscribed": result["removed"], "pending_cleared": result.get("pending_cleared", 0)}
        return result

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
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "channels_ack")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        return await pipeline.dispatch(
            "channels_ack",
            {"agent_id": agent_id, "message_id": message_id, "status": status, "reason": reason},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )

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
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "channels_heartbeat")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        return await pipeline.dispatch(
            "channels_heartbeat",
            {"agent_id": agent_id, "status": status, "ttl": ttl},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )

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
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "list_agents")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        return await pipeline.dispatch(
            "list_agents",
            {"agent_id": agent_id, "status_filter": status_filter, "namespace": namespace},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )

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
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "replay")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        return await pipeline.dispatch(
            "replay",
            {"channel": channel, "since": since, "until": until, "limit": limit},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )

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
        # Phase 02 decision: dispatch ONCE through pipeline matching
        # store_dispatch's channels_collect handling.  The multi-iteration
        # loop is preserved here for forward-compat (when store implements
        # real collect, each recv attempt will call dispatch in a loop).
        # Currently a single dispatch suffices because the underlying store
        # recv returns an empty list immediately.
        # See implementation-plan.json risk R4 and phase 02 collect semantics.
        #
        # store_dispatch maps channels_collect to a store.recv call and returns
        # {"drained_at": ..., "messages": [...]}.  The tool contract for collect
        # is {"received": [...], "missing": [...], "timed_out": bool}; the
        # normalization below converts between the two shapes.
        lc = ctx.fastmcp._lifespan_result or {}
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "channels_collect")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        result = await pipeline.dispatch(
            "channels_collect",
            {
                "agent_id": agent_id,
                "channels": [reply_to],
                "max_messages": count,
            },
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )
        # Normalize store_dispatch's recv-shaped response to collect contract.
        if isinstance(result, dict) and "messages" in result and "timed_out" not in result:
            received = result.get("messages", [])
            if not isinstance(received, list):
                received = []
            timed_out = len(received) < count
            return {"received": received, "missing": [], "timed_out": timed_out}
        return result

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
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "group_create")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        return await pipeline.dispatch(
            "group_create",
            # store_dispatch reads "creator_id" for this operation.
            {"creator_id": agent_id, "group_id": group_id},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )

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
        pipeline, caller_id, credential = _get_pipeline_and_credential(lc, "group_invite")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        return await pipeline.dispatch(
            "group_invite",
            # store_dispatch reads "inviter_id" (caller) and "invitee_id" (target agent).
            {"inviter_id": caller_id, "group_id": group_id, "invitee_id": agent_id},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )

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
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "group_join")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        return await pipeline.dispatch(
            "group_join",
            {"agent_id": agent_id, "group_id": group_id},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )

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
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "group_leave")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        return await pipeline.dispatch(
            "group_leave",
            {"agent_id": agent_id, "group_id": group_id},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )

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
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "group_list_members")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        return await pipeline.dispatch(
            "group_list_members",
            {"agent_id": agent_id, "group_id": group_id},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )

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
        pipeline, agent_id, credential = _get_pipeline_and_credential(lc, "list_channels")
        connection_id = str(ctx.client_id) if hasattr(ctx, "client_id") else "stdio"
        result = await pipeline.dispatch(
            "list_channels",
            {},
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )
        # Inject SOX protocol version negotiation block required by CONTRACTS.md §8.
        if isinstance(result, dict) and "_sox_protocol" not in result:
            result["_sox_protocol"] = {
                "server_version": "1.0",
                "supported_versions": ["1.0"],
                "min_client_version": "1.0",
            }
        return result
