# Decision: backpressure-model

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q1 (backpressure)

## Context
Backpressure can be advisory (send always succeeds, response carries a flag if the recipient queue is over threshold) or enforced (send blocks/errors when over limit). Enforced backpressure is safer for memory bounds but breaks the non-blocking send guarantee that simplifies client code. This decision constrains the send/recv envelope shape and the conformance suite.

## Decision
**Option C — Advisory by default, enforced opt-in per channel.** The base protocol guarantees non-blocking send. Every send response includes a structured backpressure field (`{queue_depth, threshold, state: ok|warn|over}`) for the recipient's pending queue; senders MAY use this to self-throttle. A channel config flag `backpressure_mode: advisory|enforced` (default `advisory`) lets channel owners opt into enforced mode, in which the server returns a typed `BACKPRESSURE_OVER_LIMIT` error when a send would exceed the recipient's bound. Enforcement, when enabled, is a server-side check; it is NOT layered as middleware because the bound lives in the backing store and must be consistent across all sends.

## Rationale
The vision doc emphasises "thoroughly tested" and a non-blocking send is the simpler default to specify and test cross-language. But several legitimate deployments (lossless audit pipelines, slow human-in-the-loop reviewers) need real backpressure, and forcing those users to write their own enforcement on top of advisory signals would push protocol concerns into application code — exactly what SOX's spec-as-product posture rejects. Per-channel opt-in keeps the default surface small while making the safer mode reachable without a new primitive. The advisory field is always present so client code is uniform regardless of mode. Trade-off accepted: two send-result shapes to test (advisory-flag path and enforced-error path), and a small backing-store contract addition (queue depth must be observable at send time).

## Consequences
- Positive: Default non-blocking send preserved; clients written for v1 do not need to handle a new error case unless they opt in.
- Positive: Conformance suite gets one extra mode-toggle dimension, not a new verb.
- Positive: Aligns with the enforcer stop-block posture — the protocol already knows how to make an agent wait; enforced backpressure is the reciprocal control on the producer side.
- Negative: Two code paths in every backing-store implementation (advisory-fill vs. reject-over-limit). Test matrix grows.
- Negative: The `backpressure_mode` field is one more channel-config knob users must learn.
- Spec impact: `spec/envelope.md` adds a `backpressure: {queue_depth, threshold, state}` field on send responses. `spec/channels.md` adds `backpressure_mode` to channel config (default `advisory`). `spec/errors.md` reserves `BACKPRESSURE_OVER_LIMIT`. `ports/store.md` requires `peek_queue_depth(agent_id, channel)` capability so enforcement is implementable.

## Open questions for follow-up
- Threshold semantics: absolute count, or percentage of a configured max? Recommend absolute with a sensible default (e.g. 1000) and per-channel override; pin during spec extraction.
- Whether the advisory `state: warn` band is server-computed or sender-computed. Recommend server-computed so all senders see consistent values.
- Interaction with the enforcer stop-block: does an over-limit recipient also count as "pending" for stop-block purposes? Likely yes, but verify when the `list_pending` design doc lands.
