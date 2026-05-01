# SPDX-License-Identifier: Apache-2.0
"""Tests for the default middleware chain.

Spec reference: ``spec/ports/middleware.md §4, §9``; ``docs/adr/0003 §Negative consequences``
"""

from __future__ import annotations

import pytest

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.default_chain import (
    DEFAULT_ORDER,
    _StoreTerminal,
    build_default_pipeline,
)
from sox_protocol.core.middleware.plugins.store_dispatch import StoreDispatchMiddleware
from sox_protocol.core.middleware.registry import MiddlewareRegistry
from tests.middleware.conftest import StubBackingStore

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


# ---------------------------------------------------------------------------
# _StoreTerminal — direct unit tests (covers the adapter with no pragma escape)
# ---------------------------------------------------------------------------


def _make_terminal(store: StubBackingStore) -> _StoreTerminal:
    return _StoreTerminal(StoreDispatchMiddleware(store))


def _ctx(op: str, inp: dict[str, object] | None = None) -> MiddlewareContext:
    return MiddlewareContext(
        operation=op,
        input=inp or {},
        connection_id="conn-terminal-test",
    )


@pytest.mark.asyncio
async def test_store_terminal_send(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("send", {"channel": "ch", "sender": "alice", "body": {}}))
    assert "message_id" in result
    assert result["channel"] == "ch"


@pytest.mark.asyncio
async def test_store_terminal_recv(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("recv", {"agent_id": "alice"}))
    assert "messages" in result
    assert "drained_at" in result


@pytest.mark.asyncio
async def test_store_terminal_subscribe(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("subscribe", {"agent_id": "alice", "pattern": "ch:*"}))
    assert result["subscribed"] is True
    assert "matched_channels" in result


@pytest.mark.asyncio
async def test_store_terminal_unsubscribe(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("unsubscribe", {"agent_id": "alice", "patterns": ["ch:*"]}))
    assert "removed" in result
    assert "pending_cleared" in result


@pytest.mark.asyncio
async def test_store_terminal_list_channels(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("list_channels", {}))
    assert "channels" in result


@pytest.mark.asyncio
async def test_store_terminal_list_agents(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("list_agents", {}))
    assert "agents" in result


@pytest.mark.asyncio
async def test_store_terminal_channels_ack(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(
        _ctx("channels_ack", {"agent_id": "alice", "message_id": "msg-1", "status": "ack"})
    )
    assert result["message_id"] == "msg-1"
    assert result["status"] == "ack"


@pytest.mark.asyncio
async def test_store_terminal_channels_heartbeat(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(
        _ctx("channels_heartbeat", {"agent_id": "alice", "status": "active"})
    )
    assert result["agent_id"] == "alice"
    assert "recorded_at" in result


@pytest.mark.asyncio
async def test_store_terminal_channels_collect(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("channels_collect", {"agent_id": "alice"}))
    assert "messages" in result
    assert "drained_at" in result


@pytest.mark.asyncio
async def test_store_terminal_replay(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("replay", {"channel": "ch", "since": 0}))
    assert "messages" in result
    assert "has_more" in result


@pytest.mark.asyncio
async def test_store_terminal_group_create(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("group_create", {"creator_id": "alice"}))
    assert "group_id" in result
    assert "created_at" in result


@pytest.mark.asyncio
async def test_store_terminal_group_invite(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(
        _ctx(
            "group_invite",
            {"inviter_id": "alice", "group_id": "grp-1", "invitee_id": "bob"},
        )
    )
    assert result["invited"] is True
    assert result["agent_id"] == "bob"


@pytest.mark.asyncio
async def test_store_terminal_group_join(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("group_join", {"agent_id": "bob", "group_id": "grp-1"}))
    assert result["joined"] is True
    assert result["group_id"] == "grp-1"


@pytest.mark.asyncio
async def test_store_terminal_group_leave(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("group_leave", {"agent_id": "bob", "group_id": "grp-1"}))
    assert result["left"] is True
    assert result["group_id"] == "grp-1"


@pytest.mark.asyncio
async def test_store_terminal_group_list_members(stub_store: StubBackingStore) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(
        _ctx("group_list_members", {"agent_id": "alice", "group_id": "grp-1"})
    )
    assert result["group_id"] == "grp-1"
    assert "members" in result


@pytest.mark.asyncio
async def test_store_terminal_unknown_op_returns_internal_error(
    stub_store: StubBackingStore,
) -> None:
    terminal = _make_terminal(stub_store)
    result = await terminal(_ctx("nonexistent_op", {}))
    assert result["error_code"] == "internal_error"
