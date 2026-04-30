# Architect-question decision index

Source: `.workflow/plans/bucket-classification/result.md` (21 questions)
Last updated: 2026-04-30

## Legend

| Status | Meaning |
|---|---|
| `delegated` | An ADR phase in a named engagement will resolve this question |
| `pending` | Orphan — queued for orchestrator-dispatched architect resolution |
| `resolved` | Decision recorded at `docs/decisions/<slug>.md` |
| `escalated` | Requires human judgment — options surfaced to user |

---

## Question index

| # | Section | Slug | Status | Resolved-by / Notes |
|---|---|---|---|---|
| 1 | agent identity verification | `credential-primitive` | `delegated` | `identity-primitive/01-adr` |
| 2 | threading | `threading-depth` | `resolved` | `docs/decisions/threading-depth.md` |
| 3 | middleware / hooks / auth | `middleware-interface` | `delegated` | `hooks-middleware/01-adr` |
| 4 | presence / heartbeat | `heartbeat-mechanism` | `resolved` | `docs/decisions/heartbeat-mechanism.md` |
| 5 | direct messages | `dm-semantics` | `resolved` | `docs/decisions/dm-semantics.md` |
| 6 | ACK / processing signal | `ack-mechanism` | `resolved` | `docs/decisions/ack-mechanism.md` |
| 7 | fan-out / collect | `fanout-collect` | `resolved` | `docs/decisions/fanout-collect.md` |
| 8 | backpressure | `backpressure-model` | `resolved` | `docs/decisions/backpressure-model.md` |
| 9 | typed channels / schema validation | `schema-validation-layer` | `resolved` | `docs/decisions/schema-validation-layer.md` |
| 10 | observability | `observability-meta-mode` | `resolved` | `docs/decisions/observability-meta-mode.md` |
| 11 | idempotent send / deduplication | `idempotency-ttl` | `resolved` | `docs/decisions/idempotency-ttl.md` |
| 12 | multi-server / federation | `federation-scope` | `resolved` | `docs/decisions/federation-scope.md` |
| 13 | message ordering | `seq-ordering-scope` | `resolved` | `docs/decisions/seq-ordering-scope.md` |
| 14 | replay / audit log | `replay-access-control` | `resolved` | `docs/decisions/replay-access-control.md` |
| 15 | channel namespacing / tenant isolation | `namespace-isolation-layer` | `resolved` | `docs/decisions/namespace-isolation-layer.md` |
| 16 | admin / management API | `admin-api-colocation` | `resolved` | `docs/decisions/admin-api-colocation.md` |
| 17 | groups (first-class, distinct from channels) | `groups-model` | `resolved` | `docs/decisions/groups-model.md` |
| 18 | deadlock detection | `deadlock-detection-approach` | `resolved` | `docs/decisions/deadlock-detection-approach.md` |
| 19 | protocol versioning | `version-negotiation-mechanism` | `resolved` | `docs/decisions/version-negotiation-mechanism.md` |
| 20 | SOX chat UI / TUI | `tui-connection-model` | `resolved` | `docs/decisions/tui-connection-model.md` |
| 21 | SOX chat UI / Web app | `webapp-deployment-model` | `resolved` | `docs/decisions/webapp-deployment-model.md` |
