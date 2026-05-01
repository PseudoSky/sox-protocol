---
slug: plugin-architecture-ts
target: 1-day TS contract spike. Ship packages/typescript/src/core/middleware/protocol.ts as TYPES ONLY (Pipeline, MiddlewareContext, Middleware, CallNext interfaces; PluginKind enum; manifest types matching sox-plugin.schema.json). Validate sox-plugin.yaml round-trips through a TS YAML loader + AJV against the same JSON Schema Python uses. Proves the contract is portable. Full TS Pipeline runtime deferred to whenever real TS production code lands.
created: 2026-05-01
last_event: 2026-05-01T15:00:00Z
orchestrator_protocol: v1
parent_plan: plugin-architecture
prereqs: [plugin-contract-freeze]
narrowed_from: 6-phase 1-week port → 1-day spike (per analysis §7.6 / optimizer suggestion #5)
---

# plugin-architecture-ts — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-types | Author `packages/typescript/src/core/middleware/protocol.ts` — interface-only port of MiddlewareContext, Middleware, CallNext, PluginKind enum, manifest types matching sox-plugin.schema.json. No runtime, no Pipeline class, no Registry class | `BLOCKED` | typescript-pro | 0 | 2026-05-01T15:00:00Z |
| 02-manifest-roundtrip | Validate `sox-plugin.yaml` round-trips through `yaml` + `ajv` against the SAME JSON Schema the Python side uses. Produces a 30-line `validate-manifest.ts` test script | `BLOCKED` | typescript-pro | 0 | 2026-05-01T15:00:00Z |
| 03-doc-deferral | Update `packages/typescript/README.md` with explicit deferral note: "TS reference shape; full Pipeline + Registry runtime ships with first TS production code" | `BLOCKED` | typescript-pro | 0 | 2026-05-01T15:00:00Z |

## Currently next action

All phases `BLOCKED` on `plugin-contract-freeze` (must freeze the contract before porting types).

## Termination targets

- [ ] All 3 phases DONE — should fit in 1 day
- [ ] `packages/typescript/src/core/middleware/protocol.ts` exists with interfaces only
- [ ] TS interfaces are isomorphic to Python `Middleware` Protocol, `MiddlewareContext`, `PluginKind` enum
- [ ] `validate-manifest.ts` script confirms a sample manifest passes both Python and Node validation
- [ ] `packages/typescript/README.md` documents the deferral with a clear reactivation trigger ("when TS production code lands")
- [ ] No TS runtime code (Pipeline, Registry, plugin_loader) shipped in this engagement — that work is reactivated later as `plugin-architecture-ts-runtime`

## Why a spike, not a full port

Optimizer suggestion #5: `packages/typescript/` has no production code yet.
Building a full TS Pipeline runtime "to prevent drift" is YAGNI; the
contract (manifest + JSON Schema + interface signatures) is what prevents
drift, not a parallel runtime. Shipping a TS Pipeline runtime with no TS
users is dead weight that has to be maintained in sync with Python changes
through v1.x.

The spike satisfies the contract-freeze goal (types match Python; manifest
round-trips) without the maintenance burden of a parallel runtime. When
real TS code lands (current roadmap: post-v1), a `plugin-architecture-ts-runtime`
engagement implements Pipeline + Registry from these already-shipped types.

**This is the most contentious decision in §7.** The original goal stated
"Mirror Python design in TS SDK before TS code lands" — the spike satisfies
*design*, not *runtime*. Owner ratified per §7.8 decision #5 (or did not — see
suggestions.md from second optimizer pass).

## Reference

See parent analysis at [`../plugin-architecture/analysis.md`](../plugin-architecture/analysis.md) §7.6 + §7.8 decision #5.
