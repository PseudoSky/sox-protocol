---
slug: plugin-discovery-py
target: Wire MiddlewareRegistry.load_plugins() into server startup with manifest validation. Out-of-tree plugins discoverable via Python entry-points. sox-plugin.yaml validated against schema before registration. `--allow-plugins` allowlist mandatory for production (risk #1). `--no-discovery` flag for testing/security audits.
created: 2026-05-01
last_event: 2026-05-01T15:00:00Z
orchestrator_protocol: v1
parent_plan: plugin-architecture
prereqs: [plugin-contract-freeze]
---

# plugin-discovery-py — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Plan plugin_loader.py + bootstrap wire-up + allowlist semantics | `BLOCKED` | sox-cto-system:planner | 0 | 2026-05-01T15:00:00Z |
| 02-build | Build `core/middleware/plugin_loader.py` (reads sox-plugin.yaml from package, validates schema, validates protocol_version range, applies must_run_before/after toposort with cycle detection per B1 spec) | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 03-allowlist | Implement `--allow-plugins ID,...` CLI flag + `SOX_ALLOWED_PLUGINS` env var. Default-deny in production mode; default-allow in dev mode (with explicit warning) | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 04-bootstrap-integration | `mcp_server/server.py` and `transports/http/app.py` invoke `registry.load_plugins()` after `build_default_pipeline` | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 05-test | Install stub plugin into temp venv; assert discovered + invoked. Test allowlist denial. Test version-mismatch refusal envelope shape | `BLOCKED` | test-automator | 0 | 2026-05-01T15:00:00Z |
| 06-review | Code review including security audit of the discovery boundary | `BLOCKED` | code-reviewer | 0 | 2026-05-01T15:00:00Z |

## Currently next action

All phases `BLOCKED` on `plugin-contract-freeze` (sox-plugin.schema.json + topological-sort algorithm + allowlist requirement must be specified before loader can implement them).

## Termination targets

- [ ] All 6 phases DONE
- [ ] `core/middleware/plugin_loader.py` reads sox-plugin.yaml, validates against schema, validates protocol_version range, instantiates via declared entry
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
