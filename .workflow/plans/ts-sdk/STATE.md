---
slug: ts-sdk
target: @sox-protocol/client npm package shipping. TypeScript SDK with codegen from spec schemas. Browser+Node compatible. Conformance suite passes via TS test harness, proving spec is portable beyond Python.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# ts-sdk — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | SDK + codegen plan | `IN_PROGRESS` | sox-cto-system:planner | 1 | 2026-04-30T00:00:00Z |
| 02-build | Build SDK + codegen + helpers | `BLOCKED` | typescript-pro | 0 | 2026-04-29T00:00:00Z |
| 03-conformance | TS conformance harness | `BLOCKED` | test-automator | 0 | 2026-04-29T00:00:00Z |

## Currently next action

`01-plan` is `IN_PROGRESS` (parallel batch 2026-04-30T00:00:00Z).

## Termination targets

- [ ] All phases DONE
- [ ] `packages/typescript/` workspace built
- [ ] @sox-protocol/client publishable to npm
- [ ] tsc --strict, eslint, no `any`, 100% coverage
- [ ] Conformance suite passes via a TS-implemented harness (cross-impl proof)
