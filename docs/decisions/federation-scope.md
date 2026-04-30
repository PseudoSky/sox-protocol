# Decision: federation-scope

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q2

## Context
Federation (multi-server SOX deployments that route messages across server boundaries) affects identity, channel namespacing, ordering, and replay. Deciding it post-spec-freeze means painful retrofitting; deciding it in-scope for v1 implementation balloons v1 effort. The vision doc lists this as resolution priority #5 and explicitly flags it as "unanswered and dangerous."

## Decision
**Option B — Federation is out of v1 implementation, but the v1 spec is federation-AWARE.** No federation code ships in v1. However, the v1 spec reserves the necessary slots so that a v2 federated deployment is additive, not breaking: (1) agent identity is structured as `<server-id>/<agent-id>` with the server-id slot allowed to be empty/implicit in single-server deployments; (2) channel names allow an optional `<server-id>:` prefix in the same way; (3) `seq` semantics are scoped per-channel (see Q3) rather than global, so no global counter must be unwound later; (4) the envelope reserves an `origin_server` field, optional in v1, populated in federated deployments.

## Rationale
Federation is a multi-quarter implementation effort (gossip, conflict resolution, trust model, replay across server boundaries) that would gate v1 launch indefinitely if pulled in. But option A (single-server-aware spec) commits to identity and namespace shapes that are expensive to change post-launch — a published spec with users is hard to break. Option B accepts the small upfront tax of one extra identifier slot and an optional envelope field in exchange for keeping v2 federation purely additive. The vision doc's "spec is the product" posture makes spec stability worth more than v1 implementation simplicity. Trade-off accepted: v1 envelopes carry one always-present optional field that single-server users will find slightly noisy.

## Consequences
- Positive: v1 ships in reasonable time. Spec doesn't need a breaking 2.0 to add federation later.
- Positive: Forces clean thinking about identity and namespacing now, before users lock in.
- Negative: Slight ceremony in single-server deployments (server-id is empty string or `local`). Documentation must explain why the slot exists.
- Negative: Spec authors must resist scope creep — "federation-aware" is a discipline, not a green light to design federation features.
- Spec impact: `spec/identity.md` defines `<server-id>/<agent-id>` form. `spec/channels.md` defines optional server-id prefix in channel names. `spec/envelope.md` reserves `origin_server` field. `spec/ordering.md` (see Q3) constrained to per-channel seq.

## Open questions for follow-up
- Concrete federation transport (gossip vs. server-to-server WebSocket vs. queue-mediated) — defer entirely to v2 design.
- Trust model between servers (mutual TLS, signed envelopes, CA hierarchy) — defer.
- Whether `server-id` is a DNS name, a UUID, or an opaque string — pin during spec extraction; recommend opaque string with a normalization rule.
