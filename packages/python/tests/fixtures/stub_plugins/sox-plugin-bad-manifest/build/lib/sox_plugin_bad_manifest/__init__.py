# SPDX-License-Identifier: Apache-2.0
"""Bad-manifest stub: sox-plugin.yaml missing required 'signatures' field."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar


class BadManifestMiddleware:
    kind: ClassVar[str] = "interceptor"
    must_run_before: ClassVar[tuple[str, ...]] = ()
    must_run_after: ClassVar[tuple[str, ...]] = ()

    async def __call__(
        self,
        ctx: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:  # pragma: no cover
        return await call_next(ctx)


def make_middleware() -> BadManifestMiddleware:
    return BadManifestMiddleware()


__all__ = ["BadManifestMiddleware", "make_middleware"]
