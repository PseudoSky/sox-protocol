# SPDX-License-Identifier: Apache-2.0
"""Cyclic-B stub: declares must_run_before: [io.sox.cyclic-a], causing a cycle with cyclic-a."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar


class CyclicBMiddleware:
    kind: ClassVar[str] = "interceptor"
    must_run_before: ClassVar[tuple[str, ...]] = ()
    must_run_after: ClassVar[tuple[str, ...]] = ()

    async def __call__(
        self,
        ctx: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:  # pragma: no cover
        return await call_next(ctx)


def make_middleware() -> CyclicBMiddleware:
    return CyclicBMiddleware()


__all__ = ["CyclicBMiddleware", "make_middleware"]
