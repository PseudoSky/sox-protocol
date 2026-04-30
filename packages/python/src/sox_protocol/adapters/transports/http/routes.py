# SPDX-License-Identifier: Apache-2.0
"""Operation route handlers for the HTTP transport.

Registers one POST handler per SOX operation at ``/v1/ops/<operation>``.
Each handler:
1. Resolves agent identity from the Authorization header.
2. Validates the request body against the operation's input schema.
3. Dispatches to the backing store.
4. Returns the operation output as JSON.

Spec reference: ``spec/operations/*.json``
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from sox_protocol.adapters.transports.http.auth import IdentityResolver, resolve_agent_id
from sox_protocol.adapters.transports.http.errors import (
    internal_error_response,
    sox_error_response,
    validation_error_response,
)
from sox_protocol.adapters.transports.http.liveness import LivenessStore
from sox_protocol.core.ports.backing_store import BackingStore

_PROTOCOL_VERSION = "1.0"


def _require_fields(body: object, *fields: str) -> str | None:
    """Return an error message if any required field is missing from *body*.

    Args:
        body: The parsed request body dict.
        *fields: Required field names.

    Returns:
        Error message string if validation fails, else ``None``.
    """
    if not isinstance(body, dict):
        return "Request body must be a JSON object"
    for f in fields:
        if f not in body:
            return f"Missing required field: {f!r}"
    return None


def register_operation_routes(
    router: APIRouter,
    store: BackingStore,
    resolver: IdentityResolver,
    liveness: LivenessStore,
) -> None:
    """Register all SOX operation handlers on *router*.

    Args:
        router: The FastAPI APIRouter to register routes on.
        store: The backing store instance for persistence.
        resolver: Identity resolver for bearer token auth.
        liveness: Liveness store for heartbeat and list_agents.
    """

    # ------------------------------------------------------------------
    # Helper: authenticate and parse body
    # ------------------------------------------------------------------

    async def _auth_and_body(request: Request) -> tuple[str, Any, JSONResponse | None]:
        agent_id, err = resolve_agent_id(request, resolver)
        if err is not None:
            return "", None, err
        try:
            body: Any = await request.json()
        except Exception:
            body = {}
        return agent_id, body, None

    # ------------------------------------------------------------------
    # send
    # ------------------------------------------------------------------

    @router.post("/v1/ops/send")
    async def op_send(request: Request) -> JSONResponse:
        """Send a message to a channel."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        val_err = _require_fields(body, "channel", "body")
        if val_err:
            return validation_error_response(val_err)
        channel: str = str(body["channel"])
        msg_body: dict[str, object] = body["body"] if isinstance(body["body"], dict) else {}
        correlation_id: str | None = body.get("correlation_id")
        try:
            async with store._lock:  # type: ignore[attr-defined]
                seq = (
                    sum(1 for m in store._messages if m.channel == channel) + 1  # type: ignore[attr-defined, misc]
                )
                sent_at = time.time()
                from sox_protocol.adapters.backing_stores.memory.store import (
                    _StoredMessage,
                )
                msg_id = store._next_id  # type: ignore[attr-defined]
                store._next_id += 1  # type: ignore[attr-defined]
                import copy
                msg = _StoredMessage(
                    id=msg_id,
                    channel=channel,
                    sender=agent_id,
                    body=copy.deepcopy(msg_body),
                    correlation_id=correlation_id,
                    sent_at=sent_at,
                )
                msg.seq = seq  # type: ignore[attr-defined]
                msg.reply_to = body.get("reply_to")  # type: ignore[attr-defined]
                store._messages.append(msg)  # type: ignore[attr-defined]
            store._new_message_event.set()  # type: ignore[attr-defined]
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(
            status_code=200,
            content={
                "sent_at": sent_at,
                "message_id": str(msg_id),
                "seq": seq,
                "backpressure": {
                    "queue_depth": 0,
                    "threshold": 1000,
                    "state": "ok",
                },
            },
        )

    # ------------------------------------------------------------------
    # recv
    # ------------------------------------------------------------------

    @router.post("/v1/ops/recv")
    async def op_recv(request: Request) -> JSONResponse:
        """Drain pending messages for the authenticated agent."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        max_messages: int = int(body.get("max_messages", 50)) if isinstance(body, dict) else 50
        channel_filter: list[str] | None = (
            body.get("channels") if isinstance(body, dict) else None
        )
        if isinstance(channel_filter, list):
            channel_filter = [str(c) for c in channel_filter]
        try:
            msgs = await store.recv(agent_id, channel_filter, max_messages)
        except Exception as exc:
            return internal_error_response(str(exc))

        # Augment with seq / reply_to from stored message attributes
        result_msgs: list[dict[str, object]] = []
        for wire in msgs:
            wire_copy = dict(wire)
            if "seq" not in wire_copy:
                async with store._lock:  # type: ignore[attr-defined]
                    for sm in store._messages:  # type: ignore[attr-defined]
                        if str(sm.id) == wire_copy.get("message_id"):
                            wire_copy["seq"] = getattr(sm, "seq", 1)
                            wire_copy["reply_to"] = getattr(sm, "reply_to", None)
                            break
            result_msgs.append(wire_copy)

        return JSONResponse(
            status_code=200,
            content={"drained_at": time.time(), "messages": result_msgs},
        )

    # ------------------------------------------------------------------
    # subscribe
    # ------------------------------------------------------------------

    @router.post("/v1/ops/subscribe")
    async def op_subscribe(request: Request) -> JSONResponse:
        """Register a subscription pattern for the authenticated agent."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        val_err = _require_fields(body, "pattern")
        if val_err:
            return validation_error_response(val_err)
        try:
            matched = await store.subscribe(agent_id, str(body["pattern"]))
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(status_code=200, content={"subscribed": matched})

    # ------------------------------------------------------------------
    # unsubscribe
    # ------------------------------------------------------------------

    @router.post("/v1/ops/unsubscribe")
    async def op_unsubscribe(request: Request) -> JSONResponse:
        """Remove subscription patterns for the authenticated agent."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        val_err = _require_fields(body, "patterns")
        if val_err:
            return validation_error_response(val_err)
        patterns: list[str] = [str(p) for p in body["patterns"]]
        removed: list[str] = []
        try:
            async with store._lock:  # type: ignore[attr-defined]
                existing = store._subscriptions.get(agent_id, [])  # type: ignore[attr-defined]
                new_patterns: list[str] = []
                import fnmatch
                for p in existing:
                    if p in patterns:
                        removed.append(p)
                        for msg in store._messages:  # type: ignore[attr-defined]
                            if (
                                agent_id not in msg.delivered_to
                                and fnmatch.fnmatchcase(msg.channel, p)
                            ):
                                msg.delivered_to.add(agent_id)
                    else:
                        new_patterns.append(p)
                store._subscriptions[agent_id] = new_patterns  # type: ignore[attr-defined]
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(status_code=200, content={"unsubscribed": removed})

    # ------------------------------------------------------------------
    # list_channels
    # ------------------------------------------------------------------

    @router.post("/v1/ops/list_channels")
    async def op_list_channels(request: Request) -> JSONResponse:
        """Return known channels."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        since: float | None = (
            float(body["since"]) if isinstance(body, dict) and "since" in body else None
        )
        try:
            channels = await store.list_channels(since)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(
            status_code=200,
            content={
                "channels": channels,
                "protocol_version": _PROTOCOL_VERSION,
                "_sox_protocol": {
                    "server_version": _PROTOCOL_VERSION,
                    "supported_versions": [_PROTOCOL_VERSION],
                    "min_client_version": _PROTOCOL_VERSION,
                },
            },
        )

    # ------------------------------------------------------------------
    # channels_ack
    # ------------------------------------------------------------------

    @router.post("/v1/ops/channels_ack")
    async def op_channels_ack(request: Request) -> JSONResponse:
        """Acknowledge receipt of a message (tool-call semantics, no message body)."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        status_val: str = (
            str(body.get("status", "received")) if isinstance(body, dict) else "received"
        )
        return JSONResponse(
            status_code=200,
            content={"acked_at": time.time(), "status": status_val},
        )

    # ------------------------------------------------------------------
    # channels_heartbeat
    # ------------------------------------------------------------------

    @router.post("/v1/ops/channels_heartbeat")
    async def op_channels_heartbeat(request: Request) -> JSONResponse:
        """Update agent liveness record and emit sox/presence event."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        status_val: str = str(body.get("status", "online")) if isinstance(body, dict) else "online"

        # Update liveness store
        liveness.record_heartbeat(agent_id, status_val)

        # Emit presence event to sox/presence channel
        presence_body: dict[str, object] = {
            "event": f"agent_{status_val}",
            "agent_id": agent_id,
            "state": status_val,
            "changed_at": time.time(),
        }
        try:
            import copy
            async with store._lock:  # type: ignore[attr-defined]
                seq = sum(1 for m in store._messages if m.channel == "sox/presence") + 1  # type: ignore[attr-defined, misc]
                from sox_protocol.adapters.backing_stores.memory.store import _StoredMessage
                msg_id = store._next_id  # type: ignore[attr-defined]
                store._next_id += 1  # type: ignore[attr-defined]
                msg = _StoredMessage(
                    id=msg_id,
                    channel="sox/presence",
                    sender="__server__",
                    body=copy.deepcopy(presence_body),
                    correlation_id=None,
                    sent_at=time.time(),
                )
                msg.seq = seq  # type: ignore[attr-defined]
                msg.reply_to = None  # type: ignore[attr-defined]
                store._messages.append(msg)  # type: ignore[attr-defined]
            store._new_message_event.set()  # type: ignore[attr-defined]
        except Exception:
            pass  # Presence emit failure is non-fatal
        return JSONResponse(
            status_code=200,
            content={"recorded_at": time.time(), "status": status_val},
        )

    # ------------------------------------------------------------------
    # channels_collect
    # ------------------------------------------------------------------

    @router.post("/v1/ops/channels_collect")
    async def op_channels_collect(request: Request) -> JSONResponse:
        """Collect N replies on a channel within a timeout window."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        val_err = _require_fields(body, "channel")
        if val_err:
            return validation_error_response(val_err)
        channel: str = str(body["channel"])
        count: int = int(body.get("count", 1)) if isinstance(body, dict) else 1
        timeout_s: float = float(body.get("timeout_s", 30.0)) if isinstance(body, dict) else 30.0
        deadline = time.time() + timeout_s
        collected: list[dict[str, object]] = []
        import asyncio
        try:
            while len(collected) < count and time.time() < deadline:
                msgs = await store.recv(agent_id, [channel], count - len(collected))
                for wire in msgs:
                    wire_copy = dict(wire)
                    if "seq" not in wire_copy:
                        async with store._lock:  # type: ignore[attr-defined]
                            for sm in store._messages:  # type: ignore[attr-defined]
                                if str(sm.id) == wire_copy.get("message_id"):
                                    wire_copy["seq"] = getattr(sm, "seq", 1)
                                    wire_copy["reply_to"] = getattr(sm, "reply_to", None)
                                    break
                    collected.append(wire_copy)
                if len(collected) < count:
                    await asyncio.sleep(0.05)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(
            status_code=200,
            content={
                "messages": collected,
                "collected_count": len(collected),
                "timed_out": len(collected) < count,
            },
        )

    # ------------------------------------------------------------------
    # replay
    # ------------------------------------------------------------------

    @router.post("/v1/ops/replay")
    async def op_replay(request: Request) -> JSONResponse:
        """Replay messages from a channel since a given seq cursor."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        val_err = _require_fields(body, "channel")
        if val_err:
            return validation_error_response(val_err)
        channel: str = str(body["channel"])
        since_seq: int = int(body.get("since_seq", 0)) if isinstance(body, dict) else 0
        limit: int = int(body.get("limit", 100)) if isinstance(body, dict) else 100
        msgs_out: list[dict[str, object]] = []
        try:
            async with store._lock:  # type: ignore[attr-defined]
                for sm in store._messages:  # type: ignore[attr-defined]
                    if sm.channel == channel:
                        sm_seq = getattr(sm, "seq", 0)
                        if sm_seq >= since_seq:
                            wire = sm.to_wire()
                            wire["seq"] = sm_seq
                            wire["reply_to"] = getattr(sm, "reply_to", None)
                            msgs_out.append(wire)
                    if len(msgs_out) >= limit:
                        break
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(
            status_code=200,
            content={"messages": msgs_out, "has_more": False},
        )

    # ------------------------------------------------------------------
    # list_agents
    # ------------------------------------------------------------------

    @router.post("/v1/ops/list_agents")
    async def op_list_agents(request: Request) -> JSONResponse:
        """Return liveness table for all known agents."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        status_filter: list[str] | None = (
            [str(s) for s in body["status_filter"]]
            if isinstance(body, dict) and "status_filter" in body
            else None
        )
        namespace_filter: str | None = (
            str(body["namespace"]) if isinstance(body, dict) and "namespace" in body else None
        )
        agents = liveness.list_agents(status_filter, namespace_filter)
        return JSONResponse(status_code=200, content={"agents": agents})

    # ------------------------------------------------------------------
    # group_create
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_create")
    async def op_group_create(request: Request) -> JSONResponse:
        """Create a new group channel."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        now = time.time()
        default_group_id = f"grp-{int(now)}"
        group_id_raw: str = (
            str(body.get("group_id", default_group_id))
            if isinstance(body, dict)
            else default_group_id
        )
        full_id = f"group/{group_id_raw}"
        try:
            async with store._lock:  # type: ignore[attr-defined]
                if not hasattr(store, "_groups"):
                    store._groups: dict[str, list[dict[str, object]]] = {}  # type: ignore[attr-defined, misc]
                store._groups[full_id] = [  # type: ignore[attr-defined]
                    {"agent_id": agent_id, "status": "active", "joined_at": now}
                ]
                patterns = store._subscriptions.setdefault(agent_id, [])  # type: ignore[attr-defined]
                if full_id not in patterns:
                    patterns.append(full_id)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(
            status_code=200,
            content={"group_id": full_id, "created_at": now},
        )

    # ------------------------------------------------------------------
    # group_invite
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_invite")
    async def op_group_invite(request: Request) -> JSONResponse:
        """Invite an agent to a group."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        val_err = _require_fields(body, "group_id", "agent_id")
        if val_err:
            return validation_error_response(val_err)
        group_id: str = str(body["group_id"])
        invitee: str = str(body["agent_id"])
        now = time.time()
        try:
            async with store._lock:  # type: ignore[attr-defined]
                if not hasattr(store, "_groups"):
                    store._groups = {}  # type: ignore[attr-defined]
                members = store._groups.get(group_id, [])  # type: ignore[attr-defined]
                caller_active = any(
                    m["agent_id"] == agent_id and m["status"] == "active"
                    for m in members
                )
                if not caller_active:
                    return sox_error_response(
                        error_code="GROUP_MEMBERSHIP_REQUIRED",
                        message="Caller must be an active group member to invite",
                        status_code=403,
                    )
                already = any(m["agent_id"] == invitee for m in members)
                if not already:
                    members.append({"agent_id": invitee, "status": "invited", "joined_at": now})
                store._groups[group_id] = members  # type: ignore[attr-defined]
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(
            status_code=200,
            content={"group_id": group_id, "invited_agent": invitee, "invited_at": now},
        )

    # ------------------------------------------------------------------
    # group_join
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_join")
    async def op_group_join(request: Request) -> JSONResponse:
        """Accept a group invitation and join the group."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        val_err = _require_fields(body, "group_id")
        if val_err:
            return validation_error_response(val_err)
        group_id = str(body["group_id"])
        now = time.time()
        try:
            async with store._lock:  # type: ignore[attr-defined]
                if not hasattr(store, "_groups"):
                    store._groups = {}  # type: ignore[attr-defined]
                members = store._groups.get(group_id, [])  # type: ignore[attr-defined]
                for m in members:
                    if m["agent_id"] == agent_id and m["status"] == "invited":
                        m["status"] = "active"
                        m["joined_at"] = now
                        break
                patterns = store._subscriptions.setdefault(agent_id, [])  # type: ignore[attr-defined]
                if group_id not in patterns:
                    patterns.append(group_id)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(
            status_code=200,
            content={"group_id": group_id, "joined_at": now},
        )

    # ------------------------------------------------------------------
    # group_leave
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_leave")
    async def op_group_leave(request: Request) -> JSONResponse:
        """Leave a group."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        val_err = _require_fields(body, "group_id")
        if val_err:
            return validation_error_response(val_err)
        group_id = str(body["group_id"])
        now = time.time()
        try:
            async with store._lock:  # type: ignore[attr-defined]
                if not hasattr(store, "_groups"):
                    store._groups = {}  # type: ignore[attr-defined]
                members = store._groups.get(group_id, [])  # type: ignore[attr-defined]
                store._groups[group_id] = [m for m in members if m["agent_id"] != agent_id]  # type: ignore[attr-defined]
                patterns = store._subscriptions.get(agent_id, [])  # type: ignore[attr-defined]
                store._subscriptions[agent_id] = [p for p in patterns if p != group_id]  # type: ignore[attr-defined]
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(
            status_code=200,
            content={"group_id": group_id, "left_at": now},
        )

    # ------------------------------------------------------------------
    # group_list_members
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_list_members")
    async def op_group_list_members(request: Request) -> JSONResponse:
        """List members of a group."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        val_err = _require_fields(body, "group_id")
        if val_err:
            return validation_error_response(val_err)
        group_id = str(body["group_id"])
        try:
            async with store._lock:  # type: ignore[attr-defined]
                if not hasattr(store, "_groups"):
                    store._groups = {}  # type: ignore[attr-defined]
                members = list(store._groups.get(group_id, []))  # type: ignore[attr-defined]
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(status_code=200, content={"members": members})
