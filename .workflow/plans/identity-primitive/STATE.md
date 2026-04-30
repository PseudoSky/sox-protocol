---
slug: identity-primitive
target: Verified-sender identity layer shipped as the first middleware plugin. Per-agent credential registry. Audit log. ADR + spec section + reference implementation + tests.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# identity-primitive — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-adr | Resolve credential primitive (ADR) | `READY` | architect-reviewer | 0 | 2026-04-29T00:00:00Z |
| 02-plan | Implementation plan from ADR + spec | `BLOCKED` | sox-cto-system:planner | 0 | 2026-04-29T00:00:00Z |
| 03-implement | Build credential registry + middleware | `BLOCKED` | python-pro | 0 | 2026-04-29T00:00:00Z |
| 04-review | Code review | `BLOCKED` | code-reviewer | 0 | 2026-04-29T00:00:00Z |

## Currently next action

`01-adr` is `READY`. Spawn `architect-reviewer`.

## Transitions

- 2026-04-29T00:00:00Z 04-review — initialized (BLOCKED)
- 2026-04-29T00:00:00Z 03-implement — initialized (BLOCKED)
- 2026-04-29T00:00:00Z 02-plan — initialized (BLOCKED)
- 2026-04-29T00:00:00Z 01-adr — initialized (READY)

## Termination targets

- [ ] All phases DONE
- [ ] `docs/adr/0002-agent-identity-primitive.md` committed
- [ ] `spec/ports/identity.md` defines the verified-sender guarantee
- [ ] `packages/python/src/sox_protocol/core/identity/` has credential registry + middleware plugin
- [ ] 100% coverage on new identity code; mypy --strict clean; lint-imports clean
- [ ] Audit log writes to `~/.sox/logs/identity-failures.jsonl` on rejection
