# ADR 0003 — Extensibility Mechanism

**Status:** Accepted — 2026-04-30
**Deciders:** SOX Protocol architecture working group
**Supersedes:** —
**Related:** `docs/decisions/schema-validation-layer.md`, `docs/decisions/namespace-isolation-layer.md`, `docs/decisions/admin-api-colocation.md`, `docs/DESIGN.md` §runtime-adapter

## Status: Accepted (2026-04-29)

## Context

SOX Protocol must let third parties extend the behaviour of a server without forking core. Multiple already-resolved decisions assume an extension surface exists:

- **Identity verification** must intercept every request and short-circuit *before* any backing-store read or write — a leak here is a confused-deputy bug.
- **Schema validation** (`docs/decisions/schema-validation-layer.md`) is committed to be a removable, tree-shakeable validator that runs *after* auth and *before* persistence.
- **Namespace resolution** (`docs/decisions/namespace-isolation-layer.md`) decorates the request context with the active tenant before auth runs.
- **Rate limiting** must be able to count, advise, or refuse — i.e., observe and short-circuit.
- **Tracing / observability** must inspect requests and responses without altering them.
- **Audit logging** is observation-only but must run after the canonical decision is known.
- **Future:** ACL evaluation, idempotency dedup, content rails, PII filters.

Three mechanisms are on the table:

1. **Hooks** — pre/post events fire on each verb. Listeners can inspect the request (pre) or the result (post) and may *short-circuit* by returning a typed decision (`deny`, `defer`, `allow`). Listeners cannot mutate the request envelope or the response. This is the model used by Claude Code's runtime-adapter hook script (`docs/DESIGN.md` §runtime-adapter).
2. **Middleware** — a chain of components, each receiving `(request, next)` and returning a response. Each link may inspect, mutate request and/or response, short-circuit, or pass through. Established pattern in Django, Express, ASGI, gRPC interceptors.
3. **Hybrid** — observation/short-circuit handled by hooks; transformation (envelope rewriting, schema validation, tracing-context injection, namespace decoration) handled by middleware.

The constraint set already filed by sibling decisions is decisive. `schema-validation-layer.md` calls out an "auth-as-middleware" posture; `namespace-isolation-layer.md` requires a `namespace_resolver` *middleware* that decorates the request context before auth — pure-hook listeners cannot decorate context because they cannot mutate the request. The use cases on the table therefore *require* mutation, not only observation.

The spec-vs-implementation rule (the spec defines the *interface* — inspect, mutate, short-circuit — and reference impls pick the mechanism) was previously accepted but is rejected here as insufficient: extension authors registering against two different runtimes need a single contract or their extensions are not portable. The interface must be normative.

## Decision

**Adopt the hybrid model. Middleware is the primary extension mechanism; hooks are a thin observation-only surface defined as a derived special case.**

Concretely:

1. **Middleware is the load-bearing primitive.** The spec defines a `Middleware` port: `async fn handle(request, next) -> response`. A middleware may (a) inspect the request, (b) attach context fields to the request *before* calling `next`, (c) call `next` and inspect / replace the response, (d) short-circuit by returning a response without calling `next`. Mutation is scoped — middleware may set context fields and replace the *response envelope*, but may not rewrite the message body except where a specific middleware (e.g., schema validator, redaction) is explicitly authorised by the chain configuration.
2. **The default chain is normative.** The reference deployment ships a fixed default order: `tracing → namespace_resolver → auth → rate_limit → schema_validator → idempotency → store_dispatch → audit_log`. Conforming implementations MUST support this order and MUST allow operators to insert / remove / replace links. Each link is a separately-named, independently-removable middleware with a documented contract.
3. **Hooks are a pre/post observer surface defined on top of middleware.** The spec defines `pre_<verb>` and `post_<verb>` events. A hook MAY return a deny / defer decision (short-circuit allowed). A hook MAY NOT mutate the request or response. Hooks are sugar: the reference impl ships a `hook_dispatcher` middleware which reads registered hooks and fans them out around the rest of the chain. Plugin authors who only need observation register hooks; authors who need transformation write a middleware.
4. **Registration is declarative and out-of-tree.** A plugin ships a Python entry point (or an equivalent declarative manifest in non-Python impls) naming its middleware/hook factory. Servers load the configured plugin list at startup. No core fork is required.
5. **The interface is normative; the implementation is not.** The wire-level contract (envelope shape, decision verbs, error codes) is part of the spec. The host language's concrete `Middleware` type signature is per-impl, but every impl MUST be expressible as the four operations in (1).

### Why hybrid, not pure middleware

A pure-middleware spec would force every observability plugin to learn the chain protocol, which is more surface than they need and makes "I just want to log every send" a 40-line affair. Hooks-as-sugar gives a low-floor entry point without splitting the conceptual model: a hook is a middleware that elected not to mutate.

### Why hybrid, not pure hooks

Pure hooks cannot satisfy the requirements already filed by sibling ADRs. Namespace resolution must decorate request context; schema validation must be a removable transformer; tracing must inject correlation IDs into the outbound envelope. None of these are observation. Choosing hooks-only would force these concerns back into core, which is exactly the "no forking" constraint we are trying to avoid.

## Alternatives considered

- **A. Pure hooks (Claude-Code-style).** Rejected: cannot mutate request context, so namespace resolution and tracing-context injection have no home outside core. Forces sibling ADRs to be re-litigated.
- **B. Pure middleware.** Rejected as the *sole* surface: high floor for observation-only plugins; "log every send" should not require understanding the chain protocol. Adopted as the *primary* surface with hooks layered on top.
- **C. Spec stays implementation-agnostic; reference impl picks.** Rejected: produces non-portable plugins. A plugin written for the Python reference impl's middleware API would not run on a Rust impl that picked hooks. Inter-impl plugin portability is a stated goal.
- **D. Aspect-oriented / decorator-only model.** Rejected: too implicit, hard to reason about chain order, and not expressible across host languages with different metaprogramming capabilities.
- **E. Event bus (publish/subscribe, no return value).** Rejected: cannot short-circuit, so auth and rate-limit cannot live there. Useful internally for fan-out audit but insufficient as the extension primitive.

## Consequences

### Positive

- Single normative contract across implementations: a middleware-style plugin written against the spec is portable between Python, Rust, and Go reference impls (subject to host-language binding).
- Sibling ADRs (`schema-validation-layer`, `namespace-isolation-layer`) compose without contradiction: each names its middleware position in the default chain.
- Hooks remain available as a low-floor surface for the common "I want to observe sends" case, matching Claude Code's runtime-adapter ergonomics.
- Operators can disable, reorder, or replace links — the chain is configuration, not code.
- Auth's short-circuit obligation is structurally satisfied: auth is a middleware that returns `Unauthorized` without calling `next`; no backing-store call is reachable.

### Negative

- **More spec surface.** The spec must define the chain protocol, the default order, the per-link contract, and the hook fan-out semantics. This is the most consequential trade-off we accept: we are paying with spec complexity to buy plugin portability and to honour the constraints that sibling ADRs already filed.
- **Footgun: chain misconfiguration.** Removing `auth` is technically possible and will silently make the server open. Mitigation: ship a conformance test that asserts the default chain refuses an unauthenticated `send`; document a "minimum viable chain" with auth, namespace_resolver, store_dispatch as non-removable in the reference deployment.
- **Two registration paths to document.** Hook authors and middleware authors follow different registration shapes. Mitigation: document hooks as the entry point, middleware as the escalation, with a single decision tree ("do you need to mutate? → middleware").
- **Per-link ordering becomes load-bearing.** Inserting a new middleware in the wrong position can break invariants (e.g., rate-limit before auth would count anonymous requests). Mitigation: each middleware declares `must_run_after` / `must_run_before` constraints that the loader validates at startup.
- **Performance.** A chain of N middlewares adds N function frames per request. Acceptable for v1's scale targets; revisit if profiling shows it dominates.

## Open questions

- **Async semantics.** Is the chain `async` end-to-end, or does the spec allow sync middleware? Recommend async-only in the contract; sync impls wrap with an executor. Pin in `spec/middleware.md`.
- **Error propagation.** Does a middleware that throws abort the chain with a typed error, or is it caught and converted to a deny? Recommend abort-with-typed-error and a top-level error middleware that maps exceptions to envelope error codes. Pin in `spec/errors.md`.
- **Hook execution model.** Are pre/post hooks fired in registration order or sorted? Recommend registration-order with a `priority: int` override; document deterministic tie-breaking.
- **Cross-impl plugin distribution.** A Python middleware is not a Rust middleware. Does the spec define a wasm-or-process boundary for cross-language plugins? Defer to a later ADR; v1 ships native-only plugins per impl.
- **Chain introspection.** Should a server expose its active chain via the admin API? Recommend yes, gated by admin auth — useful for debugging and for the conformance suite. Confirm with `admin-api-colocation.md`.
- **Versioning.** When the chain protocol evolves (e.g., adds a new context field), how do older middleware coexist? Recommend additive-only context with a declared minimum protocol version per middleware. Defer concrete migration semantics.

## Spec impact

- **New:** `spec/middleware.md` — chain protocol, default order, per-link contract template, ordering constraints.
- **New:** `ports/middleware.md` — host-language-neutral port definition.
- **New:** `spec/hooks.md` — hooks as observer surface, fan-out semantics, decision verbs.
- **Updated:** `spec/extensibility.md` — index pointing at middleware (primary) and hooks (sugar).
- **Updated:** `spec/conformance.md` — chain default-order test, "removing auth opens the server" detection test, namespace-resolver-must-run-before-auth ordering test.
