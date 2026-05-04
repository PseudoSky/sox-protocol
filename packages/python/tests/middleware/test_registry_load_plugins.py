# SPDX-License-Identifier: Apache-2.0
"""Tests for MiddlewareRegistry.load_plugins() allowlist semantics and CLI flags.

Covers phase 03-allowlist requirements:
  - no_discovery=True short-circuits before entry-point scan
  - env="production" + empty allowlist → PluginNotAllowed (fail-fast)
  - env="production" + allowlist mismatch → all silently skipped
  - env="production" + matching allowlist → only matched plugin loaded
  - env="dev" + empty allowlist → all plugins loaded, no warning
  - env="dev" + partial allowlist → matched loaded, unmatched skipped with
    stderr WARNING
  - CLI --allow-plugins parses to list; overrides SOX_ALLOWED_PLUGINS
  - CLI --no-discovery propagates SOX_NO_DISCOVERY=1

Spec reference:
  spec/ports/middleware/03-plugin-contract.md §6.1 (allowlist precedence)
  spec/ports/middleware/03-plugin-contract.md §6.2 (plugin_not_allowed error)
  .workflow/plans/plugin-architecture/analysis.md §7.5 risk #1 (supply-chain)
  implementation-plan.json §03-allowlist
"""

from __future__ import annotations

import argparse
import os
from typing import Any
from unittest.mock import MagicMock

import pytest

from sox_protocol.core.middleware.errors import (
    PluginNotAllowed,
    PluginNotFound,
)
from sox_protocol.core.middleware.registry import MiddlewareRegistry

# ---------------------------------------------------------------------------
# Helpers: build fake entry-points and manifests without site-packages writes
# ---------------------------------------------------------------------------


def _make_manifest_doc(
    *,
    plugin_id: str = "io.sox.test-plugin",
    version: str = "1.0.0",
    plugin_kind: str = "interceptor",
    protocol_version: str = ">=1.0,<2.0",
    plugin_capabilities: list[dict[str, Any]] | None = None,
    requires: list[str] | None = None,
    must_run_before: list[str] | None = None,
    must_run_after: list[str] | None = None,
) -> dict[str, Any]:
    """Build a minimal valid sox-plugin manifest dict."""
    spec: dict[str, Any] = {
        "protocol_version": protocol_version,
        "plugin_kind": plugin_kind,
        "signatures": [],
    }
    if plugin_capabilities is not None:
        spec["plugin_capabilities"] = plugin_capabilities
    if requires is not None:
        spec["requires"] = requires
    if must_run_before is not None:
        spec["must_run_before"] = must_run_before
    if must_run_after is not None:
        spec["must_run_after"] = must_run_after
    return {
        "apiVersion": "sox.dev/v1",
        "kind": "SoxPlugin",
        "metadata": {"id": plugin_id, "version": version},
        "spec": spec,
    }


class _FakeMiddleware:
    """Minimal Middleware stub for tests."""

    must_run_before: tuple[str, ...] = ()
    must_run_after: tuple[str, ...] = ()

    async def __call__(self, ctx: Any, call_next: Any) -> Any:  # pragma: no cover
        return await call_next(ctx)


def _make_fake_ep(plugin_id: str) -> MagicMock:
    """Return a mock EntryPoint whose .name and .load() factory work correctly."""
    ep = MagicMock()
    ep.name = plugin_id
    ep.load.return_value = _FakeMiddleware
    return ep


def _patch_eps(
    monkeypatch: pytest.MonkeyPatch,
    eps: list[MagicMock],
    manifest_docs: dict[str, dict[str, Any]],
) -> None:
    """Patch importlib.metadata.entry_points and read_manifest_for_entry_point.

    Both are imported *inside* load_plugins() at call time, so we patch at
    their canonical source locations (importlib.metadata and plugin_loader).

    Args:
        monkeypatch: pytest monkeypatch fixture.
        eps: List of fake EntryPoint mocks to return from entry_points().
        manifest_docs: Mapping of plugin_id → raw manifest dict returned by
            read_manifest_for_entry_point.
    """

    def _fake_entry_points(*, group: str) -> list[MagicMock]:
        if group == "sox_protocol.plugins":
            return eps
        return []

    def _fake_read_manifest(ep: MagicMock) -> dict[str, Any]:
        return manifest_docs[ep.name]

    # entry_points is imported inside load_plugins via:
    #   from importlib.metadata import entry_points
    # Patch at the importlib.metadata level so the local import picks it up.
    monkeypatch.setattr("importlib.metadata.entry_points", _fake_entry_points)
    # read_manifest_for_entry_point is imported inside load_plugins from plugin_loader.
    monkeypatch.setattr(
        "sox_protocol.core.middleware.plugin_loader.read_manifest_for_entry_point",
        _fake_read_manifest,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> MiddlewareRegistry:
    """Fresh MiddlewareRegistry per test."""
    return MiddlewareRegistry()


# ---------------------------------------------------------------------------
# A. no_discovery=True short-circuit
# ---------------------------------------------------------------------------


class TestNoDiscovery:
    def test_no_discovery_returns_immediately_empty_order(
        self, registry: MiddlewareRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """no_discovery=True → resolved_order is () with no entry-point scan."""
        scan_called = False

        def _should_not_be_called(*, group: str) -> list[MagicMock]:
            nonlocal scan_called
            scan_called = True
            return []

        # entry_points is imported inside load_plugins at call time; patch the
        # source so the local `from importlib.metadata import entry_points` picks
        # up the stub.
        monkeypatch.setattr("importlib.metadata.entry_points", _should_not_be_called)

        registry.load_plugins(no_discovery=True)

        assert not scan_called, "entry_points() must NOT be called when no_discovery=True"
        assert registry.resolved_order == ()

    def test_no_discovery_with_production_env_and_empty_allowlist_does_not_raise(
        self, registry: MiddlewareRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """no_discovery wins over production+empty-allowlist (R4 precedence rule)."""
        monkeypatch.setattr("importlib.metadata.entry_points", lambda *, group: [])
        # Must NOT raise PluginNotAllowed — no_discovery short-circuits first.
        registry.load_plugins(no_discovery=True, env="production", allowlist=None)
        assert registry.resolved_order == ()

    def test_no_discovery_with_allowlist_still_does_not_scan(
        self, registry: MiddlewareRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """no_discovery=True + allowlist=['io.sox.x'] → no scan, no PluginNotFound."""
        monkeypatch.setattr("importlib.metadata.entry_points", lambda *, group: [])
        # Must NOT raise PluginNotFound even though 'io.sox.x' is in allowlist.
        registry.load_plugins(
            no_discovery=True, allowlist=["io.sox.x"], env="production"
        )
        assert registry.resolved_order == ()

    def test_no_discovery_before_registry_call_resolved_order_is_empty_tuple(
        self, registry: MiddlewareRegistry
    ) -> None:
        """resolved_order returns () before any load_plugins call."""
        assert registry.resolved_order == ()


# ---------------------------------------------------------------------------
# B. production + empty allowlist → fail-fast PluginNotAllowed
# ---------------------------------------------------------------------------


class TestProductionEmptyAllowlist:
    def test_production_none_allowlist_raises(
        self, registry: MiddlewareRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env='production' + allowlist=None → PluginNotAllowed (supply-chain gate)."""
        monkeypatch.setattr("importlib.metadata.entry_points", lambda *, group: [])
        with pytest.raises(PluginNotAllowed) as exc_info:
            registry.load_plugins(env="production", allowlist=None)
        assert exc_info.value.error_code == "plugin_not_allowed"

    def test_production_empty_list_allowlist_raises(
        self, registry: MiddlewareRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env='production' + allowlist=[] → PluginNotAllowed."""
        monkeypatch.setattr("importlib.metadata.entry_points", lambda *, group: [])
        with pytest.raises(PluginNotAllowed) as exc_info:
            registry.load_plugins(env="production", allowlist=[])
        assert exc_info.value.error_code == "plugin_not_allowed"

    def test_production_empty_allowlist_envelope_has_error_code(
        self, registry: MiddlewareRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PluginNotAllowed.to_envelope() includes error_code key."""
        monkeypatch.setattr("importlib.metadata.entry_points", lambda *, group: [])
        with pytest.raises(PluginNotAllowed) as exc_info:
            registry.load_plugins(env="production", allowlist=None)
        env = exc_info.value.to_envelope()
        assert "error_code" in env
        assert env["error_code"] == "plugin_not_allowed"


# ---------------------------------------------------------------------------
# C. production + allowlist with mismatched IDs → all silently rejected
# ---------------------------------------------------------------------------


class TestProductionMismatchedAllowlist:
    def test_production_allowlist_mismatch_all_silently_skipped(
        self, registry: MiddlewareRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production: discovered 'io.sox.plugin-b', allowlist=['io.sox.plugin-a'] → b skipped."""
        ep_b = _make_fake_ep("io.sox.plugin-b")
        docs = {"io.sox.plugin-b": _make_manifest_doc(plugin_id="io.sox.plugin-b")}
        _patch_eps(monkeypatch, [ep_b], docs)

        # 'io.sox.plugin-a' is in allowlist but not discovered → PluginNotFound.
        # 'io.sox.plugin-b' is discovered but not in allowlist → silently skipped.
        with pytest.raises(PluginNotFound) as exc_info:
            registry.load_plugins(
                env="production", allowlist=["io.sox.plugin-a"]
            )
        assert exc_info.value.plugin_id == "io.sox.plugin-a"

    def test_production_allowlist_discovered_but_not_listed_skipped_silently(
        self, registry: MiddlewareRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production: discovered 'io.sox.plugin-b' not in allowlist; resolved_order empty."""
        ep_b = _make_fake_ep("io.sox.plugin-b")
        ep_c = _make_fake_ep("io.sox.plugin-c")
        docs = {
            "io.sox.plugin-b": _make_manifest_doc(plugin_id="io.sox.plugin-b"),
            "io.sox.plugin-c": _make_manifest_doc(plugin_id="io.sox.plugin-c"),
        }
        _patch_eps(monkeypatch, [ep_b, ep_c], docs)

        # Only 'io.sox.plugin-b' in allowlist; 'io.sox.plugin-c' silently skipped.
        registry.load_plugins(
            env="production", allowlist=["io.sox.plugin-b"]
        )
        assert registry.resolved_order == ("io.sox.plugin-b",)


# ---------------------------------------------------------------------------
# D. production + matching allowlist → only matched plugin loaded
# ---------------------------------------------------------------------------


class TestProductionMatchingAllowlist:
    def test_production_matching_allowlist_loads_only_that_plugin(
        self, registry: MiddlewareRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production allowlist=['io.sox.plugin-a'] → only a loaded."""
        ep_a = _make_fake_ep("io.sox.plugin-a")
        ep_b = _make_fake_ep("io.sox.plugin-b")
        docs = {
            "io.sox.plugin-a": _make_manifest_doc(plugin_id="io.sox.plugin-a"),
            "io.sox.plugin-b": _make_manifest_doc(plugin_id="io.sox.plugin-b"),
        }
        _patch_eps(monkeypatch, [ep_a, ep_b], docs)

        registry.load_plugins(env="production", allowlist=["io.sox.plugin-a"])

        assert registry.resolved_order == ("io.sox.plugin-a",)
        # io.sox.plugin-a registered; io.sox.plugin-b not registered.
        assert registry.get("io.sox.plugin-a") is _FakeMiddleware
        with pytest.raises(KeyError):
            registry.get("io.sox.plugin-b")

    def test_production_typo_in_allowlist_raises_not_found(
        self, registry: MiddlewareRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production allowlist=['io.sox.typo'] with no such entry-point → PluginNotFound."""
        ep_a = _make_fake_ep("io.sox.plugin-a")
        docs = {"io.sox.plugin-a": _make_manifest_doc(plugin_id="io.sox.plugin-a")}
        _patch_eps(monkeypatch, [ep_a], docs)

        with pytest.raises(PluginNotFound) as exc_info:
            registry.load_plugins(env="production", allowlist=["io.sox.typo"])
        assert exc_info.value.plugin_id == "io.sox.typo"
        assert exc_info.value.error_code == "plugin_not_found"


# ---------------------------------------------------------------------------
# E. dev + empty allowlist → all loaded silently
# ---------------------------------------------------------------------------


class TestDevEmptyAllowlist:
    def test_dev_no_allowlist_loads_all_no_warning(
        self,
        registry: MiddlewareRegistry,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """dev + allowlist=None → all discovered plugins loaded; no stderr warning."""
        ep_a = _make_fake_ep("io.sox.plugin-a")
        ep_b = _make_fake_ep("io.sox.plugin-b")
        docs = {
            "io.sox.plugin-a": _make_manifest_doc(plugin_id="io.sox.plugin-a"),
            "io.sox.plugin-b": _make_manifest_doc(plugin_id="io.sox.plugin-b"),
        }
        _patch_eps(monkeypatch, [ep_a, ep_b], docs)

        registry.load_plugins(env="dev", allowlist=None)

        captured = capsys.readouterr()
        assert captured.err == "", "No stderr output expected when dev + no allowlist"
        assert set(registry.resolved_order) == {"io.sox.plugin-a", "io.sox.plugin-b"}

    def test_dev_default_env_loads_all(
        self,
        registry: MiddlewareRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Default env ('dev') with no allowlist loads everything."""
        ep_a = _make_fake_ep("io.sox.test-plugin")
        docs = {"io.sox.test-plugin": _make_manifest_doc()}
        _patch_eps(monkeypatch, [ep_a], docs)

        registry.load_plugins()  # all defaults: env="dev", allowlist=None

        assert registry.resolved_order == ("io.sox.test-plugin",)


# ---------------------------------------------------------------------------
# F. dev + partial allowlist → matched loaded, unmatched skipped with warning
# ---------------------------------------------------------------------------


class TestDevPartialAllowlist:
    def test_dev_allowlist_unmatched_emits_stderr_warning(
        self,
        registry: MiddlewareRegistry,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """dev + allowlist=['io.sox.plugin-a']: plugin-b discovered but not listed → stderr WARNING."""
        ep_a = _make_fake_ep("io.sox.plugin-a")
        ep_b = _make_fake_ep("io.sox.plugin-b")
        docs = {
            "io.sox.plugin-a": _make_manifest_doc(plugin_id="io.sox.plugin-a"),
            "io.sox.plugin-b": _make_manifest_doc(plugin_id="io.sox.plugin-b"),
        }
        _patch_eps(monkeypatch, [ep_a, ep_b], docs)

        registry.load_plugins(env="dev", allowlist=["io.sox.plugin-a"])

        captured = capsys.readouterr()
        assert "io.sox.plugin-b" in captured.err, (
            "Expected stderr warning mentioning 'io.sox.plugin-b'"
        )

    def test_dev_allowlist_unmatched_plugin_still_loads(
        self,
        registry: MiddlewareRegistry,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """dev mode: unallowlisted plugin still loads (all discovered plugins are loaded)."""
        ep_a = _make_fake_ep("io.sox.plugin-a")
        ep_b = _make_fake_ep("io.sox.plugin-b")
        docs = {
            "io.sox.plugin-a": _make_manifest_doc(plugin_id="io.sox.plugin-a"),
            "io.sox.plugin-b": _make_manifest_doc(plugin_id="io.sox.plugin-b"),
        }
        _patch_eps(monkeypatch, [ep_a, ep_b], docs)

        registry.load_plugins(env="dev", allowlist=["io.sox.plugin-a"])

        # Both loaded in dev mode even though only a is in allowlist.
        assert set(registry.resolved_order) == {"io.sox.plugin-a", "io.sox.plugin-b"}

    def test_dev_allowlist_matched_plugin_loads_no_warning(
        self,
        registry: MiddlewareRegistry,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """dev mode: plugin IN allowlist does not generate a warning."""
        ep_a = _make_fake_ep("io.sox.plugin-a")
        docs = {"io.sox.plugin-a": _make_manifest_doc(plugin_id="io.sox.plugin-a")}
        _patch_eps(monkeypatch, [ep_a], docs)

        registry.load_plugins(env="dev", allowlist=["io.sox.plugin-a"])

        captured = capsys.readouterr()
        assert "io.sox.plugin-a" not in captured.err, (
            "No warning expected for a plugin that IS in the allowlist"
        )


# ---------------------------------------------------------------------------
# G. CLI flag parsing: --allow-plugins and --no-discovery
# ---------------------------------------------------------------------------


class TestCLIFlagParsing:
    """Test that CLI argument parsing in serve.py works correctly."""

    def _make_parser(self) -> argparse.ArgumentParser:
        from sox_protocol.cli.serve import add_serve_subcommand

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_serve_subcommand(subparsers)
        return parser

    def test_allow_plugins_single_id(self) -> None:
        """--allow-plugins io.sox.plugin-a → allow_plugins='io.sox.plugin-a'."""
        parser = self._make_parser()
        args = parser.parse_args(["serve", "--allow-plugins", "io.sox.plugin-a"])
        assert args.allow_plugins == "io.sox.plugin-a"

    def test_allow_plugins_comma_separated(self) -> None:
        """--allow-plugins X,Y stores comma-separated string (splitting deferred to bootstrap)."""
        parser = self._make_parser()
        args = parser.parse_args(["serve", "--allow-plugins", "io.sox.x,io.sox.y"])
        assert args.allow_plugins == "io.sox.x,io.sox.y"

    def test_allow_plugins_absent_is_none(self) -> None:
        """--allow-plugins absent → allow_plugins is None."""
        parser = self._make_parser()
        args = parser.parse_args(["serve"])
        assert args.allow_plugins is None

    def test_no_discovery_flag_sets_true(self) -> None:
        """--no-discovery sets no_discovery=True."""
        parser = self._make_parser()
        args = parser.parse_args(["serve", "--no-discovery"])
        assert args.no_discovery is True

    def test_no_discovery_absent_is_false(self) -> None:
        """--no-discovery absent → no_discovery=False."""
        parser = self._make_parser()
        args = parser.parse_args(["serve"])
        assert args.no_discovery is False

    def test_allow_plugins_and_no_discovery_together(self) -> None:
        """--allow-plugins and --no-discovery can coexist in args namespace."""
        parser = self._make_parser()
        args = parser.parse_args(
            ["serve", "--allow-plugins", "io.sox.x", "--no-discovery"]
        )
        assert args.allow_plugins == "io.sox.x"
        assert args.no_discovery is True


# ---------------------------------------------------------------------------
# H. _resolve_plugin_env: precedence and env-var propagation
# ---------------------------------------------------------------------------


class TestResolvePluginEnv:
    """Test _resolve_plugin_env() — CLI overrides SOX_ALLOWED_PLUGINS."""

    def _make_args(
        self,
        allow_plugins: str | None = None,
        no_discovery: bool = False,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            allow_plugins=allow_plugins,
            no_discovery=no_discovery,
        )

    def test_cli_allow_plugins_sets_env_var(self) -> None:
        """--allow-plugins sets SOX_ALLOWED_PLUGINS in os.environ."""
        from sox_protocol.cli.serve import _resolve_plugin_env

        env_backup = os.environ.pop("SOX_ALLOWED_PLUGINS", None)
        try:
            _resolve_plugin_env(self._make_args(allow_plugins="io.sox.x"))
            assert os.environ.get("SOX_ALLOWED_PLUGINS") == "io.sox.x"
        finally:
            if env_backup is not None:
                os.environ["SOX_ALLOWED_PLUGINS"] = env_backup
            else:
                os.environ.pop("SOX_ALLOWED_PLUGINS", None)

    def test_cli_overrides_sox_allowed_plugins_env_var(self) -> None:
        """--allow-plugins=cli-id overrides SOX_ALLOWED_PLUGINS=env-id (§6.1 precedence)."""
        from sox_protocol.cli.serve import _resolve_plugin_env

        os.environ["SOX_ALLOWED_PLUGINS"] = "env-id"
        try:
            _resolve_plugin_env(self._make_args(allow_plugins="cli-id"))
            assert os.environ["SOX_ALLOWED_PLUGINS"] == "cli-id"
        finally:
            os.environ.pop("SOX_ALLOWED_PLUGINS", None)

    def test_no_allow_plugins_leaves_env_var_unchanged(self) -> None:
        """When --allow-plugins absent, existing SOX_ALLOWED_PLUGINS is not touched."""
        from sox_protocol.cli.serve import _resolve_plugin_env

        os.environ["SOX_ALLOWED_PLUGINS"] = "existing-value"
        try:
            _resolve_plugin_env(self._make_args(allow_plugins=None))
            assert os.environ["SOX_ALLOWED_PLUGINS"] == "existing-value"
        finally:
            os.environ.pop("SOX_ALLOWED_PLUGINS", None)

    def test_no_discovery_sets_env_var(self) -> None:
        """--no-discovery sets SOX_NO_DISCOVERY=1."""
        from sox_protocol.cli.serve import _resolve_plugin_env

        os.environ.pop("SOX_NO_DISCOVERY", None)
        try:
            _resolve_plugin_env(self._make_args(no_discovery=True))
            assert os.environ.get("SOX_NO_DISCOVERY") == "1"
        finally:
            os.environ.pop("SOX_NO_DISCOVERY", None)

    def test_no_discovery_false_does_not_set_env_var(self) -> None:
        """--no-discovery absent (False) does not set SOX_NO_DISCOVERY."""
        from sox_protocol.cli.serve import _resolve_plugin_env

        os.environ.pop("SOX_NO_DISCOVERY", None)
        try:
            _resolve_plugin_env(self._make_args(no_discovery=False))
            assert "SOX_NO_DISCOVERY" not in os.environ
        finally:
            os.environ.pop("SOX_NO_DISCOVERY", None)

    def test_cli_allow_plugins_takes_precedence_over_env_var(self) -> None:
        """Integration: SOX_ALLOWED_PLUGINS='env-id'; --allow-plugins='cli-id' → CLI wins."""
        from sox_protocol.cli.serve import _resolve_plugin_env

        os.environ["SOX_ALLOWED_PLUGINS"] = "env-id"
        try:
            _resolve_plugin_env(self._make_args(allow_plugins="cli-id"))
            assert os.environ["SOX_ALLOWED_PLUGINS"] == "cli-id", (
                "CLI --allow-plugins must override SOX_ALLOWED_PLUGINS"
            )
        finally:
            os.environ.pop("SOX_ALLOWED_PLUGINS", None)
