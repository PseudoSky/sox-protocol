# SPDX-License-Identifier: Apache-2.0
"""Stub middleware body for version-mismatch plugin (never actually loaded)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar


class VersionMismatchMiddleware:
    """Stub that will never load due to version mismatch."""

    kind: ClassVar[str] = "interceptor"
    must_run_before: ClassVar[tuple[str, ...]] = ()
    must_run_after: ClassVar[tuple[str, ...]] = ()

    async def __call__(
        self,
        ctx: Any,
        call_next: Callable[[Any], Awaitable[Any]],
    ) -> Any:  # pragma: no cover
        return await call_next(ctx)
