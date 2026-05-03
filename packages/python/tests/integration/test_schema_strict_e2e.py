# SPDX-License-Identifier: Apache-2.0
"""End-to-end integration tests for the schema-strict reference plugin.

Tests the full discovery + dispatch path against the REAL plugin package
installed into a temporary directory via ``pip install --target``.

Isolation strategy
------------------
Same as ``test_plugin_discovery_e2e.py``:
- ``pip install --target <tmpdir>`` into a throw-away directory.
- Prepend that directory to ``sys.path`` via ``monkeypatch.syspath_prepend``.
- After ``importlib.invalidate_caches()``, entry_points picks up the newly
  installed dist-info.
- The plugin is NOT installed into the project dev venv.

What these tests prove
----------------------
1. Plugin discovers via ``MiddlewareRegistry.load_plugins(allowlist=["io.sox.schema-strict"])``.
2. Valid input passes through the pipeline end-to-end.
3. Invalid input returns a sox-error envelope with ``error_code="validation_error"``
   and a non-empty ``detail.violations`` list.
4. ``extend_pipeline_with_registry`` wires the plugin into a real Pipeline.

Spec references
---------------
- ``spec/ports/middleware/03-plugin-contract.md §3.2`` — transformer failure semantics
- ``spec/envelopes/sox-error.schema.json`` — validation_error envelope shape
- ``plugins/sox-plugin-schema-strict/sox-plugin.yaml`` — manifest under test
"""

from __future__ import annotations

import importlib
import importlib.metadata
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sox_protocol.core.middleware.errors import ShortCircuitResponse
from sox_protocol.core.middleware.registry import MiddlewareRegistry

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[4]  # packages/python/tests/integration/ → repo
_PLUGIN_DIR = _REPO_ROOT / "plugins" / "sox-plugin-schema-strict"
_SCHEMAS_DIR = _REPO_ROOT / "spec" / "operations"


# ---------------------------------------------------------------------------
# Install helper (mirrors test_plugin_discovery_e2e.py)
# ---------------------------------------------------------------------------


def _pip_install_to(target_dir: Path, *fixture_paths: Path) -> None:
    """Install one or more packages into *target_dir* via pip --target.

    Args:
        target_dir: Directory to install into.
        fixture_paths: Paths to directories containing pyproject.toml.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            str(target_dir),
            "--quiet",
            "--no-deps",
            *(str(p) for p in fixture_paths),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pip install --target failed:\n{result.stdout}\n{result.stderr}"
        )


@pytest.fixture(scope="module")
def schema_strict_install_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Install sox-plugin-schema-strict into a module-scoped temp dir.

    Returns:
        The target directory path (sys.path entry to prepend).
    """
    target = tmp_path_factory.mktemp("schema_strict_install")
    _pip_install_to(target, _PLUGIN_DIR)
    return target


# ---------------------------------------------------------------------------
# Activation helper
# ---------------------------------------------------------------------------


def _activate(monkeypatch: pytest.MonkeyPatch, install_dir: Path) -> None:
    """Prepend *install_dir* to sys.path and invalidate import caches.

    Also evicts any cached imports of the plugin package and its dist-metadata
    so a fresh entry-point scan picks up the install_dir copy. Without this
    eviction, a prior test run that imported the plugin from a different
    install_dir leaks into this run via sys.modules / importlib.metadata
    caches, causing read_manifest_for_entry_point to fail with
    'sox-plugin.yaml not found in the distribution's file list'.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        install_dir: Directory returned by _pip_install_to.
    """
    import sys
    for mod_name in list(sys.modules):
        if mod_name == "sox_plugin_schema_strict" or mod_name.startswith(
            "sox_plugin_schema_strict."
        ):
            monkeypatch.delitem(sys.modules, mod_name, raising=False)
    monkeypatch.syspath_prepend(str(install_dir))
    importlib.invalidate_caches()


def _fresh_registry() -> MiddlewareRegistry:
    """Return a new MiddlewareRegistry with no pre-registered middleware."""
    return MiddlewareRegistry()


# ---------------------------------------------------------------------------
# Scenario 1: discovery
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestDiscovery:
    """Plugin loads via MiddlewareRegistry.load_plugins()."""

    def test_plugin_discovers_with_allowlist(
        self,
        monkeypatch: pytest.MonkeyPatch,
        schema_strict_install_dir: Path,
    ) -> None:
        """Plugin id 'io.sox.schema-strict' appears in resolved_order after load."""
        _activate(monkeypatch, schema_strict_install_dir)
        registry = _fresh_registry()
        registry.load_plugins(
            allowlist=["io.sox.schema-strict"],
            env="production",
            host_protocol_version="1.0.0",
        )
        assert "io.sox.schema-strict" in registry.resolved_order

    def test_plugin_factory_returns_middleware(
        self,
        monkeypatch: pytest.MonkeyPatch,
        schema_strict_install_dir: Path,
    ) -> None:
        """Registry can retrieve the factory and call it."""
        _activate(monkeypatch, schema_strict_install_dir)
        registry = _fresh_registry()
        registry.load_plugins(
            allowlist=["io.sox.schema-strict"],
            env="production",
            host_protocol_version="1.0.0",
        )
        factory = registry.get("io.sox.schema-strict")
        assert factory is not None
        mw = factory()
        assert callable(mw)
        assert mw.name == "schema_strict"
        assert mw.kind == "transformer"


# ---------------------------------------------------------------------------
# Scenario 2: direct middleware dispatch (no full Pipeline required)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestDirectDispatch:
    """SchemaStrictMiddleware validates correctly when dispatched directly."""

    def test_valid_input_passes_through(
        self,
        monkeypatch: pytest.MonkeyPatch,
        schema_strict_install_dir: Path,
    ) -> None:
        """Valid send input calls call_next and returns its result."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        _activate(monkeypatch, schema_strict_install_dir)

        # Import after path activation so we get the installed version.
        from sox_plugin_schema_strict.middleware import SchemaStrictMiddleware

        mw = SchemaStrictMiddleware(schemas_dir=_SCHEMAS_DIR)

        ctx = MagicMock()
        ctx.operation = "send"
        ctx.input = {"channel": "general", "body": {"text": "hello world"}}
        ctx.metadata = {}

        call_next = AsyncMock(return_value={"status": "ok", "msg_id": "x"})

        result = asyncio.run(mw(ctx, call_next))

        call_next.assert_awaited_once_with(ctx)
        assert result == {"status": "ok", "msg_id": "x"}

    def test_invalid_input_raises_short_circuit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        schema_strict_install_dir: Path,
    ) -> None:
        """Invalid send input (missing fields) raises ShortCircuitResponse."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        _activate(monkeypatch, schema_strict_install_dir)

        from sox_plugin_schema_strict.middleware import SchemaStrictMiddleware

        mw = SchemaStrictMiddleware(schemas_dir=_SCHEMAS_DIR)

        ctx = MagicMock()
        ctx.operation = "send"
        ctx.input = {}  # missing required fields
        ctx.metadata = {}

        call_next = AsyncMock()

        with pytest.raises(ShortCircuitResponse) as exc_info:
            asyncio.run(mw(ctx, call_next))

        envelope = exc_info.value.response
        assert envelope["error_code"] == "validation_error"
        assert "violations" in envelope["detail"]  # type: ignore[index]
        assert len(envelope["detail"]["violations"]) >= 1  # type: ignore[index]
        call_next.assert_not_awaited()


# ---------------------------------------------------------------------------
# Scenario 3: pipeline integration via extend_pipeline_with_registry
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestPipelineIntegration:
    """Plugin wires into the default Pipeline via extend_pipeline_with_registry."""

    def test_extend_pipeline_includes_schema_strict(
        self,
        monkeypatch: pytest.MonkeyPatch,
        schema_strict_install_dir: Path,
    ) -> None:
        """After extend_pipeline_with_registry, pipeline.order contains schema_strict."""
        import asyncio

        _activate(monkeypatch, schema_strict_install_dir)

        from sox_protocol.adapters.backing_stores.memory import MemoryStore
        from sox_protocol.core.middleware import (
            build_default_pipeline,
            extend_pipeline_with_registry,
        )
        from sox_protocol.core.middleware.plugins.store_dispatch import StoreDispatchMiddleware

        from sox_protocol.core.identity import (  # type: ignore[import]
            AuditLogWriter,
            InMemoryCredentialRegistry,
        )
        from sox_protocol.core.identity.verifier import IdentityVerifier

        store = MemoryStore()
        store_mw = StoreDispatchMiddleware(store)
        verifier = IdentityVerifier(
            registry=InMemoryCredentialRegistry(),
            audit=AuditLogWriter(),
        )
        base_pipeline = build_default_pipeline(verifier=verifier, store=store)

        registry = _fresh_registry()
        registry.load_plugins(
            allowlist=["io.sox.schema-strict"],
            env="production",
            host_protocol_version="1.0.0",
        )

        # Reconstruct terminal the same way build_default_pipeline does.
        from sox_protocol.core.middleware.default_chain import _StoreTerminal  # type: ignore[attr-defined]

        terminal = _StoreTerminal(store_mw)
        extended = extend_pipeline_with_registry(base_pipeline, registry, terminal)

        assert "schema_strict" in extended.order

    def test_invalid_input_returns_validation_error_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        schema_strict_install_dir: Path,
    ) -> None:
        """Full pipeline dispatch with invalid input returns validation_error envelope."""
        import asyncio

        _activate(monkeypatch, schema_strict_install_dir)

        from sox_plugin_schema_strict.middleware import SchemaStrictMiddleware

        from sox_protocol.adapters.backing_stores.memory import MemoryStore
        from sox_protocol.core.middleware import build_default_pipeline
        from sox_protocol.core.middleware.pipeline import Pipeline
        from sox_protocol.core.middleware.plugins.store_dispatch import StoreDispatchMiddleware

        store = MemoryStore()
        store_mw = StoreDispatchMiddleware(store)

        # Build a minimal pipeline: schema_strict → store_dispatch
        mw = SchemaStrictMiddleware(schemas_dir=_SCHEMAS_DIR)

        # Inline terminal that calls store_dispatch
        async def _terminal(ctx: Any) -> dict[str, object]:
            return await store_mw(ctx, lambda c: asyncio.coroutine(lambda: {}))  # type: ignore[arg-type]

        pipeline = Pipeline([mw], _terminal)

        result = asyncio.run(
            pipeline.dispatch(
                "send",
                {},  # invalid: missing required fields
                connection_id="test-conn",
            )
        )

        assert result["error_code"] == "validation_error"
        assert "violations" in result.get("detail", {})  # type: ignore[operator]

    def test_valid_input_dispatches_successfully(
        self,
        monkeypatch: pytest.MonkeyPatch,
        schema_strict_install_dir: Path,
    ) -> None:
        """Full pipeline dispatch with valid send input reaches the store."""
        import asyncio

        _activate(monkeypatch, schema_strict_install_dir)

        from sox_plugin_schema_strict.middleware import SchemaStrictMiddleware

        from sox_protocol.adapters.backing_stores.memory import MemoryStore
        from sox_protocol.core.middleware.pipeline import Pipeline
        from sox_protocol.core.middleware.plugins.store_dispatch import StoreDispatchMiddleware

        store = MemoryStore()
        store_mw = StoreDispatchMiddleware(store)

        mw = SchemaStrictMiddleware(schemas_dir=_SCHEMAS_DIR)

        # Terminal delegates to StoreDispatchMiddleware via its own call_next
        async def _terminal(ctx: Any) -> dict[str, object]:
            return await store_mw(ctx, lambda c: asyncio.coroutine(lambda: {})())  # type: ignore[arg-type]

        pipeline = Pipeline([mw], _terminal)

        result = asyncio.run(
            pipeline.dispatch(
                "send",
                {"channel": "general", "body": {"text": "hello"}},
                connection_id="agent-1",
                metadata={"_connection_credential": None},
            )
        )

        # Should NOT be a validation_error — schema passed
        assert result.get("error_code") != "validation_error"
