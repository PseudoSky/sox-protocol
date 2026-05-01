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
| 01-restructure | Promote `spec/ports/middleware.md` → `spec/ports/middleware/` directory; split into 8 files (README, 01-context, 02-pipeline, 03-plugin-contract from B1, 04-manifest, 05-discovery, 06-versioning from B1, 07-default-chain, 08-conformance) | `BLOCKED` | api-designer | 0 | 2026-05-01T15:00:00Z |
| 02-discovery-doc | Author `spec/ports/middleware/05-discovery.md` — Python entry-points + Node package.json `sox` key + programmatic register | `BLOCKED` | api-designer | 0 | 2026-05-01T15:00:00Z |
| 03-conformance-fixtures | Author 6 fixtures under `spec/conformance/plugin-contract/` (load-via-entry-point, version-mismatch, kind-enforcement, applies-to-scope, must-run-before-after, short-circuit-explicit). Initially `pending: true` until plugin-discovery-py wires the loader | `BLOCKED` | api-designer | 0 | 2026-05-01T15:00:00Z |
| 04-cross-references | Cross-reference ADR 0003 ↔ ADR 0004 ↔ middleware/* docs; update `spec/README.md` index | `BLOCKED` | api-designer | 0 | 2026-05-01T15:00:00Z |
| 05-review | Spec review for completeness | `BLOCKED` | architect-reviewer | 0 | 2026-05-01T15:00:00Z |

## Currently next action

All phases `BLOCKED` on `plugin-contract-freeze` (B1) landing.

## Termination targets

- [ ] All phases DONE
- [ ] `spec/ports/middleware/` directory exists with 8 normative files
- [ ] Original `spec/ports/middleware.md` removed (or kept as redirect stub)
- [ ] 6 fixtures under `spec/conformance/plugin-contract/` exist and parse cleanly via existing harness
- [ ] Cross-references between ADR 0003, ADR 0004, and middleware/* docs all bidirectional
- [ ] `spec/README.md` index updated to reflect new structure
- [ ] No regression in existing 32 conformance fixtures

## Reference

See parent analysis at [`../plugin-architecture/analysis.md`](../plugin-architecture/analysis.md) §7.6 for the B1/B2 split rationale.
