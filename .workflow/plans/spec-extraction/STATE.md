---
slug: spec-extraction
target: spec/ established as the canonical, language-agnostic protocol surface; packages/python clearly demarcated as one reference implementation; ADR documenting the protocol-vs-implementation split committed.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# spec-extraction — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-extract | Extract protocol spec from current implementation | `IN_PROGRESS` | api-designer | 1 | 2026-04-30T00:00:00Z |
| 02-review | Architectural review of spec/ | `BLOCKED` | architect-reviewer | 0 | 2026-04-29T00:00:00Z |

## Currently next action

`01-extract` is `READY`. Spawn `api-designer`.

## Transitions

- 2026-04-29T00:00:00Z 02-review — initialized (BLOCKED)
- 2026-04-29T00:00:00Z 01-extract — initialized (READY)

## Termination targets

- [ ] Both phases DONE
- [ ] `spec/protocol.md` and `spec/ports/{transport,backing-store,identity,middleware}.md` exist
- [ ] `spec/operations/*.json` JSON Schemas all valid 2020-12
- [ ] `docs/adr/0001-protocol-vs-implementation-split.md` exists
- [ ] No `packages/` references inside `spec/`
