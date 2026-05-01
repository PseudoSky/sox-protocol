---
slug: plugin-spec-polish
target: Spec hygiene work that is NOT on the critical path. Promote spec/ports/middleware.md → directory; ship the 6 conformance fixtures (initially pending:true); cross-reference all docs. Runs in parallel with plugin-discovery-py / reference-plugins / plugin-architecture-ts.
created: 2026-05-01
last_event: 2026-05-01T15:00:00Z
orchestrator_protocol: v1
parent_plan: plugin-architecture
prereqs: [plugin-contract-freeze]
parallel_with: [plugin-discovery-py, reference-plugins, plugin-architecture-ts]
---

# plugin-spec-polish — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-restructure | Promote `spec/ports/middleware.md` → `spec/ports/middleware/` directory; split into 8 files (README, 01-context, 02-pipeline, 03-plugin-contract from B1, 04-manifest, 05-discovery, 06-versioning from B1, 07-default-chain, 08-conformance) | `DONE` | api-designer | 1 | 2026-05-01T16:00:00Z |
| 02-discovery-doc | Author `spec/ports/middleware/05-discovery.md` — Python entry-points + Node package.json `sox` key + programmatic register | `DONE` | api-designer | 1 | 2026-05-01T16:00:00Z |
| 03-conformance-fixtures | Author 7 fixtures under `spec/conformance/plugin-contract/` (load-via-entry-point, version-mismatch, kind-enforcement, applies-to-scope, must-run-before-after, short-circuit-explicit, provider-lifecycle-synthetic). All `pending: true` until P4+P5 ship | `DONE` | api-designer | 1 | 2026-05-01T16:00:00Z |
| 04-cross-references | Cross-reference ADR 0003 ↔ ADR 0004 ↔ middleware/* docs; update `spec/README.md` index; update `spec/conformance/README.md` | `DONE` | api-designer | 1 | 2026-05-01T16:00:00Z |
| 05-review | Spec review for completeness | `DONE` | api-designer | 1 | 2026-05-01T16:00:00Z |

## Currently next action

All phases DONE. Engagement complete. Handoff to P4 (`plugin-discovery-py`) and P5 (`reference-plugins`) to un-skip the 7 pending fixtures.

## Termination targets

- [x] All phases DONE
- [x] `spec/ports/middleware/` directory exists with 8 normative files (README + 01–08)
- [x] Original `spec/ports/middleware.md` replaced with 6-line redirect stub
- [x] 7 fixtures under `spec/conformance/plugin-contract/` exist and parse cleanly (yaml.safe_load passes)
- [x] Cross-references between ADR 0003, ADR 0004, and middleware/* docs all bidirectional
- [x] `spec/README.md` index updated to reflect new structure
- [x] No regression in existing 32 conformance fixtures (32 passed, 0 failed, 34 skipped)

## Reference

See parent analysis at [`../plugin-architecture/analysis.md`](../plugin-architecture/analysis.md) §7.6 for the B1/B2 split rationale.
