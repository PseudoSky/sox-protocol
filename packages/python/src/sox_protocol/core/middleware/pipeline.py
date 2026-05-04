# SPDX-License-Identifier: Apache-2.0
"""Pipeline: composes an ordered list of middlewares around a terminal handler.

Each :meth:`Pipeline.dispatch` call is reentrant: a fresh
:class:`~sox_protocol.core.middleware.context.MiddlewareContext` is created per
invocation so concurrent dispatches never share context state.

Exception handling per ``spec/ports/middleware.md §7``:

- :class:`~sox_protocol.core.middleware.errors.ShortCircuitResponse` raised by
  a middleware is caught and its ``.response`` is returned directly.
- Any other uncaught exception from a middleware is caught, logged, and
  converted to an ``internal_error`` sox-error envelope — no stack traces
  or implementation details are forwarded to the caller.

Observability (``pipeline_trace``, per analysis §7.5 risk #7 + suggestions-v2.md §Q3):

Every dispatch produces a ``metadata["pipeline_trace"]`` array in the response.
Each entry has the shape::

    {
        "plugin_id": str,        # e.g. "auth", "store_dispatch"
        "kind": str,             # e.g. "auth", "transformer", "store", "unknown"
        "started_at": float,     # monotonic timestamp (time.monotonic())
        "finished_at": float,
        "verdict": str,          # "passed" | "rejected" | "errored" | "skipped"
        "error_code": str | None,
        "correlation_id": str,   # echoed from MiddlewareContext.correlation_id (frozen)
    }

Emission is unconditional — every plugin in the chain is traced automatically
via the Pipeline base, NOT per-plugin opt-in.  Middlewares that were not
reached due to an upstream short-circuit receive ``verdict="skipped"``.

Spec reference: ``spec/ports/middleware.md §2, §5, §7``
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Self

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.errors import ShortCircuitResponse, make_internal_error
from sox_protocol.core.middleware.protocol import Middleware

_log = logging.getLogger(__name__)

# Sentinel used to mark a trace entry that has not yet finished.
_UNFINISHED = object()


def _get_kind(mw: Middleware) -> str:
    """Return the ``kind`` string for a middleware, falling back to ``"unknown"``.

    Plugins MAY declare a ``kind`` class attribute (str).  The Pipeline reads
    it via ``getattr`` so the :class:`Middleware` Protocol does not need to
    mandate the field for backward compatibility.
    """
    kind = getattr(mw, "kind", None)
    return str(kind) if isinstance(kind, str) else "unknown"


class Pipeline:
    """Ordered middleware chain with a terminal dispatch handler.

    Args:
        middlewares: Ordered list of middleware units.  The first element is
            outermost (receives the call first); the last element is innermost
            (calls the terminal).
        terminal: Async callable invoked after all middlewares pass through.
            Typically ``StoreDispatchMiddleware`` or a test stub.

    Attributes:
        order: Tuple of middleware names in execution order.
    """

    def __init__(
        self,
        middlewares: list[Middleware],
        terminal: Callable[[MiddlewareContext], Awaitable[dict[str, object]]],
    ) -> None:
        self._middlewares = list(middlewares)
        self._terminal = terminal
        self.order: tuple[str, ...] = tuple(m.name for m in self._middlewares)

    async def dispatch(
        self,
        operation: str,
        input: dict[str, object],
        *,
        connection_id: str,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Dispatch *operation* through the pipeline.

        Creates a fresh :class:`MiddlewareContext` per call (reentrant).
        After the chain completes (or short-circuits), injects
        ``metadata["pipeline_trace"]`` and ``metadata["correlation_id"]``
        into the response dict.

        Args:
            operation: The SOX operation name (e.g. ``"send"``).
            input: Mutable input dict for this tool call.
            connection_id: Opaque connection identifier from the transport.
            metadata: Optional pre-populated metadata dict.  Use this to
                inject connection-bound data (e.g. ``_connection_credential``)
                that MUST NOT appear in the tool-call input dict (spec §6).

        Returns:
            Response dict from the first middleware or terminal that produces
            one, conforming to the relevant operation output schema.  Always
            contains ``metadata["pipeline_trace"]`` with per-plugin trace
            entries and ``metadata["correlation_id"]``.
        """
        ctx = MiddlewareContext(
            operation=operation,
            input=dict(input),  # shallow copy so callers don't see mutations
            connection_id=connection_id,
            metadata=dict(metadata) if metadata is not None else None,
        )
        ctx.freeze_correlation_id()

        # Pre-allocate trace entries (all start as "skipped").
        # The call chain will update entries in-place as each middleware runs.
        trace: list[dict[str, object]] = []
        for mw in self._middlewares:
            trace.append(
                {
                    "plugin_id": mw.name,
                    "kind": _get_kind(mw),
                    "started_at": 0.0,
                    "finished_at": 0.0,
                    "verdict": "skipped",
                    "error_code": None,
                    "correlation_id": ctx.correlation_id,
                }
            )
        ctx._meta["pipeline_trace"] = trace

        result: dict[str, object]
        try:
            result = await self._build_call_chain(0, trace)(ctx)
        except ShortCircuitResponse as sc:
            result = sc.response
        except Exception as exc:
            _log.exception("Unhandled exception in middleware pipeline: %s", exc)
            result = make_internal_error("Internal server error")

        return self._attach_trace(result, trace, ctx.correlation_id)

    def _attach_trace(
        self,
        result: dict[str, object],
        trace: list[dict[str, object]],
        correlation_id: str,
    ) -> dict[str, object]:
        """Inject ``pipeline_trace`` and ``correlation_id`` into *result*.

        The trace is written under ``result["metadata"]["pipeline_trace"]``.
        If ``result`` already contains a ``"metadata"`` key whose value is a
        dict, the trace is merged in.  Otherwise a fresh ``metadata`` sub-dict
        is created.

        Args:
            result: The raw response dict from the pipeline.
            trace: The completed per-plugin trace list.
            correlation_id: The frozen correlation ID for this dispatch.

        Returns:
            *result* with ``metadata`` updated in-place (no copy).
        """
        meta = result.get("metadata")
        if not isinstance(meta, dict):
            meta = {}
            result["metadata"] = meta
        meta["pipeline_trace"] = trace
        meta["correlation_id"] = correlation_id
        return result

    def _build_call_chain(
        self, index: int, trace: list[dict[str, object]]
    ) -> Callable[[MiddlewareContext], Awaitable[dict[str, object]]]:
        """Recursively build the async call chain starting from *index*.

        Each layer wraps the middleware call with timing and verdict recording.
        The trace entry at ``trace[index]`` is updated in-place.
        """
        if index >= len(self._middlewares):
            return self._terminal

        mw = self._middlewares[index]
        entry = trace[index]
        next_fn = self._build_call_chain(index + 1, trace)

        async def _call(ctx: MiddlewareContext) -> dict[str, object]:
            entry["started_at"] = time.monotonic()
            try:
                response = await mw(ctx, next_fn)
                entry["finished_at"] = time.monotonic()
                # A response that contains "error_code" is a sox-error envelope —
                # the middleware rejected the request (e.g. AuthMiddleware calling
                # call_next after a pass but a downstream raising; or a middleware
                # returning an error dict directly without raising ShortCircuit).
                if isinstance(response, dict) and "error_code" in response:
                    entry["verdict"] = "rejected"
                    entry["error_code"] = response.get("error_code")
                else:
                    entry["verdict"] = "passed"
                return response
            except ShortCircuitResponse as sc:
                entry["finished_at"] = time.monotonic()
                # ShortCircuitResponse.response is always a sox-error envelope.
                err_code = sc.response.get("error_code") if isinstance(sc.response, dict) else None
                entry["verdict"] = "rejected"
                entry["error_code"] = err_code
                raise  # propagate to dispatch() for uniform handling
            except Exception as exc:
                entry["finished_at"] = time.monotonic()
                entry["verdict"] = "errored"
                _log.exception(
                    "Middleware %r raised unhandled exception: %s", mw.name, exc
                )
                raise  # let dispatch() convert to internal_error

        return _call


class PipelineBuilder:
    """Fluent builder for :class:`Pipeline`.

    Usage::

        pipeline = (
            PipelineBuilder()
            .add(namespace_resolver_mw)
            .add(auth_mw)
            .add(store_dispatch_mw)
            .build(terminal=store_dispatch_mw)
        )

    Note: the terminal is typically the *same* object as the last middleware
    added when using ``StoreDispatchMiddleware`` as a terminal adapter;
    or it can be a separate async callable for testing.
    """

    def __init__(self) -> None:
        self._middlewares: list[Middleware] = []

    def add(self, mw: Middleware) -> Self:
        """Append *mw* to the chain.

        Args:
            mw: A middleware unit conforming to the ``Middleware`` protocol.

        Returns:
            *self* for chaining.
        """
        self._middlewares.append(mw)
        return self

    def build(
        self,
        terminal: Callable[[MiddlewareContext], Awaitable[dict[str, object]]],
    ) -> Pipeline:
        """Build and return the :class:`Pipeline`.

        Args:
            terminal: The terminal handler invoked after all middlewares
                pass through.

        Returns:
            A configured :class:`Pipeline`.
        """
        return Pipeline(list(self._middlewares), terminal)
