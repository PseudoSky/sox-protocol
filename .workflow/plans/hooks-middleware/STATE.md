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
| 02-plan | Implementation plan | `DONE` | sox-cto-system:planner | 1 | 2026-04-30T17:09:00Z |
| 03-implement | Build pipeline + migrate identity plugin | `DONE` | python-pro | 1 | 2026-04-30T18:30:00Z |
| 05-op-coverage | Widen Operation literal + StoreDispatch op-table; add terminal coverage | `DONE` | python-pro | 1 | 2026-04-30T21:55:00Z |
| 04-review | Code review | `READY` | code-reviewer | 0 | 2026-04-30T21:55:00Z |

## Currently next action

`04-review` is `READY`. In-scope changes verified: 99 tests green, no pragmas, 15 ops in `Operation` literal and `store_dispatch` op-table. (Other working-tree changes in `core/identity/`, adapters tests, integration tests, http test dirs are from a parallel coverage-push agent in a separate shell, not this phase.)

## Transitions

- 2026-04-29T00:00:00Z all four phases initialized
- 2026-04-30T20:45:00Z salvage audit: 02-plan and 03-implement retroactively DONE (commit `e33d0f2`, 83/83, 100% cov); inserted 05-op-coverage for spec drift remediation; 04-review re-blocked on 05

## Reconciliation note (2026-04-30, salvage audit)

Middleware port spec at `spec/ports/middleware.md` is unchanged since plan; pipeline architecture is sound and conforms. Drifts to remediate (light):
- ⚠️ `Operation` literal in `context.py` lists 8 ops; missing `list_agents` (now v1 MUST per `9f3e11e`) and the channels__/group__ MCP-tool ops
- ⚠️ `StoreDispatchMiddleware` switch handles 4 ops (send/recv/subscribe/list_channels); other ops fall through to `internal_error`
- ⚠️ `_StoreTerminal` adapter at `default_chain.py:44-60` marked `# pragma: no cover` — terminal path untested despite 100% headline

§9 `schema_validator` default-on requirement is gated on a sibling engagement and tracked separately.

See `.workflow/plans/SALVAGE-AUDIT-2026-04-30.md`.

## Termination targets

- [ ] All phases DONE
- [ ] `docs/adr/0003-extensibility-mechanism.md` committed
- [ ] `spec/ports/middleware.md` defines the interface
- [ ] `packages/python/src/sox_protocol/core/middleware/` implements the framework
- [ ] Identity middleware migrated into the new framework, still passing identity-primitive tests
- [ ] At least one sample plugin (logging or rate-limit) demonstrating composition
- [ ] 100% coverage; mypy --strict; lint-imports clean
