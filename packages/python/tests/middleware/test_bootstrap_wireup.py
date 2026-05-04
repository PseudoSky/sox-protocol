# SPDX-License-Identifier: Apache-2.0
"""Bootstrap wire-up tests for phase 04-bootstrap-integration.

Verifies that:
- Both server bootstraps (stdio lifespan and HTTP create_app) invoke
  ``load_plugins`` after ``build_default_pipeline``.
- ``PluginStartupError`` from ``load_plugins`` aborts startup correctly
  (SystemExit(1) from mcp_server; re-raise from create_app).
- ``SOX_NO_DISCOVERY=1`` causes both bootstraps to start cleanly with no
  plugins loaded.
- ``SOX_ALLOWED_PLUGINS=`` (empty) + ``SOX_ENV=production`` causes
  ``PluginNotAllowed`` to surface as a structured error envelope.
- A fake registered plugin (mocked entry point) gets loaded into the
  pipeline after dispatch (happy-path smoke).

Spec references:
    spec/ports/middleware/03-plugin-contract.md §6.1
    implementation-plan.json §04-bootstrap-integration
    .workflow/plans/plugin-discovery-py/STATE.md §04
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from sox_protocol.adapters.backing_stores.memory.store import MemoryStore
from sox_protocol.core.middleware.errors import PluginNotAllowed
from sox_protocol.core.middleware.registry import MiddlewareRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest_doc(
    *,
    plugin_id: str = "io.sox.test-plugin",
    version: str = "1.0.0",
    plugin_kind: str = "interceptor",
    protocol_version: str = ">=1.0,<2.0",
) -> dict[str, Any]:
    """Build a minimal valid sox-plugin manifest dict."""
    return {
        "apiVersion": "sox.dev/v1",
        "kind": "SoxPlugin",
        "metadata": {"id": plugin_id, "version": version},
        "spec": {
            "protocol_version": protocol_version,
            "plugin_kind": plugin_kind,
            "signatures": [],
        },
    }


class _FakeMiddleware:
    """Minimal Middleware stub."""

    name: str = "io.sox.test-plugin"
    must_run_before: tuple[str, ...] = ()
    must_run_after: tuple[str, ...] = ()

    async def __call__(self, ctx: Any, call_next: Any) -> Any:  # pragma: no cover
        return await call_next(ctx)


def _make_fake_ep(plugin_id: str) -> MagicMock:
    """Return a mock EntryPoint."""
    ep = MagicMock()
    ep.name = plugin_id
    ep.load.return_value = _FakeMiddleware
    return ep


def _patch_discovery(
    monkeypatch: pytest.MonkeyPatch,
    eps: list[MagicMock],
    manifest_docs: dict[str, dict[str, Any]],
    registry_attr_path: str,
) -> MiddlewareRegistry:
    """Patch entry-point scan + manifest read + replace the module-level registry.

    Returns the fresh MiddlewareRegistry injected into the bootstrap.
    """
    fresh_registry = MiddlewareRegistry()

    def _fake_entry_points(*, group: str) -> list[MagicMock]:
        if group == "sox_protocol.plugins":
            return eps
        return []

    def _fake_read_manifest(ep: MagicMock) -> dict[str, Any]:
        return manifest_docs[ep.name]

    monkeypatch.setattr("importlib.metadata.entry_points", _fake_entry_points)
    monkeypatch.setattr(
        "sox_protocol.core.middleware.plugin_loader.read_manifest_for_entry_point",
        _fake_read_manifest,
    )
    monkeypatch.setattr(registry_attr_path, fresh_registry)
    return fresh_registry


# ---------------------------------------------------------------------------
# A. HTTP create_app — no_discovery short-circuit
# ---------------------------------------------------------------------------


class TestHttpCreateAppNoDiscovery:
    """HTTP create_app with SOX_NO_DISCOVERY=1 starts cleanly."""

    def test_no_discovery_starts_cleanly(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """create_app with no_discovery=True loads no plugins and returns app."""
        from sox_protocol.adapters.transports.http.server import create_app

        fresh_registry = MiddlewareRegistry()
        monkeypatch.setattr(
            "sox_protocol.adapters.transports.http.server.register_middleware",
            fresh_registry,
        )

        store = MemoryStore()
        app = create_app(store, no_discovery=True, env="production")
        assert app is not None
        assert fresh_registry.resolved_order == ()

    def test_no_discovery_env_var_starts_cleanly(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SOX_NO_DISCOVERY=1 env var is respected by create_app."""
        from sox_protocol.adapters.transports.http.server import create_app

        fresh_registry = MiddlewareRegistry()
        monkeypatch.setattr(
            "sox_protocol.adapters.transports.http.server.register_middleware",
            fresh_registry,
        )
        monkeypatch.setenv("SOX_NO_DISCOVERY", "1")
        monkeypatch.setenv("SOX_ENV", "production")

        store = MemoryStore()
        app = create_app(store)
        assert app is not None
        assert fresh_registry.resolved_order == ()


# ---------------------------------------------------------------------------
# B. HTTP create_app — production + empty allowlist → PluginNotAllowed
# ---------------------------------------------------------------------------


class TestHttpCreateAppProductionEmptyAllowlist:
    """HTTP create_app in production with no allowlist raises PluginNotAllowed."""

    def test_production_empty_allowlist_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """env='production' + allowlist=None → PluginStartupError re-raised."""
        from sox_protocol.adapters.transports.http.server import create_app

        # Inject a fake plugin so discovery doesn't short-circuit on "0 plugins found"
        ep = _make_fake_ep("io.sox.test-plugin")
        manifest = _make_manifest_doc()
        _patch_discovery(
            monkeypatch,
            [ep],
            {"io.sox.test-plugin": manifest},
            "sox_protocol.adapters.transports.http.server.register_middleware",
        )

        store = MemoryStore()
        with pytest.raises(PluginNotAllowed) as exc_info:
            create_app(store, env="production", allowlist=None)

        envelope = exc_info.value.to_envelope()
        assert envelope["error_code"] == "plugin_not_allowed"

    def test_production_empty_allowlist_envelope_shape(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The PluginNotAllowed envelope has required fields."""
        from sox_protocol.adapters.transports.http.server import create_app

        ep = _make_fake_ep("io.sox.test-plugin")
        manifest = _make_manifest_doc()
        _patch_discovery(
            monkeypatch,
            [ep],
            {"io.sox.test-plugin": manifest},
            "sox_protocol.adapters.transports.http.server.register_middleware",
        )

        store = MemoryStore()
        with pytest.raises(PluginNotAllowed) as exc_info:
            create_app(store, env="production", allowlist=None)

        envelope = exc_info.value.to_envelope()
        assert "error_code" in envelope
        assert "plugin_id" in envelope
        assert "message" in envelope

    def test_production_empty_allowlist_via_env_var(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SOX_ENV=production + SOX_ALLOWED_PLUGINS='' raises PluginNotAllowed."""
        from sox_protocol.adapters.transports.http.server import create_app

        ep = _make_fake_ep("io.sox.test-plugin")
        manifest = _make_manifest_doc()
        _patch_discovery(
            monkeypatch,
            [ep],
            {"io.sox.test-plugin": manifest},
            "sox_protocol.adapters.transports.http.server.register_middleware",
        )

        monkeypatch.setenv("SOX_ENV", "production")
        monkeypatch.delenv("SOX_ALLOWED_PLUGINS", raising=False)

        store = MemoryStore()
        with pytest.raises(PluginNotAllowed):
            create_app(store)  # env defaults to "dev" param, but SOX_ENV=production


# ---------------------------------------------------------------------------
# C. HTTP create_app — happy-path fake plugin loaded
# ---------------------------------------------------------------------------


class TestHttpCreateAppHappyPath:
    """HTTP create_app with a valid plugin: loads and pipeline extended."""

    def test_fake_plugin_loaded_and_registered(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A fake registered plugin appears in resolved_order after create_app."""
        from sox_protocol.adapters.transports.http.server import create_app

        ep = _make_fake_ep("io.sox.test-plugin")
        manifest = _make_manifest_doc()
        fresh_registry = _patch_discovery(
            monkeypatch,
            [ep],
            {"io.sox.test-plugin": manifest},
            "sox_protocol.adapters.transports.http.server.register_middleware",
        )

        store = MemoryStore()
        app = create_app(store, env="dev", allowlist=None)
        assert app is not None
        assert "io.sox.test-plugin" in fresh_registry.resolved_order


# ---------------------------------------------------------------------------
# D. MCP server lifespan — no_discovery short-circuit
# ---------------------------------------------------------------------------


class TestMcpServerNoDiscovery:
    """MCP stdio lifespan with SOX_NO_DISCOVERY=1 starts cleanly."""

    def test_no_discovery_lifespan_starts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SOX_NO_DISCOVERY=1 → lifespan yields without loading plugins."""
        import asyncio

        monkeypatch.setenv("SOX_NO_DISCOVERY", "1")
        monkeypatch.setenv("SOX_ENV", "production")
        monkeypatch.setenv("SOX_AGENT_ID", "test-agent")

        fresh_registry = MiddlewareRegistry()
        monkeypatch.setattr(
            "sox_protocol.core.mcp_server.server.register_middleware",
            fresh_registry,
        )

        from sox_protocol.core.mcp_server.server import create_server

        mcp = create_server()

        # FastMCP 2.x: the user-supplied lifespan runs via mcp._lifespan(mcp),
        # not via mcp.lifespan() (which only runs provider lifespans).
        async def _run() -> None:
            async with mcp._lifespan(mcp):  # type: ignore[attr-defined]
                pass

        asyncio.run(_run())
        assert fresh_registry.resolved_order == ()

    def test_no_discovery_load_plugins_called_with_no_discovery_true(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """load_plugins is called with no_discovery=True when SOX_NO_DISCOVERY=1."""
        import asyncio

        monkeypatch.setenv("SOX_NO_DISCOVERY", "1")
        monkeypatch.setenv("SOX_AGENT_ID", "test-agent")

        call_kwargs: list[dict[str, Any]] = []

        fresh_registry = MiddlewareRegistry()
        original_load = fresh_registry.load_plugins

        def _spy_load(**kwargs: Any) -> None:
            call_kwargs.append(dict(kwargs))
            original_load(**kwargs)

        fresh_registry.load_plugins = _spy_load  # type: ignore[method-assign]
        monkeypatch.setattr(
            "sox_protocol.core.mcp_server.server.register_middleware",
            fresh_registry,
        )

        from sox_protocol.core.mcp_server.server import create_server

        mcp = create_server()

        async def _run() -> None:
            async with mcp._lifespan(mcp):  # type: ignore[attr-defined]
                pass

        asyncio.run(_run())
        assert len(call_kwargs) == 1
        assert call_kwargs[0]["no_discovery"] is True


# ---------------------------------------------------------------------------
# E. MCP server lifespan — production + empty allowlist → SystemExit(1)
# ---------------------------------------------------------------------------


class TestMcpServerProductionEmptyAllowlist:
    """MCP stdio lifespan in production with empty allowlist exits with code 1."""

    def test_production_empty_allowlist_exits(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """env=production + no allowlist → SystemExit(1) from lifespan."""
        import asyncio

        monkeypatch.setenv("SOX_ENV", "production")
        monkeypatch.delenv("SOX_ALLOWED_PLUGINS", raising=False)
        monkeypatch.delenv("SOX_NO_DISCOVERY", raising=False)
        monkeypatch.setenv("SOX_AGENT_ID", "test-agent")

        # Inject fake plugin so production-mode sees discoverable plugins.
        ep = _make_fake_ep("io.sox.test-plugin")
        manifest = _make_manifest_doc()

        fresh_registry = MiddlewareRegistry()
        monkeypatch.setattr(
            "sox_protocol.core.mcp_server.server.register_middleware",
            fresh_registry,
        )

        def _fake_entry_points(*, group: str) -> list[MagicMock]:
            return [ep] if group == "sox_protocol.plugins" else []

        def _fake_read_manifest(ep_arg: MagicMock) -> dict[str, Any]:
            return manifest

        monkeypatch.setattr("importlib.metadata.entry_points", _fake_entry_points)
        monkeypatch.setattr(
            "sox_protocol.core.middleware.plugin_loader.read_manifest_for_entry_point",
            _fake_read_manifest,
        )

        from sox_protocol.core.mcp_server.server import create_server

        mcp = create_server()

        # FastMCP 2.x: call mcp._lifespan(mcp) to run the user-supplied lifespan.
        async def _run() -> None:
            async with mcp._lifespan(mcp):  # type: ignore[attr-defined]
                pass  # pragma: no cover

        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(_run())

        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# F. load_plugins called AFTER build_default_pipeline (call-order spy)
# ---------------------------------------------------------------------------


class TestLoadPluginsCalledAfterBuildPipeline:
    """Verify load_plugins is called after build_default_pipeline in both bootstraps."""

    def test_http_create_app_call_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """load_plugins is called only after pipeline is built in create_app."""
        from sox_protocol.adapters.transports.http.server import create_app

        call_log: list[str] = []

        original_build = __import__(
            "sox_protocol.core.middleware.default_chain",
            fromlist=["build_default_pipeline"],
        ).build_default_pipeline

        def _spy_build(**kwargs: Any) -> Any:
            call_log.append("build_default_pipeline")
            return original_build(**kwargs)

        fresh_registry = MiddlewareRegistry()

        original_load = fresh_registry.load_plugins

        def _spy_load(**kwargs: Any) -> None:
            call_log.append("load_plugins")
            original_load(**kwargs)

        fresh_registry.load_plugins = _spy_load  # type: ignore[method-assign]

        monkeypatch.setattr(
            "sox_protocol.adapters.transports.http.server.register_middleware",
            fresh_registry,
        )
        monkeypatch.setattr(
            "sox_protocol.adapters.transports.http.server.build_default_pipeline",
            _spy_build,
        )

        store = MemoryStore()
        create_app(store, no_discovery=True)

        # build_default_pipeline must appear before load_plugins in the log.
        assert "build_default_pipeline" in call_log
        assert "load_plugins" in call_log
        build_idx = call_log.index("build_default_pipeline")
        load_idx = call_log.index("load_plugins")
        assert build_idx < load_idx, (
            f"Expected build_default_pipeline before load_plugins; got: {call_log}"
        )
