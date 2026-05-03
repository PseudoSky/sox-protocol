# SPDX-License-Identifier: Apache-2.0
"""Cyclic-A stub: declares must_run_before: [io.sox.cyclic-b], causing a cycle with cyclic-b."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar


class CyclicAMiddleware:
    kind: ClassVar[str] = "interceptor"
    must_run_before: ClassVar[tuple[str, ...]] = ()
    must_run_after: ClassVar[tuple[str, ...]] = ()

    async def __call__(
        self,
        ctx: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:  # pragma: no cover
        return await call_next(ctx)


def make_middleware() -> CyclicAMiddleware:
    return CyclicAMiddleware()


__all__ = ["CyclicAMiddleware", "make_middleware"]
