---
slug: reference-plugins-extended
target: Two additional reference plugins post-v1 — sox-plugin-audit-jsonl (kind: interceptor) and sox-plugin-rate-limit-redis (kind: interceptor with `requires: capability provider`). Demonstrates breadth of the plugin contract (multiple kinds, capability-string requires). Post-v1 because each exercises contract surfaces that warrant pressure-testing under real load before publication.
created: 2026-05-01
last_event: 2026-05-01T15:00:00Z
orchestrator_protocol: v1
milestone: post-v1
parent_plan: plugin-architecture
prereqs: [reference-plugins]
---

# reference-plugins-extended — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Plan two plugins after v1 ships and contract has real-world signal | `BLOCKED` | sox-cto-system:planner | 0 | 2026-05-01T15:00:00Z |
| 02-build-audit-jsonl | `plugins/sox-plugin-audit-jsonl/` — kind: interceptor (observe_only:true), JSONL audit log w/ rotation | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 03-build-rate-limit | `plugins/sox-plugin-rate-limit-redis/` — kind: interceptor (may_short_circuit:true), `requires: rate_limit.backend: ">=1.0"` (provider capability) | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 04-redis-provider | Reference `provider` plugin: `plugins/sox-provider-redis-pool/` — proves the lifecycle-axis contract | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 05-review | Cross-plugin review for contract consistency under multiple kinds | `BLOCKED` | code-reviewer | 0 | 2026-05-01T15:00:00Z |

## Currently next action

`milestone: post-v1` — do not start until v1 has shipped and `reference-plugins` (schema-strict) has demonstrated the contract end-to-end.

## Termination targets

- [ ] All 5 phases DONE
- [ ] Three plugin packages exist under `plugins/`
- [ ] Each: 100% line coverage, mypy --strict, lint-imports clean
- [ ] Each loads via plugin-discovery mechanism without core modifications
- [ ] `audit-jsonl` demonstrates `observe_only: true` capability with runtime no-short-circuit assertion
- [ ] `rate-limit-redis` demonstrates `may_short_circuit: true` interceptor + `requires` capability dependency on a provider
- [ ] `redis-pool` provider demonstrates lifecycle-axis kind (no `__call__`; `on_startup`/`on_shutdown` only)
- [ ] Optional: a 4th plugin shipped by an external contributor — proves the spec is fork-friendly

## Reference

See parent analysis at [`../plugin-architecture/analysis.md`](../plugin-architecture/analysis.md) §7.6 (deferral rationale).
