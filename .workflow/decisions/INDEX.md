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
| 2 | threading | `threading-depth` | `pending` | — |
| 3 | middleware / hooks / auth | `middleware-interface` | `delegated` | `hooks-middleware/01-adr` |
| 4 | presence / heartbeat | `heartbeat-mechanism` | `pending` | — |
| 5 | direct messages | `dm-semantics` | `pending` | — |
| 6 | ACK / processing signal | `ack-mechanism` | `pending` | — |
| 7 | fan-out / collect | `fanout-collect` | `pending` | — |
| 8 | backpressure | `backpressure-model` | `pending` | — |
| 9 | typed channels / schema validation | `schema-validation-layer` | `pending` | — |
| 10 | observability | `observability-meta-mode` | `pending` | — |
| 11 | idempotent send / deduplication | `idempotency-ttl` | `pending` | — |
| 12 | multi-server / federation | `federation-scope` | `pending` | — |
| 13 | message ordering | `seq-ordering-scope` | `pending` | — |
| 14 | replay / audit log | `replay-access-control` | `pending` | — |
| 15 | channel namespacing / tenant isolation | `namespace-isolation-layer` | `pending` | — |
| 16 | admin / management API | `admin-api-colocation` | `pending` | — |
| 17 | groups (first-class, distinct from channels) | `groups-model` | `pending` | — |
| 18 | deadlock detection | `deadlock-detection-approach` | `pending` | — |
| 19 | protocol versioning | `version-negotiation-mechanism` | `pending` | — |
| 20 | SOX chat UI / TUI | `tui-connection-model` | `pending` | — |
| 21 | SOX chat UI / Web app | `webapp-deployment-model` | `pending` | — |
