---
slug: plugin-architecture
state: planned
provisional_roi: high
canonical_roi: high
created: 2026-05-01
last_event: 2026-05-01T17:00:00Z
---

# Engagement: plugin-architecture (umbrella, v2)

Umbrella plan for the SOX Protocol plugin architecture program. Revised
2026-05-01 after first workflow-optimizer pass and three workflow-researcher
findings. analysis.md §7 now supersedes earlier sections where conflicting.

## Objective

Make SOX Protocol's middleware framework actually pluggable end-to-end —
Express/Fastify/Backstage-style — with cross-cutting concerns (logging,
auth, DB connections, audit, rate-limit, schema validation) living outside
core behind a normative manifest-driven plugin contract.

## Topics

plugin-architecture, middleware-pipeline, manifest-driven-discovery,
protocol-version-negotiation, kind-taxonomy-2-axis, transport-integration,
cross-language-portability, conformance-harness-substitution-deletion,
supply-chain-allowlist, plugin-failure-semantics, ordering-cycles,
pipeline-observability

## Sub-engagements (revised)

| Slug | Goal | Effort | Prereqs |
|---|---|---|---|
| `pipeline-integration` | Pipeline becomes only path to BackingStore in both transports; **absorbs** harness-cleanup; ships pipeline_trace observability + verifier asyncio.Lock | 4-5d | — |
| `plugin-contract-freeze` (was plugin-manifest-spec B1) | ADR 0004 + sox-plugin.yaml JSON Schema + plugin-contract.md (4-kind 2-axis taxonomy + failure semantics + cycle detection) + versioning.md | 2-3d | — |
| `plugin-spec-polish` (B2) | Directory restructure of spec/ports/middleware → directory; 6 conformance fixtures; cross-references | 2-3d | plugin-contract-freeze |
| `plugin-discovery-py` | Wire load_plugins + manifest validation + `--allow-plugins` allowlist into server bootstraps | 3-4d | plugin-contract-freeze |
| `reference-plugins` | **Narrowed to 1 plugin:** schema-strict (transformer; migrates routes._validate_body) | 2d | plugin-discovery-py |
| `plugin-architecture-ts` | **Reduced to 1-day spike:** TS protocol.ts (types only) + manifest round-trip validation; no runtime port | 1d | plugin-contract-freeze |
| `reference-plugins-extended` (post-v1) | audit-jsonl + rate-limit-redis + redis-pool provider — deferred until contract pressure-tested | — | reference-plugins |
| ~~harness-cleanup~~ | **Removed** — folded into pipeline-integration phases 06+07 | — | — |

## Critical-path compression (per §7.6)

- Original v1 plan: ~21 days sequential, 6 sub-engagements
- Revised v2 plan: ~13 days sequential / ~10 days parallel, 7 sub-engagements (1 post-v1)
- 38% sequential reduction; 52% parallel reduction; one fewer engagement on critical path

## Dependency graph (revised)

```
pipeline-integration (4-5d) ───────────────────────────────┐
                                                            │
plugin-contract-freeze (2-3d) ──┬─→ plugin-discovery-py (3-4d) ──→ reference-plugins (2d)
                                │
                                ├─→ plugin-architecture-ts (spike, 1d)
                                │
                                └─→ plugin-spec-polish (2-3d) [parallel w/ C/D/E]
```

`pipeline-integration` and `plugin-contract-freeze` are independent — ship
in parallel from day 0 if capacity allows.

## State transitions

- 2026-05-01T13:00:00Z initialized — workflow-architect (manual)
- 2026-05-01T13:00:00Z analyzed — analysis.md v1 written
- 2026-05-01T14:00:00Z suggested — workflow-optimizer wrote suggestions.md (provisional_roi=high)
- 2026-05-01T15:00:00Z research-applied — 3 workflow-researcher findings persisted to global memory:
  - `plugin-manifest-formats/cross-language-convergence.md`
  - `plugin-taxonomies/multi-kind-vs-unified-middleware.md`
  - `plugin-protocol-versioning/version-declaration-and-negotiation.md`
- 2026-05-01T15:30:00Z revised — analysis.md §7 added; sub-engagement directories restructured (rename, split, delete, narrow); STATE.md files updated. Awaiting second workflow-optimizer pass.
- 2026-05-01T16:00:00Z re-suggested — workflow-optimizer second pass wrote suggestions-v2.md (provisional_roi=high; 5 spec-amendment recommendations + 4 new risks; no engagement effort estimates change)
- 2026-05-01T17:00:00Z planned — workflow-planner wrote migration.md (canonical_roi=high, phases=7 [6 v1 + 1 post-v1]; all v2 deltas folded into per-sub-engagement phase prompts)

## Open decisions for owner (per §7.8)

1. **§7.1 — kind taxonomy collapse 5→4 in 2 axes** (Guard folds into Interceptor) — research-grounded, ratify or reject
2. **§7.2 — entry point out of manifest body** — language-neutral but two-file authoring
3. **§7.3 — PEP 440 wire form** for protocol_version — vs npm-style caret
4. **§7.5 risk #6 — `sox.yaml` descope to env-vars-only for v1**
5. **§7.6 — `plugin-architecture-ts` reduces to spike** — most contentious; original goal said "Mirror Python design before TS code lands"
6. **§7.5 risk #2 — failure semantics defaults** — hook exceptions swallowed (proposed) vs fail-closed

## Blockers (active)

- (none) — analysis revised; sub-engagements restructured; awaiting second
  workflow-optimizer pass before spawning workflow-planner for migration.md.

## Blockers (resolved)

- 2026-05-01T15:30:00Z resolved: 7 missed risks (per first optimizer pass)
  now addressed normatively in analysis §7.5
- 2026-05-01T15:00:00Z resolved: 3 research-memory gaps (manifest formats,
  kind taxonomies, version negotiation) — persisted to global memory

## Files

- [analysis.md](./analysis.md) — full architectural analysis (v2: §§0–6 original + §7 revisions)
- [suggestions.md](./suggestions.md) — first workflow-optimizer pass (5 suggestions, 7 missed risks)
- [suggestions-v2.md](./suggestions-v2.md) — second workflow-optimizer pass (5 spec amendments to §7, 4 new risks, ratifies §7.6 decomposition)
- (migration.md — forthcoming from workflow-planner if approved)

## Sub-engagement state files

- [`../pipeline-integration/STATE.md`](../pipeline-integration/STATE.md)
- [`../plugin-contract-freeze/STATE.md`](../plugin-contract-freeze/STATE.md)
- [`../plugin-spec-polish/STATE.md`](../plugin-spec-polish/STATE.md)
- [`../plugin-discovery-py/STATE.md`](../plugin-discovery-py/STATE.md)
- [`../reference-plugins/STATE.md`](../reference-plugins/STATE.md)
- [`../plugin-architecture-ts/STATE.md`](../plugin-architecture-ts/STATE.md)
- [`../reference-plugins-extended/STATE.md`](../reference-plugins-extended/STATE.md)
