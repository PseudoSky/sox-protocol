# Decision: replay-access-control

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q3 (replay / audit log)

## Context
Replay (re-reading historical messages from a channel) needs an access-control model decided at the spec level before audit-log implementation begins. Options range from "same auth as recv" (consistent) to "admin-only capability" (stricter, separation of concerns) to per-channel configurable. The middleware/auth posture and the schema-validation split (this batch Q2) push toward expressing all access decisions through the middleware chain.

## Decision
**Option C — Configurable per channel, with a `replay_policy` field; default is `subscriber`.** Each channel's config carries `replay_policy: subscriber | admin_only | custom`. With `subscriber`, replay is gated by exactly the same middleware chain as `recv` — if a principal can recv from a channel, it can replay. With `admin_only`, replay requires a principal whose credential carries an `admin` capability (definition supplied by the auth middleware in use). With `custom`, the channel owner registers a replay-specific middleware sub-chain that runs in addition to the recv chain. The replay verb is a distinct protocol verb (`replay(channel, range)`), not a flavor of `recv`, so policy can branch on it; but in the default `subscriber` policy the same auth/identity middleware is invoked for both verbs.

## Rationale
A single hard-coded model is wrong for SOX's stated audience: a hobbyist two-agent demo wants subscriber-equals-replay (zero ceremony); a regulated audit-log deployment wants strict admin-only replay; a research deployment wants custom logic (e.g. time-windowed access). The middleware posture decided for auth and schema validation makes per-channel policy cheap to express — policy is just middleware configuration on a verb. Distinguishing `replay` from `recv` at the verb level (rather than flagging within `recv`) gives the policy engine a clean structured action to evaluate, which the policy-enforcement research finding identifies as the load-bearing layer. Default `subscriber` keeps the v1 demo experience friction-free while leaving a clear upgrade path. Trade-off accepted: three policy variants to document and conformance-test, and the `custom` mode means replay behaviour is not fully specified by the spec — that's the price of the extensibility story.

## Consequences
- Positive: Default behaviour matches the principle of least surprise (you can re-read what you could read).
- Positive: Compliance deployments get hard separation by flipping one config field; no fork required.
- Positive: Replay as a distinct verb integrates cleanly with deterministic policy engines (Cedar/OPA-style) — `action: replay` is a first-class subject for rules.
- Negative: One more channel-config knob; users must understand the difference between recv and replay policy.
- Negative: `custom` mode admits arbitrary behaviour, which complicates conformance tests for non-default deployments. Mitigation: conformance suite covers `subscriber` and `admin_only` exhaustively; `custom` is tested for the *contract* (middleware chain is invoked) not the *policy*.
- Spec impact: `spec/replay.md` defines the `replay(channel, range)` verb, response envelope, and pagination/cursor semantics. `spec/channels.md` adds `replay_policy: subscriber | admin_only | custom` to channel config (default `subscriber`). `spec/middleware.md` defines how `admin` capability is asserted (auth-middleware-defined predicate). `ports/store.md` requires range queries by `seq` or timestamp. Aligns with federation-scope decision: per-channel `seq` makes range queries well-defined.

## Open questions for follow-up
- Range expression: by `seq` range, by timestamp range, or both? Recommend both; pin in spec extraction.
- Whether replay returns identical envelopes to the originals or wraps them in a `replay_meta` shell (origin time vs. replay time). Recommend wrapping; defer concrete shape.
- Interaction with retention/compaction: what does replay do for a range partially evicted by retention policy? Recommend a `RANGE_PARTIAL` response with the available subrange. Defer details to the audit-log post-v1 work.
- How `admin` capability is granted and verified in the reference auth middleware — depends on the in-progress identity-primitive decision.
