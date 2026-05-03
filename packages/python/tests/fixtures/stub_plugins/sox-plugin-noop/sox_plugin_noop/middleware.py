# SPDX-License-Identifier: Apache-2.0
"""Noop middleware: pass-through with a metadata marker."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar


class NoopMiddleware:
    """Minimal Middleware conforming to the SOX Middleware Protocol.

    Injects ``"sox_noop_ran": True`` into ctx.metadata before calling next
    so integration tests can verify the middleware executed.
    """

    kind: ClassVar[str] = "transformer"
    must_run_before: ClassVar[tuple[str, ...]] = ()
    must_run_after: ClassVar[tuple[str, ...]] = ()

    async def __call__(
        self,
        ctx: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Pass through, injecting a marker into ctx.metadata."""
        if hasattr(ctx, "metadata") and isinstance(ctx.metadata, dict):
            ctx.metadata["sox_noop_ran"] = True
        return await call_next(ctx)
