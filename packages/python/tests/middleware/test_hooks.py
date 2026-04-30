# SPDX-License-Identifier: Apache-2.0
"""Tests for HookDispatcher: pre/post fan-out, deny short-circuit, immutability.

Spec reference: ``docs/adr/0003 §Decision (3)``
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.hooks import HookDecision, HookDispatcher
from sox_protocol.core.middleware.pipeline import Pipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _passthrough(ctx: MiddlewareContext) -> dict[str, object]:
    return {"ok": True}


class RecordingHook:
    """Hook that records the ctx_view it receives."""

    def __init__(self, decision: HookDecision | None = None) -> None:
        self.received: list[Mapping[str, object]] = []
        self._decision = decision

    async def __call__(self, ctx_view: Mapping[str, object]) -> HookDecision | None:
        self.received.append(ctx_view)
        return self._decision


# ---------------------------------------------------------------------------
# Pre-hook fires before chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_hook_fires_before_chain() -> None:
    hook = RecordingHook()
    dispatcher = HookDispatcher(pre={"send": [hook]})

    chain_called = False

    async def _terminal(ctx: MiddlewareContext) -> dict[str, object]:
        nonlocal chain_called
        chain_called = True
        return {"ok": True}

    pipeline = Pipeline([dispatcher], _terminal)
    await pipeline.dispatch("send", {"channel": "x"}, connection_id="c")

    assert len(hook.received) == 1
    assert chain_called


@pytest.mark.asyncio
async def test_pre_hook_ctx_view_is_read_only_mapping() -> None:
    async def _mutating_hook(ctx_view: Mapping[str, object]) -> HookDecision | None:
        with pytest.raises(TypeError, match="read-only"):
            ctx_view["operation"] = "evil"  # type: ignore[index]
        return None

    dispatcher = HookDispatcher(pre={"send": [_mutating_hook]})
    pipeline = Pipeline([dispatcher], _passthrough)
    await pipeline.dispatch("send", {}, connection_id="c")


# ---------------------------------------------------------------------------
# Post-hook fires after response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_hook_fires_after_response() -> None:
    order: list[str] = []

    async def _pre(ctx_view: Mapping[str, object]) -> HookDecision | None:
        order.append("pre")
        return None

    async def _post(ctx_view: Mapping[str, object]) -> HookDecision | None:
        order.append("post")
        return None

    async def _terminal(ctx: MiddlewareContext) -> dict[str, object]:
        order.append("terminal")
        return {"ok": True}

    dispatcher = HookDispatcher(pre={"send": [_pre]}, post={"send": [_post]})
    pipeline = Pipeline([dispatcher], _terminal)
    await pipeline.dispatch("send", {}, connection_id="c")

    assert order == ["pre", "terminal", "post"]


# ---------------------------------------------------------------------------
# Deny decision short-circuits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_deny_short_circuits() -> None:
    deny_error: dict[str, object] = {
        "error_code": "hook_denied",
        "message": "blocked",
        "detail": None,
        "retry_after": None,
    }
    deny_hook = RecordingHook(HookDecision(action="deny", error=deny_error))
    dispatcher = HookDispatcher(pre={"send": [deny_hook]})

    chain_called = False

    async def _terminal(ctx: MiddlewareContext) -> dict[str, object]:
        nonlocal chain_called
        chain_called = True
        return {"ok": True}

    pipeline = Pipeline([dispatcher], _terminal)
    result = await pipeline.dispatch("send", {}, connection_id="c")

    assert result["error_code"] == "hook_denied"
    assert not chain_called


@pytest.mark.asyncio
async def test_hook_deny_without_error_uses_default_envelope() -> None:
    async def _deny(ctx_view: Mapping[str, object]) -> HookDecision | None:
        return HookDecision(action="deny")

    dispatcher = HookDispatcher(pre={"send": [_deny]})
    pipeline = Pipeline([dispatcher], _passthrough)
    result = await pipeline.dispatch("send", {}, connection_id="c")

    assert "error_code" in result


# ---------------------------------------------------------------------------
# Hook cannot mutate ctx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_cannot_mutate_ctx_via_view() -> None:
    """Assigning on ctx_view raises TypeError."""

    async def _mutator(ctx_view: Mapping[str, object]) -> HookDecision | None:
        with pytest.raises(TypeError):
            ctx_view["agent_id"] = "hacked"  # type: ignore[index]
        return None

    dispatcher = HookDispatcher(pre={"send": [_mutator]})
    pipeline = Pipeline([dispatcher], _passthrough)
    await pipeline.dispatch("send", {}, connection_id="c")


# ---------------------------------------------------------------------------
# Allow decision passes through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_allow_decision_passes_through() -> None:
    allow_hook = RecordingHook(HookDecision(action="allow"))
    dispatcher = HookDispatcher(pre={"send": [allow_hook]})
    pipeline = Pipeline([dispatcher], _passthrough)
    result = await pipeline.dispatch("send", {}, connection_id="c")

    assert result == {"ok": True}


# ---------------------------------------------------------------------------
# Hook only fires for matching operation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_hook_only_fires_for_matching_operation() -> None:
    send_hook = RecordingHook()
    dispatcher = HookDispatcher(pre={"send": [send_hook]})
    pipeline = Pipeline([dispatcher], _passthrough)

    await pipeline.dispatch("recv", {}, connection_id="c")

    assert send_hook.received == []


# ---------------------------------------------------------------------------
# _ImmutableContextView — getitem, iter, len, delitem
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ctx_view_getitem_accessible() -> None:
    """Hook can read values from ctx_view via __getitem__."""
    read_values: list[object] = []

    async def _reader(ctx_view: Mapping[str, object]) -> HookDecision | None:
        read_values.append(ctx_view["operation"])
        return None

    dispatcher = HookDispatcher(pre={"send": [_reader]})
    pipeline = Pipeline([dispatcher], _passthrough)
    await pipeline.dispatch("send", {}, connection_id="c")

    assert read_values == ["send"]


@pytest.mark.asyncio
async def test_ctx_view_iter_and_len() -> None:
    """ctx_view supports iteration and len()."""
    iter_keys: list[list[str]] = []
    lengths: list[int] = []

    async def _iter_hook(ctx_view: Mapping[str, object]) -> HookDecision | None:
        iter_keys.append(list(ctx_view))
        lengths.append(len(ctx_view))
        return None

    dispatcher = HookDispatcher(pre={"send": [_iter_hook]})
    pipeline = Pipeline([dispatcher], _passthrough)
    await pipeline.dispatch("send", {}, connection_id="c")

    assert len(iter_keys[0]) > 0
    assert lengths[0] > 0


@pytest.mark.asyncio
async def test_ctx_view_delitem_raises() -> None:
    """del ctx_view[key] raises TypeError."""

    async def _deleter(ctx_view: Mapping[str, object]) -> HookDecision | None:
        with pytest.raises(TypeError, match="read-only"):
            del ctx_view["operation"]  # type: ignore[attr-defined]
        return None

    dispatcher = HookDispatcher(pre={"send": [_deleter]})
    pipeline = Pipeline([dispatcher], _passthrough)
    await pipeline.dispatch("send", {}, connection_id="c")
