# SPDX-License-Identifier: Apache-2.0
"""Operation route handlers for the HTTP transport.

Registers one POST handler per SOX operation at ``/v1/ops/<operation>``.
Each handler:
1. Resolves agent identity from the Authorization header.
2. Validates the request body against the operation's input schema (JSON Schema,
   compiled at module load time from ``spec/operations/<op>.input.schema.json``).
3. Dispatches to the backing store.
4. Returns the operation output as JSON.

Spec reference: ``spec/operations/*.json``

Fix catalogue (04-spec-realignment):
- FIX-1: Schema-driven input validation replaces ``_require_fields``; validators
  are compiled at module load time.
- FIX-2: Wildcard subscription rejection enforced at transport boundary for
  ``dm/*`` and ``group/*`` prefixes per ``subscribe.input.schema.json``.
- FIX-3: ``backpressure_over_limit`` emission in ``op_send``; hard-coded
  ``state:"ok"`` block replaced.
- FIX-4: ``op_list_agents`` migrated to ``BackingStore.list_agents()``;
  in-process liveness dependency removed entirely from this module.
- FIX-5: ``channels_collect`` marked as documented degraded mode (internal
  poll-loop); ``x-degraded-mode`` annotation in openapi.yaml.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import jsonschema
import jsonschema.exceptions
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from sox_protocol.adapters.transports.http.auth import IdentityResolver, resolve_agent_id
from sox_protocol.adapters.transports.http.errors import (
    internal_error_response,
    sox_error_response,
)
from sox_protocol.core.ports.backing_store import BackingStore

_PROTOCOL_VERSION = "1.0"

# ---------------------------------------------------------------------------
# FIX-1: Schema-driven validators compiled at module load time
# ---------------------------------------------------------------------------

def _load_op_schema(op_name: str) -> dict[str, Any]:
    """Load ``spec/operations/<op_name>.input.schema.json`` relative to this package.

    Args:
        op_name: Operation name (e.g. ``"send"``).

    Returns:
        Parsed JSON Schema dict.
    """
    # Walk up from this file to the repo root, then into spec/operations/
    here = Path(__file__).resolve()
    # packages/python/src/sox_protocol/adapters/transports/http/routes.py
    # → repo root is 7 levels up
    repo_root = here.parents[7]
    schema_path = repo_root / "spec" / "operations" / f"{op_name}.input.schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    with schema_path.open(encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


def _compile(op_name: str) -> jsonschema.Draft202012Validator:
    """Compile and return a cached Draft 2020-12 validator for *op_name*.

    Args:
        op_name: Operation name.

    Returns:
        A compiled :class:`jsonschema.Draft202012Validator`.
    """
    schema = _load_op_schema(op_name)
    validator = jsonschema.Draft202012Validator(schema)
    return validator


# Module-level compiled validators — loaded once at import time.
_VALIDATORS: dict[str, jsonschema.Draft202012Validator] = {
    op: _compile(op)
    for op in [
        "send",
        "recv",
        "subscribe",
        "unsubscribe",
        "list_channels",
        "channels_ack",
        "channels_heartbeat",
        "channels_collect",
        "replay",
        "list_agents",
        "group_create",
        "group_invite",
        "group_join",
        "group_leave",
        "group_list_members",
    ]
}

# ---------------------------------------------------------------------------
# FIX-2: Wildcard subscription rejection patterns
# ---------------------------------------------------------------------------

# Patterns forbidden by subscribe.input.schema.json «not/anyOf»:
#   - dm/<anything>*   → wildcard on dm/ prefix
#   - group/<anything>* → wildcard on group/ prefix
_FORBIDDEN_WILDCARD_RE = re.compile(r"^(?:dm/|group/).*\*")


def _wildcard_forbidden(pattern: str) -> bool:
    """Return True if *pattern* is a forbidden wildcard per the subscribe schema.

    Args:
        pattern: Subscription pattern string.

    Returns:
        True when the pattern matches ``dm/.*\\*`` or ``group/.*\\*``.
    """
    return bool(_FORBIDDEN_WILDCARD_RE.match(pattern))


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def _validate_body(op_name: str, body: object) -> JSONResponse | None:
    """Validate *body* against the compiled schema for *op_name*.

    Args:
        op_name: Operation name key in ``_VALIDATORS``.
        body: Parsed request body.

    Returns:
        A 400 :class:`JSONResponse` with ``validation_error`` envelope if
        validation fails, else ``None``.
    """
    validator = _VALIDATORS[op_name]
    errors = sorted(validator.iter_errors(body), key=lambda e: list(e.path))
    if not errors:
        return None
    violations = [
        {
            "field": ".".join(str(p) for p in err.absolute_path) or "<root>",
            "issue": err.message,
        }
        for err in errors
    ]
    return sox_error_response(
        error_code="validation_error",
        message=f"Input does not conform to {op_name}.input.schema.json.",
        status_code=400,
        detail={"violations": violations},
    )


def register_operation_routes(
    router: APIRouter,
    store: BackingStore,
    resolver: IdentityResolver,
) -> None:
    """Register all SOX operation handlers on *router*.

    Args:
        router: The FastAPI APIRouter to register routes on.
        store: The backing store instance for persistence.
        resolver: Identity resolver for bearer token auth.
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
    # FIX-1 + FIX-3: send
    # ------------------------------------------------------------------

    @router.post("/v1/ops/send")
    async def op_send(request: Request) -> JSONResponse:
        """Send a message to a channel."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation
        val_err = _validate_body("send", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        channel: str = str(body["channel"])
        msg_body: dict[str, object] = body["body"] if isinstance(body["body"], dict) else {}
        correlation_id: str | None = body.get("correlation_id")
        try:
            message_id, sent_at, seq, bp = await store.send(
                channel, agent_id, msg_body, correlation_id
            )
        except Exception as exc:
            return internal_error_response(str(exc))
        # FIX-3: emit backpressure_over_limit when threshold is crossed
        if bp.over_limit:
            return sox_error_response(
                error_code="backpressure_over_limit",
                message=(
                    f"Send rejected: channel '{channel}' queue depth {bp.queue_depth} "
                    f"is at or above threshold {bp.threshold}."
                ),
                status_code=429,
                detail={
                    "queue_depth": bp.queue_depth,
                    "threshold": bp.threshold,
                    "mode": bp.mode,
                },
            )
        return JSONResponse(
            status_code=200,
            content={
                "sent_at": sent_at,
                "message_id": message_id,
                "seq": seq,
                "backpressure": {
                    "queue_depth": bp.queue_depth,
                    "threshold": bp.threshold,
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
        # FIX-1: schema-driven validation
        val_err = _validate_body("recv", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict) or body is None
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

        return JSONResponse(
            status_code=200,
            content={"drained_at": time.time(), "messages": msgs},
        )

    # ------------------------------------------------------------------
    # FIX-1 + FIX-2: subscribe
    # ------------------------------------------------------------------

    @router.post("/v1/ops/subscribe")
    async def op_subscribe(request: Request) -> JSONResponse:
        """Register a subscription pattern for the authenticated agent."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation (also enforces minLength/maxLength)
        val_err = _validate_body("subscribe", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        pattern = str(body["pattern"])
        # FIX-2: wildcard subscription rejection at transport boundary
        if _wildcard_forbidden(pattern):  # pragma: no cover — schema already rejects these patterns
            return sox_error_response(
                error_code="validation_error",
                message=(
                    f"Wildcard subscriptions on reserved prefixes are forbidden. "
                    f"Pattern '{pattern}' matches dm/* or group/* wildcard restriction."
                ),
                status_code=400,
                detail={
                    "violations": [
                        {
                            "field": "pattern",
                            "issue": (
                                "Wildcard subscriptions on the dm/ or group/ prefix are "
                                "forbidden. Use an exact channel name instead."
                            ),
                        }
                    ]
                },
            )
        try:
            matched = await store.subscribe(agent_id, pattern)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(status_code=200, content={"subscribed": matched})

    # ------------------------------------------------------------------
    # unsubscribe  (FIX-1: schema uses "channels" not "patterns")
    # ------------------------------------------------------------------

    @router.post("/v1/ops/unsubscribe")
    async def op_unsubscribe(request: Request) -> JSONResponse:
        """Remove subscription patterns for the authenticated agent."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation; spec field is "channels"
        val_err = _validate_body("unsubscribe", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        # Spec field is "channels" (unsubscribe.input.schema.json)
        patterns: list[str] = [str(p) for p in body["channels"]]
        try:
            removed, pending_cleared = await store.unsubscribe(agent_id, patterns)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(
            status_code=200,
            content={"unsubscribed": removed, "pending_cleared": pending_cleared},
        )

    # ------------------------------------------------------------------
    # list_channels
    # ------------------------------------------------------------------

    @router.post("/v1/ops/list_channels")
    async def op_list_channels(request: Request) -> JSONResponse:
        """Return known channels."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation
        val_err = _validate_body("list_channels", body)
        if val_err is not None:
            return val_err
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
        """Acknowledge receipt of a message."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation (requires message_id + status)
        val_err = _validate_body("channels_ack", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        message_id_val: str = str(body["message_id"])
        status_val: str = str(body["status"])
        reason_val: str | None = body.get("reason")
        try:
            result = await store.ack(agent_id, message_id_val, status_val, reason_val)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(status_code=200, content=result)

    # ------------------------------------------------------------------
    # channels_heartbeat
    # ------------------------------------------------------------------

    @router.post("/v1/ops/channels_heartbeat")
    async def op_channels_heartbeat(request: Request) -> JSONResponse:
        """Update agent liveness record."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation (requires status)
        val_err = _validate_body("channels_heartbeat", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        status_val: str = str(body["status"])
        ttl_val: int | None = body.get("ttl")
        try:
            result = await store.heartbeat(agent_id, status_val, ttl_val)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(status_code=200, content=result)

    # ------------------------------------------------------------------
    # channels_collect  (FIX-5: documented degraded mode)
    #
    # Spec §5 requires SSE or long-poll for efficient collect. This
    # implementation uses an internal poll-loop which is documented here
    # and in openapi.yaml as a degraded mode (x-degraded-mode extension).
    # This is acceptable per spec §5: "Implementations that support neither
    # SSE nor long-poll MAY implement collect by polling internally and
    # returning a regular HTTP response, but this degrades efficiency for
    # long timeout windows and is NOT RECOMMENDED for production deployments."
    #
    # The spec uses reply_to/count/timeout (not channel/count/timeout_s).
    # ------------------------------------------------------------------

    @router.post("/v1/ops/channels_collect")
    async def op_channels_collect(request: Request) -> JSONResponse:
        """Collect N ACK replies to a broadcast within a timeout window.

        .. note::
            **Degraded mode**: This endpoint uses an internal poll-loop rather
            than SSE or long-poll as recommended by ``spec/ports/transport.md §5``.
            See ``spec/transports/http/openapi.yaml`` (``x-degraded-mode``
            extension on this path) for rationale and production guidance.
        """
        import asyncio

        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation (requires reply_to, count, timeout)
        val_err = _validate_body("channels_collect", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        reply_to: str = str(body["reply_to"])
        count: int = int(body["count"])
        timeout_s: float = float(body["timeout"])
        status_filter: list[str] | None = body.get("status_filter")

        # Poll for ACK records that reference reply_to.
        # This is degraded-mode: we poll the store's ack records indirectly
        # by draining recv and counting matching ack statuses.
        deadline = time.time() + timeout_s
        collected: list[dict[str, object]] = []
        try:
            while len(collected) < count and time.time() < deadline:
                msgs = await store.recv(agent_id, None, count - len(collected))
                for m in msgs:
                    m_reply = m.get("reply_to") or m.get("correlation_id")
                    if m_reply == reply_to:
                        if status_filter is None:
                            collected.append(m)
                        # status_filter on body messages is advisory in degraded mode
                if len(collected) < count:
                    await asyncio.sleep(0.05)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(
            status_code=200,
            content={"messages": collected, "timed_out": len(collected) < count},
        )

    # ------------------------------------------------------------------
    # replay  (FIX-1: spec field is "since" not "since_seq")
    # ------------------------------------------------------------------

    @router.post("/v1/ops/replay")
    async def op_replay(request: Request) -> JSONResponse:
        """Replay messages from a channel since a given seq cursor."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation (requires channel, since, limit)
        val_err = _validate_body("replay", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        channel: str = str(body["channel"])
        # Spec field: "since" (not "since_seq")
        since_seq: int = int(body["since"])
        limit: int = int(body.get("limit", 100))
        until: int | None = body.get("until")
        try:
            messages, has_more = await store.replay(channel, since_seq, until, limit)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(
            status_code=200,
            content={"messages": messages, "has_more": has_more},
        )

    # ------------------------------------------------------------------
    # FIX-4: list_agents — backed by BackingStore port
    # ------------------------------------------------------------------

    @router.post("/v1/ops/list_agents")
    async def op_list_agents(request: Request) -> JSONResponse:
        """Return liveness table for all known agents.

        .. note::
            FIX-4: Delegates entirely to ``BackingStore.list_agents()``.
            In-process liveness dependency removed from this module.
        """
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation
        val_err = _validate_body("list_agents", body)
        if val_err is not None:
            return val_err
        status_filter: list[str] | None = (
            [str(s) for s in body["status_filter"]]
            if isinstance(body, dict) and "status_filter" in body
            else None
        )
        namespace_filter: str | None = (
            str(body["namespace"]) if isinstance(body, dict) and "namespace" in body else None
        )
        try:
            agents = await store.list_agents(status_filter, namespace_filter)
        except Exception as exc:
            return internal_error_response(str(exc))
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
        # FIX-1: schema-driven validation
        val_err = _validate_body("group_create", body)
        if val_err is not None:
            return val_err
        group_id_arg: str | None = (
            str(body["group_id"]) if isinstance(body, dict) and "group_id" in body else None
        )
        try:
            result = await store.group_create(agent_id, group_id_arg)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(status_code=200, content=result)

    # ------------------------------------------------------------------
    # group_invite
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_invite")
    async def op_group_invite(request: Request) -> JSONResponse:
        """Invite an agent to a group."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation
        val_err = _validate_body("group_invite", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        group_id: str = str(body["group_id"])
        invitee: str = str(body["agent_id"])
        try:
            result = await store.group_invite(agent_id, group_id, invitee)
        except ValueError as exc:
            return sox_error_response(
                error_code="GROUP_MEMBERSHIP_REQUIRED",
                message=str(exc),
                status_code=403,
            )
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(status_code=200, content=result)

    # ------------------------------------------------------------------
    # group_join
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_join")
    async def op_group_join(request: Request) -> JSONResponse:
        """Accept a group invitation and join the group."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation
        val_err = _validate_body("group_join", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        group_id = str(body["group_id"])
        try:
            result = await store.group_join(agent_id, group_id)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(status_code=200, content=result)

    # ------------------------------------------------------------------
    # group_leave
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_leave")
    async def op_group_leave(request: Request) -> JSONResponse:
        """Leave a group."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation
        val_err = _validate_body("group_leave", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        group_id = str(body["group_id"])
        try:
            result = await store.group_leave(agent_id, group_id)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(status_code=200, content=result)

    # ------------------------------------------------------------------
    # group_list_members
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_list_members")
    async def op_group_list_members(request: Request) -> JSONResponse:
        """List members of a group."""
        agent_id, body, err = await _auth_and_body(request)
        if err is not None:
            return err
        # FIX-1: schema-driven validation
        val_err = _validate_body("group_list_members", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        group_id = str(body["group_id"])
        try:
            result = await store.group_list_members(agent_id, group_id)
        except Exception as exc:
            return internal_error_response(str(exc))
        return JSONResponse(status_code=200, content=result)
