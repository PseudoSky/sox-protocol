# Decision: seq-ordering-scope

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q3

## Context
The `seq` field on every envelope provides ordering for replay, ack tracking, and cursor-based reads (`since=<seq>`). It can be a single global monotone counter (total ordering, simple client logic, hot global counter at scale) or per-channel (partial ordering, scalable, federation-friendly). This decision is tightly coupled to federation-scope (Q2), since a global counter cannot be federated without a coordination protocol.

## Decision
**Option B — Per-channel seq.** Each channel maintains its own monotone `seq` counter starting at 1. Clients reading with `since=<seq>` are reading per-channel cursors. There is no cross-channel total order in the protocol; if two messages are sent on different channels, their relative order is unspecified. A separate, optional, monotonic `ts` (server-assigned timestamp, monotonic-per-server) is included in the envelope for human-readable ordering and as a tiebreaker for cross-channel display.

## Rationale
Q2 chose federation-aware spec, which makes per-channel seq mandatory: a federated v2 cannot maintain a global counter without distributed coordination, so committing to global seq in v1 would either lock out federation or force a breaking spec change later. Per-channel seq also avoids the single-counter contention point that bites at scale (every send takes a write lock on the global counter). The cost — losing cross-channel total ordering — is small in practice: SOX is "group chat for agents," and chat semantics rarely depend on ordering events across unrelated rooms; when display-time ordering matters, the `ts` field handles it. Option C (both) was rejected as premature — it doubles client logic for a v1 use case nobody has yet.

## Consequences
- Positive: No hot global counter. Each channel scales independently.
- Positive: Per-channel replay is trivially correct: `since=<seq>` on a channel returns exactly what the client missed.
- Positive: v2 federation adds no ordering retrofit — per-channel seq with `origin_server` in the envelope is already federation-shaped.
- Negative: No protocol-level total order across channels. Tooling that wants a unified timeline (audit log, debugger) must sort by `ts` and accept the weaker guarantee.
- Negative: `ts` must be monotonic-per-server and clearly documented as advisory, not authoritative.
- Spec impact: `spec/envelope.md` defines `seq` (per-channel monotone, ≥ 1) and `ts` (server-assigned, monotone-per-server). `spec/ordering.md` documents partial-order guarantee and tiebreaking. `spec/replay.md` defines `since` as per-channel cursor. `ports/store.md` requires per-channel atomic increment, not a global sequence.

## Open questions for follow-up
- Whether `ts` is wall-clock-derived (with monotonic correction) or pure logical clock — recommend nanosecond-precision wall clock with monotonic-per-server enforcement; pin during spec extraction.
- Whether replay tools want a synthesized cross-channel cursor (e.g. `(channel, seq)` pair list) — defer to replay-tool design.
