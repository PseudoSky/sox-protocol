# Decision: namespace-isolation-layer

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q4 (channel namespacing / tenant isolation)

## Context
Namespacing (tenant isolation) can be implemented as a backing-store concept (each namespace maps to a separate database file or schema, hard isolation) or as a middleware enforcement layer (single store, all queries filtered by namespace). The federation-scope decision committed the v1 spec to be federation-aware, with channel names allowing an optional `<server-id>:` prefix; namespaces interact with that slot. The middleware posture (auth, schema validation, replay policy) pushes toward middleware-side enforcement, but middleware-only isolation is famously a "one missing filter from a leak" architecture.

## Decision
**Option C — Split: namespace is a backing-store concept (the store knows about it and tags every record), but the isolation mechanism is configurable.** Every channel and every message in the store is tagged with a `namespace` field (string, default `default`). The store port requires that all read/write operations be parameterised by namespace and that no API can return cross-namespace records. *How* the store achieves that is a deployment choice declared at store-construction time:
- `mode: shared` — single database, all queries include a namespace WHERE clause enforced inside the store implementation (not in middleware).
- `mode: isolated` — namespace maps to a separate SQLite file or Postgres schema; the store routes per-namespace.

A namespace-resolver middleware sits in front of the store and derives the active namespace from the authenticated principal (default rule: principal's home namespace; overridable). The middleware does NOT enforce isolation — the store does. The middleware's only job is to attach the correct namespace to the request context.

## Rationale
Pure middleware enforcement (Option B) is the textbook tenant-isolation foot-gun: any code path that constructs a store query without going through the middleware-set context leaks across tenants. The policy-enforcement research finding is explicit that deterministic gating belongs at the structured-action layer — but tenant isolation is a *data-layer invariant*, not a policy decision; it must be enforced where the data lives or it isn't really enforced. Pure backing-store-as-database (Option A) makes hobbyist single-tenant deployments needlessly heavy and complicates federation: a federated server may host many namespaces and "one SQLite per namespace" stops scaling well before "one schema per namespace" does.

The split makes the *contract* uniform (store API is namespace-parameterised; cross-namespace return is impossible by construction) while making the *implementation* deployment-appropriate. Resolving the namespace in middleware, but enforcing in the store, keeps the middleware chain's role consistent (context decoration) and locates the security-critical check at the data layer where it cannot be accidentally bypassed. Aligns cleanly with the federation-scope decision: namespace and `server-id` are orthogonal slots — `server-id` distinguishes hosts in a federation; `namespace` distinguishes tenants within a host. Trade-off accepted: store implementations carry slightly more complexity (must support both modes, or declare which they support) and the namespace-resolver middleware adds one mandatory chain element.

## Consequences
- Positive: No "missing filter = data leak" failure mode. Cross-namespace return is structurally impossible at the port level.
- Positive: Single-tenant demos get `mode: shared` with `namespace: default` and effectively don't notice the system exists.
- Positive: Multi-tenant SaaS deployments can choose `mode: isolated` for hard separation without changing application code.
- Positive: Federation-aware: `<server-id>` and `<namespace>` are independent slots; a federated message envelope is `(server, namespace, channel, seq)`.
- Negative: Every store implementation must implement the namespace contract (no namespace-unaware stores). Conformance suite enforces this.
- Negative: The `mode` knob is a deployment-time concern; users must understand the trade-off (operational simplicity vs. blast-radius isolation).
- Negative: The namespace-resolver middleware is mandatory in the default chain — removing it breaks routing. Document as required.
- Spec impact: `spec/namespacing.md` defines namespace as a first-class concept, default `default`, ASCII identifier rules, and the orthogonality with `server-id`. `ports/store.md` requires every read/write API to take a namespace argument and forbids cross-namespace returns; `mode` is a store construction parameter (not a runtime field). `spec/middleware.md` defines the `namespace_resolver` reference middleware and places it before auth in the default chain (so auth can scope credentials per-namespace). `spec/envelope.md` reserves `namespace` field. Conformance suite adds a "namespace isolation" axis with cross-namespace leak attempts.

## Open questions for follow-up
- Namespace creation/lifecycle: who can create a namespace, and through which verb? Likely a privileged admin operation; defer to admin-API colocation decision.
- Whether namespace deletion is supported in v1, and if so what happens to in-flight messages and subscribers. Recommend "v1: namespaces are create-only; deletion is post-v1 with a documented eviction protocol."
- Interaction with replay (Q3): does `replay_policy: subscriber` implicitly scope to the principal's namespace? Yes — namespace is resolved before auth, so all downstream policy is namespace-scoped by construction. Document explicitly.
- Default-namespace migration story: deployments that start single-tenant and later split — recommend a one-shot retag tool, defer to post-v1.
- Postgres schema vs. database vs. row-level-security as the `isolated` mode default — pin during reference-implementation work; recommend schema as the default for operational reasons.
