# Decision: deadlock-detection-approach

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q4 (deadlock detection)

## Context
Deadlock detection across agents requires the server to know who is waiting on whom, which means `list_pending` state must be server-authoritative rather than derived ad hoc on each client. The question is whether the wait graph deserves a dedicated `waiting_on` schema column (O(1) detection, extra writes) or can be computed at query time from `reply_to` + `delivered_to` (no schema change, O(n) traversal). The vision doc flags `list_pending` as already "doing a lot."

## Decision
**Option B for v1 — compute the wait graph from existing `reply_to` + `delivered_to` columns at query time, with an explicit upgrade path to Option A documented in the backing-store port.** Deadlock detection is exposed as a server-side query (`admin__detect_deadlocks` or equivalent), not a per-message hot-path concern. At v1 scale (tens of agents, hundreds of pending replies), graph traversal on demand is comfortably fast. The schema is left clean for the upgrade.

## Rationale
A dedicated `waiting_on` column is a write-amplification cost paid on every wait operation in exchange for a read benefit (deadlock detection) that runs rarely and tolerates latency. At v1 scale the read is fast enough without it; at scale it becomes worthwhile, but the right move is to add it when measurements justify it, not speculatively. Option C (out of scope entirely) is rejected because the vision doc treats `list_pending` and the enforcer stop-block as core to the SOX story — surfacing deadlocks is part of "the protocol knows what an agent is," not an operator side-quest. Trade-off accepted: detection latency scales with pending-reply count, and the migration to Option A is a real schema change later.

## Consequences
- Positive: No schema bloat in v1. Backing-store port stays minimal.
- Positive: Existing columns already carry the information; no double-write coherence problem.
- Positive: Deadlock detection is a real protocol feature, not a deferred concern.
- Negative: Detection cost is O(pending-reply-count). At thousands of pending replies it will need re-evaluation.
- Negative: Naive implementations may re-traverse on every call; spec should suggest caching the result with a short TTL.
- Spec impact: `spec/list-pending.md` declares the wait graph computable from envelope fields. `spec/deadlock-detection.md` defines the detection query semantics. `ports/backing-store.md` notes the optional `waiting_on` index as a v1.x or v2 upgrade. Conformance suite includes simple-cycle and transitive-cycle test fixtures.

## Open questions for follow-up
- Cache TTL for repeated detection calls (probably 1–5s; defer to implementation).
- Whether the detection result should auto-trigger a NACK on the oldest waiter (policy decision, defer to enforcer spec).
- Trigger threshold for migrating to dedicated column — measurement target, not a spec concern.
