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

Spec reference: ``spec/ports/middleware.md §2, §5, §7``
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Self

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.errors import ShortCircuitResponse, make_internal_error
from sox_protocol.core.middleware.protocol import CallNext, Middleware

_log = logging.getLogger(__name__)


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
    ) -> dict[str, object]:
        """Dispatch *operation* through the pipeline.

        Creates a fresh :class:`MiddlewareContext` per call (reentrant).

        Args:
            operation: The SOX operation name (e.g. ``"send"``).
            input: Mutable input dict for this tool call.
            connection_id: Opaque connection identifier from the transport.

        Returns:
            Response dict from the first middleware or terminal that produces
            one, conforming to the relevant operation output schema.
        """
        ctx = MiddlewareContext(
            operation=operation,
            input=dict(input),  # shallow copy so callers don't see mutations
            connection_id=connection_id,
        )
        ctx.freeze_correlation_id()

        try:
            return await self._build_call_chain(0)(ctx)
        except ShortCircuitResponse as sc:
            return sc.response
        except Exception as exc:
            _log.exception("Unhandled exception in middleware pipeline: %s", exc)
            return make_internal_error("Internal server error")

    def _build_call_chain(
        self, index: int
    ) -> Callable[[MiddlewareContext], Awaitable[dict[str, object]]]:
        """Recursively build the async call chain starting from *index*."""
        if index >= len(self._middlewares):
            return self._terminal

        mw = self._middlewares[index]
        next_fn: CallNext = self._build_call_chain(index + 1)

        async def _call(ctx: MiddlewareContext) -> dict[str, object]:
            try:
                return await mw(ctx, next_fn)
            except ShortCircuitResponse:
                raise  # propagate to dispatch() for uniform handling
            except Exception as exc:
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
