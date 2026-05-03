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
from collections.abc import Awaitable, Callable
from typing import Any

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
        async def _noop(c: MiddlewareContext) -> dict[str, object]:
            return {}  # terminal never calls next

        return await self._store_mw(ctx, _noop)


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


def extend_pipeline_with_registry(
    base_pipeline: Pipeline,
    registry: MiddlewareRegistry,
    terminal: Callable[..., Awaitable[Any]],
) -> Pipeline:
    """Rebuild Pipeline with default chain + registered plugin factories.

    Plugin middlewares (from ``registry.resolved_order``) are inserted into
    the default chain in a position that respects each plugin's
    ``must_run_before`` constraints against the default-chain middlewares.
    The terminal handler is preserved.

    Insertion algorithm: for each plugin middleware (in ``resolved_order``),
    find the first default-chain middleware whose name appears in the plugin's
    ``must_run_before`` tuple and insert the plugin before that position.
    If no ``must_run_before`` constraint applies to the existing chain,
    the plugin is appended at the end.

    This helper is called by both server bootstraps (stdio lifespan and HTTP
    ``create_app``) after ``load_plugins()`` has been invoked on *registry*.
    If ``resolved_order`` is empty (no plugins discovered, or
    ``--no-discovery`` set), the returned Pipeline is identical to
    *base_pipeline* with the caller-supplied *terminal*.

    Per analysis §7.5 risk #4 (hot-reload deferred): the pipeline is rebuilt
    **once at startup**, never per-request.  ``Pipeline.with_appended`` is
    intentionally absent from this module to prevent per-request mutation.

    Args:
        base_pipeline: The pipeline returned by ``build_default_pipeline()``.
            Its existing ``_middlewares`` list forms the default chain prefix.
        registry: The ``MiddlewareRegistry`` whose ``resolved_order`` lists the
            plugin ids to append.  Each id must already be registered on
            *registry* (``load_plugins()`` guarantees this).
        terminal: The terminal async callable.  Should be the same terminal
            used to build *base_pipeline* (e.g. ``_StoreTerminal``).  Passed
            explicitly because ``Pipeline._terminal`` is private.

    Returns:
        A new :class:`Pipeline` whose middleware list is the default chain
        interleaved with the ordered plugin middlewares, respecting
        ``must_run_before`` constraints.
    """
    # Extract the existing default-chain middlewares.
    chain: list[Any] = list(base_pipeline._middlewares)  # noqa: SLF001

    # Insert each plugin middleware respecting ordering constraints.
    #
    # The insertion algorithm must handle two interacting constraints:
    #
    # 1. ``must_run_before`` on the *plugin*: the plugin must appear before
    #    those named middlewares in the chain.
    # 2. ``must_run_before`` on *existing* chain members that name a slot
    #    the plugin is replacing (e.g. ``auth.must_run_before`` includes
    #    ``"schema_validator"`` — a plugin that fills the schema_validator
    #    role should therefore come AFTER auth, not before it).
    #
    # Strategy: compute a valid window [earliest_ok, latest_ok) for insertion:
    # - ``earliest_ok`` = one past the last existing middleware that declares
    #   this plugin's name OR the plugin's ``kind`` in its own
    #   ``must_run_before``.  This handles "auth must run before schema_strict".
    # - ``latest_ok`` = the index of the first existing middleware that appears
    #   in the plugin's own ``must_run_before`` set (the plugin must be before
    #   that middleware).
    # - If window is valid (earliest_ok <= latest_ok), insert at earliest_ok
    #   (as early as possible while respecting all constraints).
    # - If window is degenerate (earliest_ok > latest_ok), fall back to
    #   inserting at latest_ok (must_run_before wins; ordering cycle is a
    #   caller misconfiguration, not our fault here).
    # - If no must_run_before constraint fires, append at end.
    for plugin_id in registry.resolved_order:
        factory = registry.get(plugin_id)
        mw = factory()

        plugin_name: str = getattr(mw, "name", plugin_id)
        must_run_before: tuple[str, ...] = getattr(mw, "must_run_before", ())
        must_run_after: tuple[str, ...] = getattr(mw, "must_run_after", ())

        # latest_ok: the plugin must appear BEFORE any existing middleware
        # whose name is in must_run_before.
        latest_ok: int | None = None
        if must_run_before:
            for i, existing_mw in enumerate(chain):
                if getattr(existing_mw, "name", None) in must_run_before:
                    latest_ok = i
                    break

        # earliest_ok: the plugin must appear AFTER any existing middleware
        # that either (a) names the plugin in its own must_run_before, or
        # (b) appears in this plugin's must_run_after.
        earliest_ok: int = 0
        for i, existing_mw in enumerate(chain):
            existing_name: str | None = getattr(existing_mw, "name", None)
            existing_must_before: tuple[str, ...] = getattr(
                existing_mw, "must_run_before", ()
            )
            if existing_name in must_run_after:
                # Plugin must run after this existing middleware.
                earliest_ok = i + 1
            if plugin_name in existing_must_before:
                # This existing middleware says it must run before the plugin.
                earliest_ok = max(earliest_ok, i + 1)

        if latest_ok is not None:
            insert_at = max(earliest_ok, 0)
            # Clamp to latest_ok in case of conflicting constraints.
            if insert_at > latest_ok:
                insert_at = latest_ok
            chain.insert(insert_at, mw)
        else:
            chain.append(mw)

    return Pipeline(chain, terminal)
