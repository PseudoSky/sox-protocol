---
slug: hooks-middleware
target: Pluggable extensibility framework chosen and shipped. Identity check refactored to be the first plugin. Sample logging or rate-limit plugin demonstrating composition.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# hooks-middleware — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-adr | Resolve hooks vs middleware (ADR) | `DONE` | architect-reviewer | 1 | 2026-04-30T00:00:00Z |
| 02-plan | Implementation plan | `READY` | sox-cto-system:planner | 0 | 2026-04-30T00:00:00Z |
| 03-implement | Build pipeline + migrate identity plugin | `BLOCKED` | python-pro | 0 | 2026-04-29T00:00:00Z |
| 04-review | Code review | `BLOCKED` | code-reviewer | 0 | 2026-04-29T00:00:00Z |

## Currently next action

`02-plan` is `READY`. Spawn `sox-cto-system:planner`.

## Transitions

- 2026-04-29T00:00:00Z all four phases initialized

## Termination targets

- [ ] All phases DONE
- [ ] `docs/adr/0003-extensibility-mechanism.md` committed
- [ ] `spec/ports/middleware.md` defines the interface
- [ ] `packages/python/src/sox_protocol/core/middleware/` implements the framework
- [ ] Identity middleware migrated into the new framework, still passing identity-primitive tests
- [ ] At least one sample plugin (logging or rate-limit) demonstrating composition
- [ ] 100% coverage; mypy --strict; lint-imports clean
