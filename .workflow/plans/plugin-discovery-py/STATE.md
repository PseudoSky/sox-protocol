---
slug: plugin-discovery-py
target: Wire MiddlewareRegistry.load_plugins() into server startup with manifest validation. Out-of-tree plugins discoverable via Python entry-points. sox-plugin.yaml validated against schema before registration. `--allow-plugins` allowlist mandatory for production (risk #1). `--no-discovery` flag for testing/security audits.
created: 2026-05-01
last_event: 2026-05-01T18:30:00Z
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
| 03-allowlist | Implement `--allow-plugins ID,...` CLI flag + `SOX_ALLOWED_PLUGINS` env var. Default-deny in production mode; default-allow in dev mode (with explicit warning) | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 04-bootstrap-integration | `mcp_server/server.py` and `transports/http/app.py` invoke `registry.load_plugins()` after `build_default_pipeline` | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 05-test | Install stub plugin into temp venv; assert discovered + invoked. Test allowlist denial. Test version-mismatch refusal envelope shape | `BLOCKED` | test-automator | 0 | 2026-05-01T15:00:00Z |
| 06-review | Code review including security audit of the discovery boundary | `BLOCKED` | code-reviewer | 0 | 2026-05-01T15:00:00Z |

## Currently next action

Dispatch **phase 03-allowlist**: implement `--allow-plugins ID,...` CLI flag in
`packages/python/src/sox_protocol/cli/serve.py` and wire `SOX_ALLOWED_PLUGINS` /
`SOX_ENV` / `SOX_NO_DISCOVERY` env-var reads into the allowlist branches of
`MiddlewareRegistry.load_plugins()` (already implemented in 02-build;
`load_plugins` accepts `allowlist`, `env`, `no_discovery` params — CLI layer
just needs to pass them through).

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

## Termination targets

- [ ] All 6 phases DONE
- [x] `core/middleware/plugin_loader.py` reads sox-plugin.yaml, validates against schema, validates protocol_version range, instantiates via declared entry
- [ ] `MiddlewareRegistry.load_plugins(allowlist=...)` calls load_entry_points + validates + filters by allowlist + registers
- [ ] `mcp_server/server.py` and `transports/http/app.py` invoke `registry.load_plugins(...)` after `build_default_pipeline`
- [ ] `sox serve --allow-plugins ID,...` flag respected; `SOX_ALLOWED_PLUGINS` env var also respected
- [ ] `sox serve --no-discovery` flag short-circuits the loader entirely
- [ ] Production mode (env `SOX_ENV=production`): empty allowlist refuses to load any plugin; non-empty allowlist filters strictly
- [ ] Dev mode (default): all discovered plugins loaded, with stderr warning per discovered-but-unallowlisted plugin
- [ ] Integration test: stub plugin in temp venv discovered + invoked end-to-end
- [ ] Integration test: stub plugin with mismatched protocol_version rejected with `plugin_protocol_version_mismatch` envelope
- [ ] Integration test: stub plugin with cyclic must_run_before/after rejected with `plugin_ordering_cycle` envelope
- [ ] mypy --strict clean; lint-imports kept

## Reference

See parent analysis at [`../plugin-architecture/analysis.md`](../plugin-architecture/analysis.md) §4.3 + §7.5 risk #1 (supply-chain) + §7.5 risk #3 (cycles).
