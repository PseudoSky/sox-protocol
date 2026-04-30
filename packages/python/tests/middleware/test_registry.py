# SPDX-License-Identifier: Apache-2.0
"""Tests for MiddlewareRegistry: constraint validation, assembly, entry-point loading.

Spec reference: ``spec/ports/middleware.md §4``; ``docs/adr/0003 §Decision (4)``
"""

from __future__ import annotations

import warnings
from collections.abc import Awaitable, Callable
from unittest.mock import MagicMock, patch

import pytest

from sox_protocol.core.middleware.context import MiddlewareContext
from sox_protocol.core.middleware.errors import ChainConfigurationError
from sox_protocol.core.middleware.registry import MiddlewareRegistry

# ---------------------------------------------------------------------------
# Stub middlewares
# ---------------------------------------------------------------------------


class _MW:
    """Minimal middleware stub."""

    def __init__(
        self,
        name: str,
        *,
        before: tuple[str, ...] = (),
        after: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.must_run_before = before
        self.must_run_after = after

    async def __call__(
        self,
        ctx: MiddlewareContext,
        call_next: Callable[[MiddlewareContext], Awaitable[dict[str, object]]],
    ) -> dict[str, object]:
        return await call_next(ctx)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_and_get() -> None:
    reg = MiddlewareRegistry()

    def factory() -> _MW:
        return _MW("mw_a")

    reg.register("mw_a", factory)
    assert reg.get("mw_a") is factory


def test_register_duplicate_raises() -> None:
    reg = MiddlewareRegistry()
    reg.register("mw_a", lambda: _MW("mw_a"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register("mw_a", lambda: _MW("mw_a"))


def test_get_unknown_raises() -> None:
    reg = MiddlewareRegistry()
    with pytest.raises(KeyError):
        reg.get("unknown")


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def test_assemble_returns_instances_in_order() -> None:
    reg = MiddlewareRegistry()
    reg.register("a", lambda: _MW("a"))
    reg.register("b", lambda: _MW("b"))
    reg.register("c", lambda: _MW("c"))

    chain = reg.assemble(["a", "b", "c"])
    assert [m.name for m in chain] == ["a", "b", "c"]


def test_assemble_skips_missing_with_warning() -> None:
    reg = MiddlewareRegistry()
    reg.register("a", lambda: _MW("a"))

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        chain = reg.assemble(["a", "missing_link"])

    assert [m.name for m in chain] == ["a"]
    assert any("missing_link" in str(warning.message) for warning in w)


def test_assemble_rejects_auth_before_namespace_resolver() -> None:
    """must_run_after constraint: auth must follow namespace_resolver."""
    reg = MiddlewareRegistry()
    reg.register(
        "namespace_resolver",
        lambda: _MW("namespace_resolver"),
    )
    reg.register(
        "auth",
        lambda: _MW("auth", after=("namespace_resolver",)),
    )

    # The registry re-sorts via topological sort — should produce correct order.
    chain = reg.assemble(["auth", "namespace_resolver"])
    assert [m.name for m in chain] == ["namespace_resolver", "auth"]


def test_assemble_raises_on_cycle() -> None:
    reg = MiddlewareRegistry()
    reg.register("a", lambda: _MW("a", after=("b",)))
    reg.register("b", lambda: _MW("b", after=("a",)))

    with pytest.raises(ChainConfigurationError, match="cycle"):
        reg.assemble(["a", "b"])


def test_assemble_empty_order() -> None:
    reg = MiddlewareRegistry()
    assert reg.assemble([]) == []


# ---------------------------------------------------------------------------
# Entry-point loading
# ---------------------------------------------------------------------------


def test_load_entry_points_registers_factories() -> None:
    """Stub entry-point group: registry resolves it."""
    reg = MiddlewareRegistry()

    mock_ep = MagicMock()
    mock_ep.name = "stub_ep"
    mock_ep.value = "tests.stub:factory"
    mock_ep.load.return_value = lambda: _MW("stub_ep")

    with patch("importlib.metadata.entry_points") as mock_eps:
        mock_eps.return_value = [mock_ep]
        reg.load_entry_points(group="sox_protocol.middleware")

    chain = reg.assemble(["stub_ep"])
    assert len(chain) == 1
    assert chain[0].name == "stub_ep"


def test_load_entry_points_logs_warning_on_failure() -> None:
    """Failed entry-point load is warned and skipped, not raised."""
    reg = MiddlewareRegistry()

    mock_ep = MagicMock()
    mock_ep.name = "bad_ep"
    mock_ep.value = "nonexistent:factory"
    mock_ep.load.side_effect = ImportError("not found")

    with patch("importlib.metadata.entry_points") as mock_eps:
        mock_eps.return_value = [mock_ep]
        # Should not raise.
        reg.load_entry_points(group="sox_protocol.middleware")

    # bad_ep was not registered.
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        chain = reg.assemble(["bad_ep"])

    assert chain == []


# ---------------------------------------------------------------------------
# OUT-OF-CORE registration smoke
# ---------------------------------------------------------------------------


def test_out_of_core_registration_via_module_api() -> None:
    """A plugin defined outside core/ can be registered via a local registry."""
    local_reg = MiddlewareRegistry()

    class ExternalPlugin(_MW):
        pass

    local_reg.register("external_test_plugin", lambda: ExternalPlugin("external_test_plugin"))
    chain = local_reg.assemble(["external_test_plugin"])
    assert len(chain) == 1
    assert chain[0].name == "external_test_plugin"
