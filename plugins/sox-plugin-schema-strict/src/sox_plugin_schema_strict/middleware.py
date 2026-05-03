# SPDX-License-Identifier: Apache-2.0
"""SchemaStrictMiddleware — kind: transformer.

Validates each SOX operation's ``ctx.input`` against the corresponding
``spec/operations/<op>.input.schema.json`` before dispatching to the
next stage in the Pipeline.

Design decisions
----------------
Schema source
    Schemas are loaded from ``spec/operations/`` at the repo root.  The
    plugin accepts an optional ``schemas_dir`` constructor argument so
    callers (and the host bootstrap) can supply the canonical path.  When
    ``schemas_dir`` is ``None``, the plugin falls back to the environment
    variable ``SOX_PLUGIN_IO_SOX_SCHEMA_STRICT_SCHEMAS_DIR`` (the
    canonicalized env-var form per plugin-contract §7.2).  If that is also
    absent, the plugin attempts to discover ``spec/operations/`` relative
    to the repo root by traversing the CWD's parent chain — suitable for
    in-repo development/CI but not for installed production use without
    explicit configuration.

    **Why not bundle copies?**  The spec schemas are the source of truth;
    bundling copies would require a release every time a schema changes and
    creates a divergence risk.  Loading from ``spec/`` directly ties the
    plugin to a checked-out repo, which is acceptable for v1 in-repo use
    and for CI.  Production deployments MUST set
    ``SOX_PLUGIN_IO_SOX_SCHEMA_STRICT_SCHEMAS_DIR`` to the path of the
    ``spec/operations/`` directory.

Schema loading
    Schemas are loaded lazily per operation on first access and cached in
    ``_validators``.  Compiling a JSON Schema validator is inexpensive
    (sub-millisecond) but caching avoids repeated filesystem reads on hot
    paths.

Failure contract (spec/ports/middleware/03-plugin-contract.md §3.2)
    The current Python Pipeline uses continuation-passing style (call_next)
    for all middleware kinds, including transformers.  The pipeline catches
    ``ShortCircuitResponse`` at dispatch level and surfaces it as the final
    response.  To integrate without requiring changes to the host pipeline,
    this middleware raises ``ShortCircuitResponse`` with a ``validation_error``
    envelope on failure — matching the ``validation_error`` error code defined
    in ``spec/envelopes/sox-error.schema.json``.

    Phase 03-migrate-routes note: This is intentionally consistent with the
    ``error_code="validation_error"`` shape produced by ``routes._validate_body``.
    When phase 03 deletes ``_validate_body``, the client-visible error payload
    will be identical (same error_code, same violations list shape).

Routes._validate_body parity
    The existing ``routes._validate_body`` builds a violations list as::

        [{"field": ".".join(path) or "<root>", "issue": err.message}, ...]

    This middleware replicates that shape verbatim so phase 03-migrate-routes
    can delete ``routes._validate_body`` without changing client-visible error
    payloads.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

import jsonschema
import jsonschema.exceptions

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env-var canonicalization per plugin-contract §7.2:
# id = io.sox.schema-strict → SOX_PLUGIN_IO_SOX_SCHEMA_STRICT_SCHEMAS_DIR
# ---------------------------------------------------------------------------
_SCHEMAS_DIR_ENVVAR = "SOX_PLUGIN_IO_SOX_SCHEMA_STRICT_SCHEMAS_DIR"

# All 15 SOX v1 operations that have input schemas.
_KNOWN_OPERATIONS: frozenset[str] = frozenset(
    [
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
)


def _find_schemas_dir_from_cwd() -> Path | None:
    """Walk up from CWD searching for a ``spec/operations/`` directory.

    Returns:
        The ``spec/operations/`` Path if found, else ``None``.
    """
    candidate = Path.cwd()
    for _ in range(8):  # max 8 levels up
        ops = candidate / "spec" / "operations"
        if ops.is_dir():
            return ops
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return None


class SchemaStrictMiddleware:
    """Transformer middleware: validates ``ctx.input`` before dispatch.

    Implements the ``Middleware`` Protocol (name, must_run_before,
    must_run_after, async __call__).

    On validation failure, raises
    :class:`~sox_protocol.core.middleware.errors.ShortCircuitResponse`
    with a ``validation_error`` sox-error envelope.  On success, calls
    ``call_next(ctx)`` and returns its result.

    Attributes:
        kind: Always ``"transformer"`` — used by the host for kind dispatch.
        name: Unique middleware name within the pipeline.
        must_run_before: Run before ``store_dispatch``.
        must_run_after: No constraint (empty).
    """

    kind: ClassVar[str] = "transformer"
    name: ClassVar[str] = "schema_strict"
    must_run_before: ClassVar[tuple[str, ...]] = ("store_dispatch",)
    must_run_after: ClassVar[tuple[str, ...]] = ()

    def __init__(self, schemas_dir: Path | None = None) -> None:
        """Initialise the middleware, resolving the schemas directory.

        Args:
            schemas_dir: Explicit path to ``spec/operations/`` directory.
                When ``None``, falls back to the env-var, then CWD search.
        """
        self._schemas_dir: Path | None = self._resolve_schemas_dir(schemas_dir)
        # Lazy per-operation cache: op_name → compiled validator
        self._validators: dict[str, jsonschema.Draft202012Validator] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_schemas_dir(explicit: Path | None) -> Path | None:
        """Resolve the schemas directory from explicit arg, env-var, or CWD.

        Args:
            explicit: Caller-supplied path (highest priority).

        Returns:
            Resolved ``Path`` or ``None`` if not found.
        """
        if explicit is not None:
            return explicit
        env_val = os.environ.get(_SCHEMAS_DIR_ENVVAR)
        if env_val:
            p = Path(env_val)
            if p.is_dir():
                return p
            _log.warning(
                "%s=%r does not point to an existing directory; ignoring.",
                _SCHEMAS_DIR_ENVVAR,
                env_val,
            )
        # CWD search fallback (in-repo dev/CI)
        return _find_schemas_dir_from_cwd()

    def _get_validator(
        self, op_name: str
    ) -> jsonschema.Draft202012Validator | None:
        """Return a cached validator for *op_name*, loading lazily.

        Args:
            op_name: SOX operation name.

        Returns:
            Compiled validator, or ``None`` if schemas_dir not set or
            schema file not found.
        """
        if op_name in self._validators:
            return self._validators[op_name]

        if self._schemas_dir is None:
            return None

        schema_path = self._schemas_dir / f"{op_name}.input.schema.json"
        if not schema_path.exists():
            return None

        with schema_path.open(encoding="utf-8") as fh:
            schema: dict[str, Any] = json.load(fh)
        validator = jsonschema.Draft202012Validator(schema)
        self._validators[op_name] = validator
        return validator

    @staticmethod
    def _build_violations(
        validator: jsonschema.Draft202012Validator,
        body: object,
    ) -> list[dict[str, str]]:
        """Collect all schema violations for *body*.

        Replicates the exact violation shape used by ``routes._validate_body``
        so phase 03-migrate-routes can delete that function without changing
        client-visible error payloads.

        Args:
            validator: Compiled JSON Schema validator.
            body: Parsed request body to validate.

        Returns:
            List of ``{"field": str, "issue": str}`` dicts, sorted by field
            path (ascending).
        """
        errors = sorted(validator.iter_errors(body), key=lambda e: list(e.path))
        return [
            {
                "field": ".".join(str(p) for p in err.absolute_path) or "<root>",
                "issue": err.message,
            }
            for err in errors
        ]

    @staticmethod
    def _make_validation_error_envelope(
        op_name: str,
        violations: list[dict[str, str]],
    ) -> dict[str, object]:
        """Build a sox-error envelope for a validation failure.

        Shape matches ``spec/envelopes/sox-error.schema.json`` and the
        response produced by ``routes._validate_body``.

        Args:
            op_name: SOX operation name (included in the human-readable message).
            violations: List of ``{"field": str, "issue": str}`` dicts.

        Returns:
            A ``dict`` conforming to ``sox-error.schema.json`` with
            ``error_code="validation_error"``.
        """
        return {
            "error_code": "validation_error",
            "message": f"Input does not conform to {op_name}.input.schema.json.",
            "detail": {"violations": violations},
        }

    # ------------------------------------------------------------------
    # Middleware __call__
    # ------------------------------------------------------------------

    async def __call__(
        self,
        ctx: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Validate ``ctx.input`` then forward to ``call_next``.

        On validation failure, raises ``ShortCircuitResponse`` with a
        ``validation_error`` envelope (HTTP 400 semantics).  On success,
        calls and returns ``call_next(ctx)``.

        Args:
            ctx: ``MiddlewareContext`` — provides ``.operation`` and
                ``.input``.
            call_next: The next stage in the Pipeline.

        Returns:
            The response dict from downstream.

        Raises:
            ShortCircuitResponse: When ``ctx.input`` violates the operation
                schema.  Carries a ``validation_error`` envelope.
        """
        # Import here to avoid hard coupling at import time (the plugin is
        # installed outside the core package tree; the import works at runtime
        # when the plugin is loaded by a sox-protocol host).
        from sox_protocol.core.middleware.errors import ShortCircuitResponse

        op_name: str = getattr(ctx, "operation", "")
        body: object = getattr(ctx, "input", {})

        validator = self._get_validator(op_name)
        if validator is None:
            if op_name in _KNOWN_OPERATIONS:
                # Known operation but schemas_dir not configured — warn and
                # pass through rather than silently corrupting the request.
                _log.warning(
                    "SchemaStrictMiddleware: no schema found for operation %r "
                    "(schemas_dir=%r). Skipping validation.",
                    op_name,
                    self._schemas_dir,
                )
            # Unknown operation or no schema dir — pass through.
            return await call_next(ctx)

        violations = self._build_violations(validator, body)
        if violations:
            envelope = self._make_validation_error_envelope(op_name, violations)
            raise ShortCircuitResponse(envelope)

        return await call_next(ctx)
