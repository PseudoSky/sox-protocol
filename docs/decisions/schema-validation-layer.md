# Decision: schema-validation-layer

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q2 (typed channels / schema validation)

## Context
Typed channels require a schema registry and a validator. The registry can live in the backing store (storing the schema bound to the channel) and validation can be enforced either at the store layer (every implementation must validate) or as a middleware plugin (flexible, tree-shakeable). The decision must align with the credential-primitive direction (auth as middleware) and the hooks-middleware engagement.

## Decision
**Option C — Split: channel schema registry is backing-store-level, validation is middleware-level.** The backing store owns the schema artifact: a channel may have a registered schema (JSON Schema document, content-addressable, versioned) stored alongside its config; ports define `get_schema(channel) -> Schema | None` and `set_schema(channel, schema)`. Validation is NOT performed by the store. A first-party `schema_validator` middleware reads the registered schema for the channel on each `send` and rejects messages whose body does not conform; this middleware is enabled by default in the reference deployment but is removable. Backing stores are explicitly forbidden from rejecting sends on schema grounds — they are dumb about message body content.

## Rationale
Aligning with the middleware posture chosen for auth gives one consistent extensibility story: cross-cutting policy is middleware; persistence is the store. This is exactly the two-tier split surfaced in the policy-enforcement research finding (Layer 1 semantic/declarative vs. Layer 2 deterministic gating) — a schema validator is Layer 1 over structured data and belongs in the same middleware chain as content rails, PII filters, and rate limits. Putting validation in the store would force every alternative implementation (Rust, Go, in-memory test doubles) to ship a JSON Schema engine and would couple persistence concerns to validation concerns. Conversely, refusing to standardise where the *schema artifact* lives would let each store invent its own registry shape, breaking schema portability. Splitting registry (store) from enforcement (middleware) gives cross-language consistency on the artifact while preserving flexibility on the policy. Trade-off accepted: a deployment that disables the validator middleware silently accepts malformed messages — that risk is documented and mitigated by shipping the validator on by default.

## Consequences
- Positive: Consistent with auth-as-middleware; one mental model for cross-cutting policy.
- Positive: Schemas are portable across implementations because the registry contract is in the store port; any conforming store exposes the same `get_schema`/`set_schema` shape.
- Positive: Tree-shakeable for performance-sensitive deployments that own their producers and don't need server-side validation.
- Negative: Two places to look for schema behaviour (store for the artifact, middleware chain for enforcement). Documentation must make the split explicit.
- Negative: A misconfigured deployment (validator disabled) accepts garbage on typed channels. Mitigation: ship-on-by-default and a conformance test that asserts the default chain rejects schema violations.
- Spec impact: `spec/typed-channels.md` defines the schema artifact format (JSON Schema, version field, content hash). `ports/store.md` adds `get_schema`/`set_schema`. `spec/middleware.md` defines the `schema_validator` reference middleware and its position in the default chain (after auth, before persistence). `ports/middleware.md` (from hooks-middleware engagement) is the host.

## Open questions for follow-up
- Schema language: JSON Schema (draft 2020-12) is the obvious choice; confirm during spec extraction. Alternatives (Avro, Protobuf) deferred.
- Schema evolution: how do `v1` and `v2` of a channel's schema coexist? Recommend content-addressable schemas with channel-config pinning a version; defer concrete migration semantics.
- Whether validation errors flow through the same envelope as auth errors (`VALIDATION_FAILED` vs. typed sub-codes). Pin in `spec/errors.md`.
- Interaction with replay: if a channel's schema changes, do historical messages still validate? Recommend "messages are validated against the schema active at send time, recorded by content hash on the envelope." Confirm with the replay-access-control decision.
