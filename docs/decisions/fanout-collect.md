# Decision: fanout-collect

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q4 (fan-out / collect)

## Context
Fan-out (one sender, N recipients in a group) is the core "group chat for agents" use case — orchestrator broadcasting to worker agents is the canonical demo. The question is whether fanout/collect are first-class protocol verbs with server-side atomicity guarantees, or SDK conveniences over `send` + `recv`. The vision doc emphasizes "Groups are first-class" — that constraint pulls toward protocol-level support, but only if the spec actually offers something `N × send()` cannot.

## Decision
**Option C (refined) — Hybrid: `channels__send` to a group channel is the fan-out primitive (no new verb needed); `channels__collect` is a first-class server-side aggregation tool; pure client-side fan-out is the SDK fallback.** Because the dm-semantics decision modeled groups as managed channels, sending to a group is already one `channels__send` against a group-channel name — the server handles delivery to all members. There is no `channels__fanout`; it would be a synonym for send-to-group. `channels__collect` *is* a new tool: given a `reply_to` message-id and a wait spec (count, timeout, quorum), the server blocks until the condition is met and returns the matching ACKs/replies in one call. SDKs ship a `fanout()` helper that is cosmetic over send-to-group and a `collect()` helper that is a thin wrapper over the tool.

## Rationale
Send-to-group as fan-out falls out of the dm-semantics unification for free — adding `channels__fanout` would duplicate `channels__send` and contradict the minimum-primitives posture. Collect is the asymmetric case: implementing it client-side is N parallel recvs with manual timeout and quorum logic, which is exactly the kind of orchestration plumbing that should live in the protocol if "groups are first-class" means anything operationally. Server-side collect can use the same pending-state record that ACK and `list_pending` already maintain — no new backing-store primitive, just a query against existing state. Atomicity question (3-of-5 deliver before failure): the protocol guarantees at-least-once delivery per group member via the existing ACK/retry path; collect surfaces the partial-result honestly (returns received-set + missing-set + timeout flag) rather than pretending to atomic broadcast. Trade-off accepted: no exactly-once group broadcast guarantee. That's a distributed-systems impossibility under partial failure; honesty beats fiction.

## Consequences
- Positive: One new verb (`collect`), not two. Spec surface stays small.
- Positive: Collect uses the pending-state record from ack-mechanism — single source of truth, no new backing-store capability.
- Positive: Orchestrator pattern (broadcast + wait for N replies) is one send + one collect. The 30-second demo writes itself.
- Positive: Partial-failure semantics are explicit in the collect response shape, not hidden behind a fake atomicity guarantee.
- Negative: Long-blocking `collect` calls hold a server-side wait; needs a max-timeout cap and probably a websocket or long-poll transport binding to be efficient. Document the transport constraint.
- Negative: Quorum semantics (M-of-N) need a precise spec — is it M ACKs with status=`done`, or M replies of any kind? Decide explicitly.
- Spec impact: `spec/groups.md` (per dm-semantics follow-up) defines group channels; fan-out is "send to a group channel". `spec/collect.md` defines `channels__collect` verb (params: `reply_to`, `count` or `quorum`, `timeout`, optional `status_filter`) and the response shape (`received[]`, `missing[]`, `timed_out: bool`). `ports/transport.md` documents the long-poll/streaming requirement for efficient collect.

## Open questions for follow-up
- Exact quorum semantics — count-of-ACKs vs. count-of-replies vs. configurable. Lean configurable via `status_filter`.
- Whether `collect` can be cancelled by the caller mid-wait. Yes, almost certainly; spec the cancel verb or piggyback on a generic cancel.
- Whether multiple collectors can wait on the same `reply_to` (observer pattern). Probably yes; verify against pending-state record semantics.
- Recovery/replay for partial fan-out: if the server crashes mid-broadcast, do un-delivered members get the message on reconnect? Should be yes via the standard replay+`since` path, but write a conformance test.
