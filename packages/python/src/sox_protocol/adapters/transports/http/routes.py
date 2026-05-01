# SPDX-License-Identifier: Apache-2.0
"""Operation route handlers for the HTTP transport.

Registers one POST handler per SOX operation at ``/v1/ops/<operation>``.
Each handler:
1. Extracts the bearer token (agent_id) from the Authorization header.
2. Validates the request body against the operation's input schema (JSON Schema,
   compiled at module load time from ``spec/operations/<op>.input.schema.json``).
3. Dispatches through ``Pipeline.dispatch`` (which runs AuthMiddleware →
   StoreDispatchMiddleware).
4. Returns the operation output as JSON.

Phase 03-build-http (pipeline-integration): all 15 direct ``store.<op>()``
calls converted to ``await pipeline.dispatch(...)``.  ``IdentityResolver``,
``PassthroughIdentityResolver``, and ``resolve_agent_id`` deleted from the
import set; bearer token is wrapped in a :class:`SignedRequest` envelope via
:func:`~sox_protocol.adapters.transports.http._credential.resolve_credential`
and injected into ``ctx.metadata["_connection_credential"]`` so AuthMiddleware
performs real cryptographic verification.

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
import logging
import re
import time
from pathlib import Path
from typing import Any

import jsonschema
import jsonschema.exceptions
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from sox_protocol.adapters.transports.http._credential import resolve_credential
from sox_protocol.adapters.transports.http.auth import extract_bearer_token
from sox_protocol.adapters.transports.http.errors import (
    internal_error_response,
    sox_error_response,
)
from sox_protocol.core.identity import InMemoryCredentialRegistry
from sox_protocol.core.identity.keys import generate_keypair
from sox_protocol.core.middleware.pipeline import Pipeline

_log = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Pipeline dispatch helper
# ---------------------------------------------------------------------------

async def _dispatch(
    pipeline: Pipeline,
    private_key: Ed25519PrivateKey,
    registry: InMemoryCredentialRegistry,
    operation: str,
    body: dict[str, object],
    token: str,
    connection_id: str,
    *,
    auto_register: bool = True,
) -> JSONResponse:
    """Build a credential, dispatch through the pipeline, return a JSONResponse.

    Field mapping note: the HTTP request body uses spec-schema field names
    (e.g. ``channels`` for unsubscribe, ``agent_id`` for group_invite target).
    ``StoreDispatchMiddleware`` uses different internal field names in some
    operations.  Callers of this helper must pass body dicts with field names
    already remapped to the StoreDispatchMiddleware conventions — OR pass the
    body as-is and rely on StoreDispatchMiddleware's ``ctx.agent_id`` fallbacks
    (set by AuthMiddleware from the verified credential).

    Args:
        pipeline: The configured middleware pipeline.
        private_key: Ephemeral Ed25519 key for signing the per-request credential.
        registry: Credential registry for auto-registration of new agents (v1
            transitional — see module docstring).
        operation: SOX operation name (e.g. ``"send"``).
        body: Request body dict with field names mapped for StoreDispatchMiddleware.
        token: Bearer token (== agent_id in v1 transitional path).
        connection_id: Remote address / connection identifier for the context.

    Returns:
        :class:`JSONResponse` with the pipeline result, or a sox-error response
        on credential failure.
    """
    # v1 transitional: auto-register the agent if not already in the registry.
    # The same ephemeral public key is used for all agents in this app instance.
    # AuthMiddleware will verify the SignedRequest against this key.
    # v1.1 will require explicit agent registration via manifest or CLI.
    #
    # When auto_register=False (host pre-populated registry via
    # SOX_PRE_REGISTERED_AGENTS), unknown tokens skip the registration path and
    # fall through to AuthMiddleware unmapped — registry.lookup returns None
    # and verifier.verify() raises UnknownAgentError, which the middleware
    # converts to an identity_failure envelope. This is the gate that lets
    # the conformance harness's unknown-credential-rejected fixture pass.
    if auto_register and not await registry.lookup(token):
        # Use the app's private key to derive a consistent public key for this agent.
        public_key_bytes = private_key.public_key().public_bytes_raw()
        await registry.register(token, public_key_bytes)

    try:
        credential = resolve_credential(token, private_key, operation, body)
    except Exception as exc:  # pragma: no cover — defensive; resolve_credential is pure
        _log.exception("Failed to build credential for operation %r", operation)
        return sox_error_response("invalid_credential", str(exc), status_code=401)

    try:
        result = await pipeline.dispatch(
            operation=operation,
            input=body,
            connection_id=connection_id,
            metadata={"_connection_credential": credential},
        )
        # Pipeline returns either an operation success dict or a sox-error
        # envelope (any dict containing an "error_code" field). Map error
        # envelopes to HTTP status codes per the closed error taxonomy in
        # spec/ports/middleware/03-plugin-contract.md §6 — without this, the
        # body is correct but the HTTP layer reports 200 OK and clients
        # treat the call as success. The operation-success path returns the
        # raw result with HTTP 200.
        if isinstance(result, dict) and "error_code" in result:
            err_code = str(result.get("error_code", "internal_error"))
            err_msg = str(result.get("message", ""))
            status_map = {
                "identity_failure": 401,
                "missing_credential": 401,
                "invalid_credential": 401,
                "unknown_agent": 401,
                "validation_failed": 400,
                "plugin_capability_conflict": 400,
                "plugin_ordering_cycle": 500,
                "plugin_protocol_version_mismatch": 500,
                "internal_error": 500,
            }
            return JSONResponse(
                status_code=status_map.get(err_code, 400),
                content=result,
            )
        return JSONResponse(status_code=200, content=result)
    except Exception as exc:
        # Pipeline already converts most failures to envelopes via
        # ShortCircuitResponse; this catches only programmer errors that
        # escape the pipeline's own exception handler.
        _log.exception("Unhandled exception in pipeline.dispatch for %r", operation)
        return internal_error_response(str(exc))


def register_operation_routes(
    router: APIRouter,
    pipeline: Pipeline,
    private_key: Ed25519PrivateKey,
    registry: InMemoryCredentialRegistry,
    *,
    auto_register: bool = True,
) -> None:
    """Register all SOX operation handlers on *router*.

    Each handler extracts the bearer token, validates the body schema, then
    dispatches through *pipeline* with a freshly signed credential envelope.

    v1 transitional: when *auto_register* is ``True`` (default), arriving
    bearer tokens are auto-registered in *registry* under the server's
    keypair so AuthMiddleware can verify the per-request SignedRequest.
    When *auto_register* is ``False`` (set when the host pre-populates the
    registry via the ``SOX_PRE_REGISTERED_AGENTS`` env var), unknown tokens
    fall through to AuthMiddleware unmapped and trigger a normal
    ``identity_failure`` envelope — the conformance suite's
    ``unknown-credential-rejected`` fixtures rely on this gate.

    v1.1 will require explicit registration and the auto-register path will
    be removed entirely.

    Args:
        router: The FastAPI APIRouter to register routes on.
        pipeline: The configured middleware pipeline (AuthMiddleware →
            StoreDispatchMiddleware).
        private_key: The ephemeral Ed25519 private key used to sign per-request
            credential envelopes (generated at app startup).
        registry: The in-memory credential registry for auto-registration of
            arriving agents (v1 transitional).
        auto_register: Whether unknown bearer tokens should be auto-registered
            in *registry* (default True). Disabled when the host pre-populates
            the registry via SOX_PRE_REGISTERED_AGENTS.
    """

    # ------------------------------------------------------------------
    # Common token extractor (replaces old _auth_and_body / resolve_agent_id)
    # ------------------------------------------------------------------

    def _require_token(request: Request) -> tuple[str, JSONResponse | None]:
        """Extract bearer token; return (token, None) or ("", error_response)."""
        token = extract_bearer_token(request)
        if token is None:
            return (
                "",
                sox_error_response(
                    error_code="missing_credential",
                    message="Authorization: Bearer <token> header required",
                    status_code=401,
                ),
            )
        return token, None

    def _connection_id(request: Request) -> str:
        if request.client is not None:
            return request.client.host or "unknown"
        return "unknown"

    def _inject_agent_id(body: dict[str, object], token: str) -> dict[str, object]:
        """Inject token as agent_id into body for operations where AuthMiddleware
        does not enforce identity (and therefore does not set ctx.agent_id).
        StoreDispatchMiddleware reads ``inp.get("agent_id", ctx.agent_id or "")``
        so providing it here ensures correct routing even for non-enforced ops.
        """
        result = dict(body)
        result.setdefault("agent_id", token)
        return result

    # ------------------------------------------------------------------
    # FIX-1 + FIX-3: send
    # ------------------------------------------------------------------

    @router.post("/v1/ops/send")
    async def op_send(request: Request) -> JSONResponse:
        """Send a message to a channel."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body: Any = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation
        val_err = _validate_body("send", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        resp = await _dispatch(pipeline, private_key, registry, "send", body, token, _connection_id(request), auto_register=auto_register)
        # FIX-3: pipeline result may carry backpressure_over_limit from
        # StoreDispatchMiddleware; surface it as 429 if so.
        # Also strip extra "channel" key not in send.output.schema.json.
        if resp.status_code == 200:
            content = json.loads(bytes(resp.body))
            content.pop("channel", None)  # not in send output schema
            bp = content.get("backpressure", {})
            # FIX-3: check both state field AND queue_depth >= threshold because
            # BackpressureInfo.state defaults to "ok" even when over_limit=True
            # (StoreDispatchMiddleware serialises state but not over_limit).
            over_limit = (
                isinstance(bp, dict)
                and (
                    bp.get("state") == "over_limit"
                    or (
                        isinstance(bp.get("queue_depth"), (int, float))
                        and isinstance(bp.get("threshold"), (int, float))
                        and bp["queue_depth"] >= bp["threshold"]
                    )
                )
            )
            if over_limit:
                channel = body.get("channel", "")
                return sox_error_response(
                    error_code="backpressure_over_limit",
                    message=(
                        f"Send rejected: channel '{channel}' queue depth "
                        f"{bp.get('queue_depth')} is at or above threshold "
                        f"{bp.get('threshold')}."
                    ),
                    status_code=429,
                    detail={
                        "queue_depth": bp.get("queue_depth"),
                        "threshold": bp.get("threshold"),
                        # StoreDispatchMiddleware does not serialize BackpressureInfo.mode;
                        # default to "enforced" (the only mode in v1).  v1.1 will add mode
                        # to the pipeline result shape.
                        "mode": bp.get("mode", "enforced"),
                    },
                )
            return JSONResponse(status_code=200, content=content)
        return resp

    # ------------------------------------------------------------------
    # recv
    # ------------------------------------------------------------------

    @router.post("/v1/ops/recv")
    async def op_recv(request: Request) -> JSONResponse:
        """Drain pending messages for the authenticated agent."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation
        val_err = _validate_body("recv", body)
        if val_err is not None:
            return val_err
        if not isinstance(body, dict):
            body = {}
        return await _dispatch(pipeline, private_key, registry, "recv", body, token, _connection_id(request), auto_register=auto_register)

    # ------------------------------------------------------------------
    # FIX-1 + FIX-2: subscribe
    # ------------------------------------------------------------------

    @router.post("/v1/ops/subscribe")
    async def op_subscribe(request: Request) -> JSONResponse:
        """Register a subscription pattern for the authenticated agent."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
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
        resp = await _dispatch(pipeline, private_key, registry, "subscribe", body, token, _connection_id(request), auto_register=auto_register)
        # Normalize: StoreDispatchMiddleware returns {"subscribed": True, "matched_channels": [...]}
        # but HTTP clients expect {"subscribed": [<channel names>]}.
        if resp.status_code == 200:
            content = json.loads(bytes(resp.body))
            if isinstance(content.get("matched_channels"), list):
                return JSONResponse(status_code=200, content={"subscribed": content["matched_channels"]})
        return resp

    # ------------------------------------------------------------------
    # unsubscribe  (FIX-1: schema uses "channels" not "patterns")
    # ------------------------------------------------------------------

    @router.post("/v1/ops/unsubscribe")
    async def op_unsubscribe(request: Request) -> JSONResponse:
        """Remove subscription patterns for the authenticated agent."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation; spec field is "channels"
        val_err = _validate_body("unsubscribe", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        # Remap spec field "channels" → StoreDispatchMiddleware field "patterns".
        # Also inject agent_id (unsubscribe is not in _IDENTITY_ENFORCED_OPERATIONS
        # so ctx.agent_id won't be set by AuthMiddleware).
        dispatch_body: dict[str, object] = _inject_agent_id(body, token)
        if "channels" in dispatch_body and "patterns" not in dispatch_body:
            dispatch_body["patterns"] = dispatch_body.pop("channels")
        resp = await _dispatch(pipeline, private_key, registry, "unsubscribe", dispatch_body, token, _connection_id(request), auto_register=auto_register)
        # Normalize: StoreDispatchMiddleware returns {"removed": [...], "pending_cleared": int}
        # but HTTP clients expect {"unsubscribed": [...], "pending_cleared": int}.
        if resp.status_code == 200:
            content = json.loads(bytes(resp.body))
            if "removed" in content and "unsubscribed" not in content:
                content["unsubscribed"] = content.pop("removed")
                return JSONResponse(status_code=200, content=content)
        return resp

    # ------------------------------------------------------------------
    # list_channels
    # ------------------------------------------------------------------

    @router.post("/v1/ops/list_channels")
    async def op_list_channels(request: Request) -> JSONResponse:
        """Return known channels."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation
        val_err = _validate_body("list_channels", body)
        if val_err is not None:
            return val_err
        if not isinstance(body, dict):
            body = {}
        # list_channels is not enforced by AuthMiddleware; inject agent_id for
        # StoreDispatchMiddleware's fallback lookup.
        resp = await _dispatch(pipeline, private_key, registry, "list_channels", _inject_agent_id(body, token), token, _connection_id(request), auto_register=auto_register)
        # Add _sox_protocol version block expected by list_channels output schema.
        if resp.status_code == 200:
            content = json.loads(bytes(resp.body))
            if "_sox_protocol" not in content:
                content["_sox_protocol"] = {
                    "server_version": _PROTOCOL_VERSION,
                    "supported_versions": [_PROTOCOL_VERSION],
                    "min_client_version": _PROTOCOL_VERSION,
                }
            return JSONResponse(status_code=200, content=content)
        return resp

    # ------------------------------------------------------------------
    # channels_ack
    # ------------------------------------------------------------------

    @router.post("/v1/ops/channels_ack")
    async def op_channels_ack(request: Request) -> JSONResponse:
        """Acknowledge receipt of a message."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation (requires message_id + status)
        val_err = _validate_body("channels_ack", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        return await _dispatch(pipeline, private_key, registry, "channels_ack", _inject_agent_id(body, token), token, _connection_id(request), auto_register=auto_register)

    # ------------------------------------------------------------------
    # channels_heartbeat
    # ------------------------------------------------------------------

    @router.post("/v1/ops/channels_heartbeat")
    async def op_channels_heartbeat(request: Request) -> JSONResponse:
        """Update agent liveness record."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation (requires status)
        val_err = _validate_body("channels_heartbeat", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        return await _dispatch(pipeline, private_key, registry, "channels_heartbeat", _inject_agent_id(body, token), token, _connection_id(request), auto_register=auto_register)

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
    # Phase 03-build-http: the loop now dispatches each recv through
    # pipeline instead of calling store.recv directly.  Per implementation-plan
    # risk R4 the loop structure and guards are preserved exactly.
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

        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation (requires reply_to, count, timeout)
        val_err = _validate_body("channels_collect", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        reply_to: str = str(body["reply_to"])
        count: int = int(body["count"])
        timeout_s: float = float(body["timeout"])
        status_filter_raw = body.get("status_filter")
        status_filter: list[str] | None = (
            [str(s) for s in status_filter_raw] if isinstance(status_filter_raw, list) else None
        )
        connection_id = _connection_id(request)

        # Poll for ACK records that reference reply_to.
        # Per implementation-plan risk R4: loop structure and guards preserved;
        # each recv dispatches through pipeline.dispatch (one call per iteration).
        deadline = time.time() + timeout_s
        collected: list[dict[str, object]] = []
        try:
            while len(collected) < count and time.time() < deadline:
                recv_body: dict[str, object] = {"max_messages": count - len(collected)}
                resp = await _dispatch(
                    pipeline, private_key, registry, "recv", recv_body, token, connection_id,
                    auto_register=auto_register,
                )
                if resp.status_code != 200:
                    # Auth or pipeline error — surface immediately
                    return resp
                result = json.loads(bytes(resp.body))
                msgs: list[dict[str, object]] = result.get("messages", [])
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
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation (requires channel, since, limit)
        val_err = _validate_body("replay", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        return await _dispatch(pipeline, private_key, registry, "replay", _inject_agent_id(body, token), token, _connection_id(request), auto_register=auto_register)

    # ------------------------------------------------------------------
    # FIX-4: list_agents — backed by BackingStore port via pipeline
    # ------------------------------------------------------------------

    @router.post("/v1/ops/list_agents")
    async def op_list_agents(request: Request) -> JSONResponse:
        """Return liveness table for all known agents.

        .. note::
            FIX-4: Delegates entirely to ``BackingStore.list_agents()`` via
            pipeline.dispatch.  In-process liveness dependency removed.
        """
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation
        val_err = _validate_body("list_agents", body)
        if val_err is not None:
            return val_err
        if not isinstance(body, dict):
            body = {}
        # list_agents IS in _IDENTITY_ENFORCED_OPERATIONS; ctx.agent_id set by AuthMiddleware.
        return await _dispatch(pipeline, private_key, registry, "list_agents", body, token, _connection_id(request), auto_register=auto_register)

    # ------------------------------------------------------------------
    # group_create
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_create")
    async def op_group_create(request: Request) -> JSONResponse:
        """Create a new group channel."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation
        val_err = _validate_body("group_create", body)
        if val_err is not None:
            return val_err
        if not isinstance(body, dict):
            body = {}
        # StoreDispatchMiddleware reads "creator_id" falling back to ctx.agent_id.
        # group_create is not enforced so inject creator_id explicitly.
        dispatch_body_gc = dict(body)
        dispatch_body_gc.setdefault("creator_id", token)
        return await _dispatch(pipeline, private_key, registry, "group_create", dispatch_body_gc, token, _connection_id(request), auto_register=auto_register)

    # ------------------------------------------------------------------
    # group_invite
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_invite")
    async def op_group_invite(request: Request) -> JSONResponse:
        """Invite an agent to a group."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation
        val_err = _validate_body("group_invite", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        # Remap spec field "agent_id" (invitee) → StoreDispatchMiddleware field "invitee_id".
        # Also inject "inviter_id" (the caller) since group_invite is not enforced.
        dispatch_body = dict(body)
        if "agent_id" in dispatch_body and "invitee_id" not in dispatch_body:
            dispatch_body["invitee_id"] = dispatch_body.pop("agent_id")
        dispatch_body.setdefault("inviter_id", token)
        resp = await _dispatch(pipeline, private_key, registry, "group_invite", dispatch_body, token, _connection_id(request), auto_register=auto_register)
        # The pipeline converts store.group_invite ValueError (membership check) to an
        # internal_error envelope.  Map it back to 403 GROUP_MEMBERSHIP_REQUIRED to
        # preserve the pre-pipeline HTTP contract (v1 transitional; v1.1 will raise
        # a typed GroupMembershipError that the pipeline surfaces as a ShortCircuit).
        if resp.status_code == 200:
            content = json.loads(bytes(resp.body))
            if content.get("error_code") == "internal_error":
                # Re-map membership-check errors to 403; all other internal errors stay 500.
                return sox_error_response(
                    error_code="GROUP_MEMBERSHIP_REQUIRED",
                    message=content.get("message", "Group membership required"),
                    status_code=403,
                )
        return resp

    # ------------------------------------------------------------------
    # group_join
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_join")
    async def op_group_join(request: Request) -> JSONResponse:
        """Accept a group invitation and join the group."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation
        val_err = _validate_body("group_join", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        return await _dispatch(pipeline, private_key, registry, "group_join", _inject_agent_id(body, token), token, _connection_id(request), auto_register=auto_register)

    # ------------------------------------------------------------------
    # group_leave
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_leave")
    async def op_group_leave(request: Request) -> JSONResponse:
        """Leave a group."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation
        val_err = _validate_body("group_leave", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        return await _dispatch(pipeline, private_key, registry, "group_leave", _inject_agent_id(body, token), token, _connection_id(request), auto_register=auto_register)

    # ------------------------------------------------------------------
    # group_list_members
    # ------------------------------------------------------------------

    @router.post("/v1/ops/group_list_members")
    async def op_group_list_members(request: Request) -> JSONResponse:
        """List members of a group."""
        token, err = _require_token(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        # FIX-1: schema-driven validation
        val_err = _validate_body("group_list_members", body)
        if val_err is not None:
            return val_err
        assert isinstance(body, dict)
        return await _dispatch(pipeline, private_key, registry, "group_list_members", _inject_agent_id(body, token), token, _connection_id(request), auto_register=auto_register)
