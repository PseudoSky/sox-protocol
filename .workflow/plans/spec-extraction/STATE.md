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
| 01-extract | Extract protocol spec from current implementation | `DONE` | api-designer | 1 | 2026-04-30T00:00:00Z |
| 03-reconcile | Reconcile spec with architecture decisions | `IN_PROGRESS` | api-designer | 3 | 2026-04-30T00:00:00Z |
| 02-review | Architectural review of spec/ | `BLOCKED` | architect-reviewer | 0 | 2026-04-30T00:00:00Z |

## Currently next action

`03-reconcile` is `IN_PROGRESS` (attempt 3). Re-dispatched with feedback-1.md corrective instructions.

## Transitions

- 2026-04-29T00:00:00Z 02-review — initialized (BLOCKED)
- 2026-04-29T00:00:00Z 01-extract — initialized (READY)
- 2026-04-30T00:00:00Z 03-reconcile — IN_PROGRESS → REVIEW (attempt 2; 3 exit criteria failed: ajv x-status, packages/ grep, markdownlint 29 errors)
- 2026-04-30T00:00:00Z 03-reconcile — REVIEW → IN_PROGRESS (attempt 3; re-dispatch with feedback-1.md)

## Termination targets

- [ ] All three phases DONE
- [ ] `spec/protocol.md` envelope carries seq, reply_to, delivered_to, origin_server
- [ ] `spec/operations/` has 8 operation pairs (send, recv, subscribe, list_channels, channels_ack, channels_heartbeat, channels_collect, replay)
- [ ] `spec/operations/*.json` JSON Schemas all valid 2020-12
- [ ] All 5 conflict primitives rewritten (dms, ack-nack, groups, sequence-numbers, presence)
- [ ] `spec/ports/backing-store.md` has namespace + schema registry + idempotency sweep
- [ ] `docs/adr/0001-protocol-vs-implementation-split.md` exists
- [ ] `docs/V1-SCOPE.md` exists — canonical v1 reference for downstream planners
- [ ] No `packages/` references inside `spec/`
