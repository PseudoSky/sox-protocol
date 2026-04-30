# SPDX-License-Identifier: Apache-2.0
"""Tests for the default middleware chain.

Spec reference: ``spec/ports/middleware.md §4, §9``; ``docs/adr/0003 §Negative consequences``
"""

from __future__ import annotations

import pytest

from sox_protocol.core.middleware.default_chain import DEFAULT_ORDER, build_default_pipeline
from sox_protocol.core.middleware.registry import MiddlewareRegistry

# ---------------------------------------------------------------------------
# DEFAULT_ORDER
# ---------------------------------------------------------------------------


def test_default_order_constant_matches_spec() -> None:
    """DEFAULT_ORDER must contain at minimum the links documented in spec §4."""
    assert "namespace_resolver" in DEFAULT_ORDER
    assert "auth" in DEFAULT_ORDER
    assert "store_dispatch" in DEFAULT_ORDER
    assert "audit_log" in DEFAULT_ORDER
    # Check relative ordering.
    assert DEFAULT_ORDER.index("namespace_resolver") < DEFAULT_ORDER.index("auth")
    assert DEFAULT_ORDER.index("auth") < DEFAULT_ORDER.index("store_dispatch")


def test_default_order_namespace_before_auth() -> None:
    assert DEFAULT_ORDER.index("namespace_resolver") < DEFAULT_ORDER.index("auth")


# ---------------------------------------------------------------------------
# build_default_pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_chain_refuses_unauthenticated_send(
    verifier,
    stub_store,
) -> None:
    """Conformance footgun: unauthenticated send must be rejected."""
    pipeline = build_default_pipeline(verifier=verifier, store=stub_store)

    result = await pipeline.dispatch(
        "send",
        {"channel": "test", "body": {}},  # no signed_request
        connection_id="conn-1",
    )

    assert result.get("error_code") == "identity_failure"


@pytest.mark.asyncio
async def test_chain_still_builds_when_optional_links_absent(
    verifier,
    stub_store,
) -> None:
    """Chain builds successfully when namespace_resolver, rate_limit, etc. are absent."""
    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        pipeline = build_default_pipeline(verifier=verifier, store=stub_store)

    # Pipeline exists and has at least auth + store_dispatch.
    assert "auth" in pipeline.order
    assert "store_dispatch" in pipeline.order
    # Warnings were emitted for absent optional links.
    warned_names = [str(warning.message) for warning in w]
    assert any("namespace_resolver" in msg for msg in warned_names)


@pytest.mark.asyncio
async def test_chain_builds_with_namespace_resolver_registered(
    verifier,
    stub_store,
) -> None:
    """namespace_resolver runs before auth when both are registered."""
    from collections.abc import Awaitable, Callable

    class FakeNamespaceResolver:
        name = "namespace_resolver"
        must_run_before: tuple[str, ...] = ("auth",)
        must_run_after: tuple[str, ...] = ()

        async def __call__(
            self,
            ctx: object,
            call_next: Callable[..., Awaitable[dict[str, object]]],
        ) -> dict[str, object]:
            return await call_next(ctx)  # type: ignore[arg-type]

    registry = MiddlewareRegistry()
    registry.register("namespace_resolver", FakeNamespaceResolver)

    import warnings

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        pipeline = build_default_pipeline(
            verifier=verifier,
            store=stub_store,
            registry=registry,
        )

    order = list(pipeline.order)
    assert order.index("namespace_resolver") < order.index("auth")


@pytest.mark.asyncio
async def test_build_default_pipeline_tolerates_pre_registered_auth_and_store(
    verifier,
    stub_store,
) -> None:
    """build_default_pipeline does not raise when auth/store_dispatch already registered."""
    from sox_protocol.core.middleware.plugins.auth import AuthMiddleware
    from sox_protocol.core.middleware.plugins.store_dispatch import StoreDispatchMiddleware

    registry = MiddlewareRegistry()
    # Pre-register auth and store_dispatch — build_default_pipeline must tolerate this.
    registry.register("auth", lambda: AuthMiddleware(verifier))
    registry.register("store_dispatch", lambda: StoreDispatchMiddleware(stub_store))

    import warnings

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        pipeline = build_default_pipeline(
            verifier=verifier, store=stub_store, registry=registry
        )

    assert "auth" in pipeline.order
    assert "store_dispatch" in pipeline.order


@pytest.mark.asyncio
async def test_default_chain_store_terminal_invoked_on_list_channels(
    verifier,
    stub_store,
) -> None:
    """The _StoreTerminal is exercised when the chain reaches store_dispatch."""
    import warnings

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        pipeline = build_default_pipeline(verifier=verifier, store=stub_store)

    result = await pipeline.dispatch("list_channels", {}, connection_id="conn-1")
    # _StoreTerminal.__call__ was invoked — store_dispatch handled list_channels.
    assert "channels" in result


@pytest.mark.asyncio
async def test_default_chain_passes_list_channels_without_credentials(
    verifier,
    stub_store,
) -> None:
    """list_channels is not auth-enforced; passes through without credentials."""
    pipeline = build_default_pipeline(verifier=verifier, store=stub_store)

    import warnings

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        result = await pipeline.dispatch(
            "list_channels",
            {},
            connection_id="conn-1",
        )

    # No auth error — should return channels list.
    assert "error_code" not in result or result.get("error_code") != "identity_failure"
    assert "channels" in result
