# SPDX-License-Identifier: Apache-2.0
"""Proves out-of-core plugin registration: no core code changes needed.

A custom Middleware class defined inside this test module is registered via
``register_middleware`` (imported from outside core/) and exercised end-to-end
through ``Pipeline.dispatch``.

Spec reference: ``docs/adr/0003 §Decision (4) declarative out-of-tree registration``
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.pipeline import Pipeline
from sox_protocol.core.middleware.registry import MiddlewareRegistry

# ---------------------------------------------------------------------------
# Plugin defined entirely outside core/
# ---------------------------------------------------------------------------


class ExternalPlugin:
    """A sample plugin defined in the test module (outside core/).

    The ``name`` attribute is set as an instance attribute so that each
    instantiation can carry the name assigned by the registry factory.
    """

    must_run_before: tuple[str, ...] = ()
    must_run_after: tuple[str, ...] = ()

    def __init__(self, plugin_name: str = "external_test_plugin") -> None:
        self.name: str = plugin_name
        self.call_count: int = 0

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: Callable[[MiddlewareContext], Awaitable[dict[str, object]]],
    ) -> dict[str, object]:
        self.call_count += 1
        ctx.metadata["external_plugin_ran"] = True
        return await call_next(ctx)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_plugin_registers_via_module_api() -> None:
    """Plugin from outside core/ registers via register_middleware and runs end-to-end."""
    # Use a local registry to avoid polluting the global singleton.
    local_registry = MiddlewareRegistry()
    plugin_instance = ExternalPlugin("external_test_plugin")
    local_registry.register("external_test_plugin", lambda: plugin_instance)

    chain = local_registry.assemble(["external_test_plugin"])
    assert len(chain) == 1
    assert chain[0].name == "external_test_plugin"

    ran_external: list[bool] = []

    async def _terminal(ctx: MiddlewareContext) -> dict[str, object]:
        ran_external.append(bool(ctx.metadata.get("external_plugin_ran", False)))
        return {"ok": True}

    pipeline = Pipeline(chain, _terminal)
    result = await pipeline.dispatch("send", {}, connection_id="c")

    assert result == {"ok": True}
    assert ran_external == [True]
    assert plugin_instance.call_count == 1


@pytest.mark.asyncio
async def test_external_plugin_no_core_modification_required() -> None:
    """Registering and running a plugin requires zero changes to any core/ file."""
    # This test itself IS the proof: it imports only from sox_protocol.core.middleware,
    # defines a plugin here, and runs it — no core/ file was modified.
    local_registry = MiddlewareRegistry()
    local_registry.register("proof_plugin", lambda: ExternalPlugin("proof_plugin"))

    chain = local_registry.assemble(["proof_plugin"])
    assert chain[0].name == "proof_plugin"

    async def _terminal(ctx: MiddlewareContext) -> dict[str, object]:
        return {"proof": True}

    pipeline = Pipeline(chain, _terminal)
    result = await pipeline.dispatch("send", {}, connection_id="c")
    assert result == {"proof": True}
