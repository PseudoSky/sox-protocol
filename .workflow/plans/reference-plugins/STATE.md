---
slug: reference-plugins
target: One reference plugin shipped outside core/ to prove the contract — sox-plugin-schema-strict (kind: transformer). Migrates `routes._validate_body` duplication out of core. Demonstrates manifest-driven discovery + transformer kind end-to-end. Audit-jsonl and rate-limit-redis deferred to reference-plugins-extended (post-v1).
created: 2026-05-01
last_event: 2026-05-01T15:00:00Z
orchestrator_protocol: v1
parent_plan: plugin-architecture
prereqs: [plugin-contract-freeze, plugin-discovery-py]
narrowed_from: 3 plugins → 1 (per analysis §7.6 / optimizer suggestion #2)
---

# reference-plugins — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Plan one plugin: API surface, manifest, lifecycle, tests, package layout | `BLOCKED` | sox-cto-system:planner | 0 | 2026-05-01T15:00:00Z |
| 02-build-schema-strict | `plugins/sox-plugin-schema-strict/` — kind: transformer; pyproject.toml; sox-plugin.yaml; src/; tests/; integration with sox-plugin spec from B1 | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 03-migrate-routes | Delete `routes.py:_validate_body` (and the 22 inline validation calls); replace with the plugin in the chain | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 04-review | Review for contract conformance — does the plugin demonstrate the manifest-driven discovery path end-to-end without core/ modifications? | `BLOCKED` | code-reviewer | 0 | 2026-05-01T15:00:00Z |

## Currently next action

All phases `BLOCKED` on `plugin-contract-freeze` (manifest schema must exist) and `plugin-discovery-py` (loader must be wired).

## Termination targets

- [ ] All 4 phases DONE
- [ ] `plugins/sox-plugin-schema-strict/` exists as standalone package — own pyproject.toml, sox-plugin.yaml manifest, src/, tests/
- [ ] 100% line coverage on the plugin
- [ ] mypy --strict clean
- [ ] Plugin loads via plugin-discovery mechanism (not just programmatic registration in tests)
- [ ] `routes.py:_validate_body` deleted; the 22 inline validation call sites removed
- [ ] schema validation now runs as the `transformer` kind in the chain on both transports
- [ ] Conformance suite still 32/0/27 against both transports with the plugin enabled
- [ ] **Demonstrates that contract works end-to-end with zero `core/` modifications**

## Why one plugin, not three

Optimizer suggestion #2 + §7.6: schema-strict migrates *real existing code*
(measurable LOC reduction in `routes.py`), exercises only the
least-controversial kind (transformer), and does not depend on the
`Provider` contract — which §7.5 risk #2/#6 reveals still needs failure-mode
specification. Three plugins built simultaneously against an unfrozen
contract risks three divergent interpretations and costly re-alignment.
One canonical migration is sufficient contract proof; breadth comes after
the contract has been pressure-tested.

## Out-of-scope — handled by sibling engagement

- `sox-plugin-audit-jsonl` (kind: interceptor) → `reference-plugins-extended` (post-v1)
- `sox-plugin-rate-limit-redis` (kind: interceptor + requires provider) → `reference-plugins-extended` (post-v1, after Provider failure semantics finalized)

## Reference

See parent analysis at [`../plugin-architecture/analysis.md`](../plugin-architecture/analysis.md) §7.6 for the narrowing rationale.
