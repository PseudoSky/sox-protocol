# SPDX-License-Identifier: Apache-2.0
"""Middleware Protocol type — the Python binding of the normative pipeline contract.

A middleware unit is any object that:

1. Has a ``name`` attribute (string) — unique within a chain.
2. Declares ordering constraints via ``must_run_before`` and ``must_run_after``
   tuples of middleware names.
3. Is callable as an async function
   ``(ctx: MiddlewareContext, call_next: CallNext) -> dict[str, object]``.

This module defines the ``Middleware`` Protocol so that type-checkers can
verify structural conformance without requiring inheritance.

Spec reference: ``spec/ports/middleware.md §2``
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from sox_protocol.core.middleware.context import MiddlewareContext

# The signature of the ``call_next`` argument passed to each middleware unit.
CallNext = Callable[[MiddlewareContext], Awaitable[dict[str, object]]]


@runtime_checkable
class Middleware(Protocol):
    """Structural protocol for a single middleware unit.

    Implementations do NOT need to inherit from this class; they only need to
    expose the correct attributes and be callable with the correct signature.

    Attributes:
        name: Unique name for this middleware within a pipeline.
        must_run_before: Names of middlewares this one must precede.
        must_run_after: Names of middlewares this one must follow.

    Example::

        class MyMiddleware:
            name = "my_mw"
            must_run_before: tuple[str, ...] = ()
            must_run_after: tuple[str, ...] = ("auth",)

            async def __call__(
                self,
                ctx: MiddlewareContext,
                call_next: CallNext,
            ) -> dict[str, object]:
                # inspect / mutate ctx.input here
                return await call_next(ctx)
    """

    name: str
    must_run_before: tuple[str, ...]
    must_run_after: tuple[str, ...]

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: CallNext,
    ) -> dict[str, object]:
        """Process *ctx* and either forward to *call_next* or short-circuit.

        Args:
            ctx: The per-call context object.
            call_next: Async callable to forward to the next pipeline stage.

        Returns:
            A response dict conforming to the relevant operation output schema.
        """
        ...
