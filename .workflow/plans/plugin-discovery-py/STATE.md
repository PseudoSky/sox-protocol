---
slug: plugin-discovery-py
target: Wire MiddlewareRegistry.load_plugins() into server startup with manifest validation. Out-of-tree plugins discoverable via Python entry-points. sox-plugin.yaml validated against schema before registration. `--allow-plugins` allowlist mandatory for production (risk #1). `--no-discovery` flag for testing/security audits.
created: 2026-05-01
last_event: 2026-05-04T00:00:00Z
orchestrator_protocol: v1
parent_plan: plugin-architecture
prereqs: [plugin-contract-freeze]
---

# plugin-discovery-py — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Plan plugin_loader.py + bootstrap wire-up + allowlist semantics | `DONE` | sox-cto-system:planner | 1 | 2026-05-01T15:00:00Z |
| 02-build | Build `core/middleware/plugin_loader.py` (reads sox-plugin.yaml from package, validates schema, validates protocol_version range, applies must_run_before/after toposort with cycle detection per B1 spec) | `DONE` | python-pro | 1 | 2026-05-01T18:30:00Z |
| 03-allowlist | Implement `--allow-plugins ID,...` CLI flag + `SOX_ALLOWED_PLUGINS` env var. Default-deny in production mode; default-allow in dev mode (with explicit warning) | `DONE` | python-pro | 1 | 2026-05-03T00:00:00Z |
| 04-bootstrap-integration | `mcp_server/server.py` and `transports/http/app.py` invoke `registry.load_plugins()` after `build_default_pipeline` | `DONE` | python-pro | 1 | 2026-05-04T00:00:00Z |
| 05-test | Install stub plugin into temp venv; assert discovered + invoked. Test allowlist denial. Test version-mismatch refusal envelope shape | `READY` | test-automator | 0 | 2026-05-01T15:00:00Z |
| 06-review | Code review including security audit of the discovery boundary | `BLOCKED` | code-reviewer | 0 | 2026-05-01T15:00:00Z |

## Currently next action

Dispatch **phase 05-test**: install stub plugin into temp venv (real venv, not
mocked entry-points); assert discovered + invoked end-to-end. Test
version-mismatch refusal envelope shape.

## Transition log

### 2026-05-01 — phase 01-plan: STATE stale correction

Phase 01-plan was marked `BLOCKED` but was actually completed at commit
`48b1860` (implementation-plan.json committed). STATE.md was not updated
after plan completion. Corrected to `DONE` in this update alongside phase
02-build landing.

### 2026-05-01 — phase 02-build: DONE

**Agent:** python-pro  
**Commit:** feat(plugin-loader): manifest loader, typed errors, registry.load_plugins, unit tests

**Files landed:**

- `packages/python/src/sox_protocol/core/middleware/plugin_loader.py` (NEW, 315 lines)
  - `Manifest` dataclass (10 fields mirroring schema spec block + metadata.id/version)
  - `read_manifest_for_entry_point(ep) -> dict` — locates sox-plugin.yaml via dist.files
  - `validate_manifest(doc) -> Manifest` — jsonschema.validate + signatures structural check
  - `parse_version_range(s) -> SpecifierSet` — PEP 440 first, npm caret fallback (R1 handled)
  - `check_protocol_version(manifest, host_version) -> None | raises` — §4.2 algorithm, prereleases=True for pre-release hosts (§4.4)
  - `assert_capability_orthogonality(manifest) -> None | raises` — observe_only+may_short_circuit conflict
  - `canonicalize_env_var(plugin_id, key) -> str` — §7.2 algorithm
  - Hard import boundary: no `sox_protocol.adapters` imports (verified by grep)

- `packages/python/src/sox_protocol/core/middleware/errors.py` (MODIFIED)
  - Added `PluginStartupError(MiddlewareError)` base with `error_code: ClassVar[str]` + `to_envelope() -> dict[str, str]`
  - Added 7 typed subclasses: `PluginNotAllowed`, `PluginNotFound`, `PluginManifestInvalid`, `PluginProtocolVersionMismatch`, `PluginCapabilityConflict`, `PluginOrderingCycle`, `PluginRequirementUnmet`
  - `PluginProtocolVersionMismatch` carries five-field envelope per §5.1

- `packages/python/src/sox_protocol/core/middleware/registry.py` (MODIFIED)
  - Added `_toposort_plugins(manifests) -> list[str]` — stable Kahn with lex tie-break
  - Added `MiddlewareRegistry.load_plugins(*, allowlist, env, host_protocol_version, no_discovery, group)` — full 7-step orchestration
  - Added `MiddlewareRegistry.resolved_order` property
  - `load_entry_points()` left untouched (R6 backward compat)

- `packages/python/src/sox_protocol/core/middleware/__init__.py` (MODIFIED)
  - Re-exports all 8 plugin startup error classes + `Manifest`

- `packages/python/pyproject.toml` (MODIFIED)
  - Added `pyyaml>=6.0` and `packaging>=23.0` to runtime deps
  - Added `types-PyYAML>=6.0` to dev deps

- `packages/python/tests/middleware/test_plugin_loader.py` (NEW, 55 tests)
  - All 55 tests pass

**Public API surface:** 10 items in plugin_loader.py + 8 plugin error classes in errors.py + 2 registry methods = 20 total new public API items.

**Acceptance gates at commit:**
- `mypy --strict`: Success, 81 source files, 0 errors
- `pytest`: 1158 passed, 2 failed (pre-existing group_invite failures)
- stdio conformance: 33 passed, 0 failed, 34 skipped
- HTTP conformance: 24 passed, 9 failed (pre-existing baseline), 34 skipped

**Notes:**
- Phase 02 does NOT wire `load_plugins()` into any bootstrap — that is phase 04.
  The loader is built but dormant; no runtime behavior changes.
- `parse_version_range("")` returns an unconstrained `SpecifierSet` (PEP 440
  treats empty string as "no constraints"); empty protocol_version is rejected
  at `validate_manifest()` via schema `minLength: 1`. Test updated to reflect this.

### 2026-05-03 — phase 03-allowlist: DONE

**Agent:** python-pro (with inline fix for ad-hoc Namespace tests)

**CLI flags added to `packages/python/src/sox_protocol/cli/serve.py`:**
- `--allow-plugins ID,...` — comma-separated plugin IDs to allow; sets
  `SOX_ALLOWED_PLUGINS` env var. Takes precedence over the env var when both
  are present (§6.1 CLI-precedence rule).
- `--no-discovery` — sets `SOX_NO_DISCOVERY=1`. Short-circuits the loader
  before entry-point scan (R4).
- `_resolve_plugin_env(args)` helper writes flags into env vars BEFORE
  branching on transport so both stdio lifespan and HTTP create_app read
  uniformly. Uses `getattr(args, ..., default)` defensively to support
  ad-hoc `argparse.Namespace` constructions in pre-phase-03 tests.

**Allowlist branches in `MiddlewareRegistry.load_plugins()`:** all 4
combinations covered by tests in
`packages/python/tests/middleware/test_registry_load_plugins.py` (NEW):
- `no_discovery=True` → empty `resolved_order`, no entry-point scan
- `env=production` + empty allowlist → `PluginNotAllowed` raised
  (supply-chain protection per analysis §7.5 risk #1)
- `env=production` + non-empty allowlist → strict filter, unmatched IDs
  rejected
- `env=dev` + empty allowlist → load-all silently
- `env=dev` + non-empty allowlist → matched loaded; unallowlisted skipped
  with stderr warning per skipped plugin

**Acceptance gates at commit:**
- `mypy --strict`: Success, 81 source files, 0 errors
- `pytest`: 1186 passed, 2 failed (pre-existing group_invite — unchanged)
- stdio conformance: 33 passed, 0 failed, 34 skipped (no regression)
- HTTP conformance: 24 passed, 9 failed, 34 skipped (no regression)

**Inline fix applied during this session:**
3 pre-existing CLI tests (`test_serve_command_stdio_delegates_to_mcp_server`,
`test_serve_command_http_sets_env_and_runs_uvicorn`,
`test_serve_command_http_no_host_no_port`) construct `argparse.Namespace`
ad-hoc without the new attributes. Fixed `_resolve_plugin_env` to use
`getattr(args, "allow_plugins", None)` and `getattr(args, "no_discovery", False)`
defensively. Argparse-built namespaces always carry the attributes (default
values from `add_serve_subcommand`); the getattr defends only ad-hoc tests.

## Termination targets

- [ ] All 6 phases DONE
- [x] `core/middleware/plugin_loader.py` reads sox-plugin.yaml, validates against schema, validates protocol_version range, instantiates via declared entry
- [x] `MiddlewareRegistry.load_plugins(allowlist=...)` calls load_entry_points + validates + filters by allowlist + registers
- [x] `mcp_server/server.py` and `transports/http/app.py` invoke `registry.load_plugins(...)` after `build_default_pipeline`
- [x] `sox serve --allow-plugins ID,...` flag respected; `SOX_ALLOWED_PLUGINS` env var also respected
- [x] `sox serve --no-discovery` flag short-circuits the loader entirely
- [x] Production mode (env `SOX_ENV=production`): empty allowlist refuses to load any plugin; non-empty allowlist filters strictly
- [x] Dev mode (default): all discovered plugins loaded, with stderr warning per discovered-but-unallowlisted plugin
- [ ] Integration test: stub plugin in temp venv discovered + invoked end-to-end
- [ ] Integration test: stub plugin with mismatched protocol_version rejected with `plugin_protocol_version_mismatch` envelope
- [ ] Integration test: stub plugin with cyclic must_run_before/after rejected with `plugin_ordering_cycle` envelope
- [x] mypy --strict clean; lint-imports kept

### 2026-05-04 — phase 04-bootstrap-integration: DONE

**Agent:** python-pro
**Commit:** feat(plugin-discovery): bootstrap wire-up + extend_pipeline_with_registry

**Helper added:**

- `extend_pipeline_with_registry(base_pipeline, registry, terminal) -> Pipeline`
  in `core/middleware/default_chain.py`. Reads `base_pipeline._middlewares` to
  extract the default chain, appends each plugin factory from
  `registry.resolved_order`, and returns a new `Pipeline` with the same
  terminal. Rebuild-once-at-startup pattern; no `Pipeline.with_appended` per
  analysis §7.5 risk #4 (hot-reload deferred). Re-exported from
  `core/middleware/__init__.py`.

**stdio bootstrap wire-up (`core/mcp_server/server.py`):**

- Added `from sox_protocol.core.middleware.registry import register_middleware`
  and `_HOST_PROTOCOL_VERSION = "1.0.0"` constant.
- After `pipeline = build_default_pipeline(...)` in `_lifespan`: reads
  `SOX_ALLOWED_PLUGINS` / `SOX_ENV` / `SOX_NO_DISCOVERY` env vars, calls
  `register_middleware.load_plugins(...)`.
- On `PluginStartupError`: logs structured envelope to stderr + `sys.exit(1)`
  (fail-fast per ADR 0004).
- If `resolved_order` non-empty: rebuilds pipeline via
  `extend_pipeline_with_registry` with a fresh `_StoreTerminal`.
- Note: FastMCP 2.x stores the user lifespan as `mcp._lifespan` (not via
  `mcp.lifespan()`). Tests call `mcp._lifespan(mcp)` directly to exercise the
  plugin init path.

**HTTP bootstrap wire-up (`adapters/transports/http/server.py`):**

- Added `_HOST_PROTOCOL_VERSION = "1.0.0"` constant.
- Added `allowlist`, `env`, `no_discovery` kwargs to `create_app()` with
  defaults preserving existing behaviour (`env="dev"`, `allowlist=None`,
  `no_discovery=False`).
- After `built_pipeline` is determined: resolves allowlist/env/no_discovery
  from kwargs first, falls back to env vars (`SOX_ALLOWED_PLUGINS`,
  `SOX_ENV`, `SOX_NO_DISCOVERY`), calls `register_middleware.load_plugins(...)`.
- On `PluginStartupError`: logs + re-raises (uvicorn exits non-zero on ASGI
  startup failure).
- If `resolved_order` non-empty: extends pipeline via
  `extend_pipeline_with_registry`.

**Error envelope shape on production + empty allowlist:**

```json
{
  "error_code": "plugin_not_allowed",
  "plugin_id": "*",
  "message": "SOX_ENV=production requires an explicit --allow-plugins allowlist. ..."
}
```

**Tests added (`tests/middleware/test_bootstrap_wireup.py`, 10 tests):**

- `TestHttpCreateAppNoDiscovery`: `no_discovery=True` kwarg + `SOX_NO_DISCOVERY=1`
  env var → app created, `resolved_order == ()`.
- `TestHttpCreateAppProductionEmptyAllowlist`: `env=production`, no allowlist →
  `PluginNotAllowed` raised with required envelope fields. Also via env vars.
- `TestHttpCreateAppHappyPath`: fake entry-point → plugin loaded, appears in
  `resolved_order`.
- `TestMcpServerNoDiscovery`: `SOX_NO_DISCOVERY=1` → lifespan yields cleanly,
  `resolved_order == ()`; spy confirms `load_plugins` called with
  `no_discovery=True`.
- `TestMcpServerProductionEmptyAllowlist`: `SOX_ENV=production` + fake entry-point
  → `sys.exit(1)` from lifespan.
- `TestLoadPluginsCalledAfterBuildPipeline`: spy confirms `build_default_pipeline`
  is called before `load_plugins` in `create_app`.

**Acceptance gates at commit:**

- `mypy --strict`: Success, 81 source files, 0 errors
- `pytest`: 1196 passed, 2 failed (pre-existing group_invite — unchanged)
- stdio conformance: 33 passed, 0 failed, 34 skipped (no regression)
- HTTP conformance: 24 passed, 9 failed, 34 skipped (no regression)

**Notes:**

- `host_protocol_version` is hard-coded as `_HOST_PROTOCOL_VERSION = "1.0.0"` in
  both bootstrap files. No shared version module exists in the codebase; both
  bootstraps carry their own constant (parallel to `_PROTOCOL_VERSION = "1.0"` in
  `http/server.py`). Phase 06-review may unify these.
- The conformance harness runs with no env vars → dev mode, no real entry points
  → `load_plugins` finds 0 plugins → `resolved_order = ()` → no conformance
  regression.
- FastMCP 2.x `mcp.lifespan()` iterates provider lifespans only; the
  user-supplied lifespan runs via `mcp._lifespan(mcp)` (stored as `self._lifespan`
  in `FastMCP.__init__`). Tests use `_lifespan` directly to avoid FastMCP
  internals.

## Reference

See parent analysis at [`../plugin-architecture/analysis.md`](../plugin-architecture/analysis.md) §4.3 + §7.5 risk #1 (supply-chain) + §7.5 risk #3 (cycles).
