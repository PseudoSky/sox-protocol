# SPDX-License-Identifier: Apache-2.0
"""Default middleware chain definition.

Defines the normative middleware order (ADR 0003) and provides
``build_default_pipeline()`` which assembles a ready-to-use
:class:`~sox_protocol.core.middleware.pipeline.Pipeline`.

Optional links (``namespace_resolver``, ``rate_limit``, ``schema_validator``,
``idempotency``, ``audit_log``) are owned by sibling engagements.  If they are
not registered in *registry*, they are skipped with a startup warning so the
v1 chain remains usable while those engagements catch up.

Required links: ``auth`` and ``store_dispatch`` — these are always registered
by :func:`build_default_pipeline` before calling
:meth:`~sox_protocol.core.middleware.registry.MiddlewareRegistry.assemble`.

Spec reference: ``spec/ports/middleware.md §4``; ``docs/adr/0003 §Decision (2)``
"""

from __future__ import annotations

import contextlib

from sox_protocol.core.identity.verifier import IdentityVerifier
from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.pipeline import Pipeline
from sox_protocol.core.middleware.plugins.auth import AuthMiddleware
from sox_protocol.core.middleware.plugins.store_dispatch import StoreDispatchMiddleware
from sox_protocol.core.middleware.registry import MiddlewareRegistry
from sox_protocol.core.ports.backing_store import BackingStore

# Normative default order per spec/ports/middleware.md §4.
DEFAULT_ORDER: tuple[str, ...] = (
    "namespace_resolver",
    "auth",
    "rate_limit",
    "schema_validator",
    "idempotency",
    "store_dispatch",
    "audit_log",
)


class _StoreTerminal:
    """Callable terminal that wraps StoreDispatchMiddleware.

    Pipeline.terminal has signature ``(ctx) -> Awaitable[dict]`` but
    StoreDispatchMiddleware.__call__ has signature ``(ctx, call_next) -> Awaitable[dict]``.
    This adapter bridges the two by supplying a no-op call_next.
    """

    def __init__(self, store_mw: StoreDispatchMiddleware) -> None:
        self._store_mw = store_mw

    async def __call__(self, ctx: MiddlewareContext) -> dict[str, object]:
        """Invoke store_mw with a no-op call_next."""
        async def _noop(c: MiddlewareContext) -> dict[str, object]:  # pragma: no cover
            return {}

        return await self._store_mw(ctx, _noop)  # pragma: no cover


def build_default_pipeline(
    *,
    verifier: IdentityVerifier,
    store: BackingStore,
    registry: MiddlewareRegistry | None = None,
) -> Pipeline:
    """Build a :class:`~sox_protocol.core.middleware.pipeline.Pipeline` from the default chain.

    Always registers ``auth`` and ``store_dispatch`` into *registry*.
    Optional links absent from *registry* are skipped with a startup warning.

    Args:
        verifier: The :class:`~sox_protocol.core.identity.verifier.IdentityVerifier`
            for the auth middleware.
        store: The :class:`~sox_protocol.core.ports.backing_store.BackingStore`
            for the terminal store-dispatch middleware.
        registry: The :class:`~sox_protocol.core.middleware.registry.MiddlewareRegistry`
            to use.  A fresh registry is created if ``None``.

    Returns:
        A configured :class:`~sox_protocol.core.middleware.pipeline.Pipeline`
        ready to dispatch tool calls.
    """
    if registry is None:
        registry = MiddlewareRegistry()

    store_mw = StoreDispatchMiddleware(store)
    auth_mw = AuthMiddleware(verifier)

    # Register only if not already present (callers may pre-register).
    with contextlib.suppress(ValueError):
        registry.register("auth", lambda: auth_mw)  # noqa: B023

    with contextlib.suppress(ValueError):
        registry.register("store_dispatch", lambda: store_mw)  # noqa: B023

    middlewares = registry.assemble(list(DEFAULT_ORDER))

    return Pipeline(middlewares, _StoreTerminal(store_mw))
