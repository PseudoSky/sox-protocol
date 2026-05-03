# SPDX-License-Identifier: Apache-2.0
"""Noop stub plugin for SOX Protocol integration tests.

Conforms to the Middleware Protocol:
- kind: ClassVar[str] = "transformer"
- async __call__(ctx, call_next) -> dict

Pass-through: calls await call_next(ctx) and injects a marker into
ctx.metadata so tests can verify the middleware ran.
"""

from __future__ import annotations

from .middleware import NoopMiddleware


def make_noop_middleware() -> "NoopMiddleware":
    """Factory function declared as the entry-point.

    Returns:
        A fresh NoopMiddleware instance.
    """
    return NoopMiddleware()


__all__ = ["NoopMiddleware", "make_noop_middleware"]
