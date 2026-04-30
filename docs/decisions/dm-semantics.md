# Decision: dm-semantics

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q1

## Context
A DM in SOX could be modeled either as a regular channel with a server-enforced naming convention (e.g. `dm/<sorted-pair>`), or as a first-class message type with distinct delivery semantics (exactly-once, no wildcard subscription, built-in read receipts). This decision blocks the unified "addressable destinations" design pass called out in the vision doc, and propagates into the groups-model decision (Q4).

## Decision
**Option A — DM = channel with naming convention plus server-side enforcement.** A DM is a managed channel whose name follows a reserved pattern (`dm/<sorted-pair-of-agent-ids>`). The server creates the channel on first send, enforces that only the two named agents may subscribe or send, blocks wildcard subscriptions on the `dm/` prefix, and otherwise reuses the entire channel machinery (envelope, seq, ack/nack, threading, replay, enforcer stop-block). Read-receipts, if added later, are a hook over normal ack semantics, not a new message type.

## Rationale
The vision doc explicitly flags threading + DMs + groups as "three half-coherent abstractions" and calls for a unifying "addressable destinations" pass; channels-with-convention is the unification. Adding a second delivery type doubles the surface for every cross-cutting concern (replay, audit, enforcer, conformance suite) and contradicts the spec-as-product posture, where minimizing primitive count is a primary virtue. Exactly-once and read-receipts are policy concerns implementable as middleware over channels — they don't require a distinct message kind. The trade-off accepted: no built-in cryptographic guarantee that a DM is unobservable to a privileged server operator; that's a deployment/auth concern, not a protocol concern.

## Consequences
- Positive: One delivery path. Threading, replay, presence, enforcer all work for DMs without special-casing. Conformance suite stays small.
- Positive: Sets up Q4 (groups-model) for the same unification — groups as managed channels.
- Negative: Server must enforce the `dm/` namespace as reserved; clients that try to create `dm/foo` directly must be rejected. Adds one validation rule.
- Negative: "Exactly-once DM" becomes a middleware/hook responsibility, not a protocol guarantee. Must be documented.
- Spec impact: `spec/channels.md` gains a "reserved name prefixes" section. `spec/dm.md` is a thin doc describing the `dm/<sorted-pair>` convention and membership-enforcement rules; no separate envelope or verb. `ports/transport.md` unchanged.

## Open questions for follow-up
- Exact canonicalization of the sorted-pair (lexicographic on agent-id strings? what about case?). Decide during spec extraction.
- Whether multi-party DMs (3–8 agents) collapse into "groups" or get their own `dm/<sorted-tuple>` form. Defer to groups-model decision and the addressable-destinations pass.
