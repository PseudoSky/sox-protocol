# ADR 0004 — SOX Protocol Plugin Architecture

**Status:** Accepted — 2026-05-01
**Deciders:** SOX Protocol architecture working group
**Supersedes:** —
**Related:** `docs/adr/0003-extensibility-mechanism.md`, `.workflow/plans/plugin-architecture/analysis.md` §7, `.workflow/plans/plugin-architecture/suggestions-v2.md`

## Status: Accepted (2026-05-01)

## Context

ADR 0003 ratified the *extensibility mechanism* — a hybrid model in which middleware is the load-bearing primitive and hooks are an observation-only sugar layer. ADR 0003 left several follow-on questions explicitly open ("Open questions": versioning, error propagation, hook execution model, cross-impl plugin distribution). This ADR closes those questions for v1 by promoting a concrete *plugin contract* to normative status.

Two reviews drove the decisions below: the second-pass optimizer review (`suggestions-v2.md`) and three research findings dispatched to `workflow-researcher` (`~/.claude/plugins/workflow/memory/research/{plugin-manifest-formats,plugin-taxonomies,plugin-protocol-versioning}/`). Together they surveyed Backstage, Envoy/xDS, OPA, gRPC, VS Code, Babel, ESLint, Terraform, NestJS, Spring AOP, Fastify, Hapi, and Strapi. The convergent findings — particularly NestJS issue #541 (production usage collapses to two of five kinds), Spring AOP's "least-powerful-advice" doctrine, and Backstage RFC 18372's `apiVersion`/`kind`/`metadata`/`spec` envelope — supplied most of what follows.

This ADR documents a *candidate* contract: the B1 freeze. Conformance fixtures authored in B2 (`plugin-spec-polish`) may force minor amendments — that is the design loop functioning, not a process failure.

## Decision

The decisions below are normative for SOX Protocol v1.

### 1. Plugin kind taxonomy: 4 kinds in 2 axes

Per analysis §7.1 (ratified §7.8.1):

- **Wire axis:** `interceptor` (`async (ctx, next) -> response`), `transformer` (`async (ctx) -> ctx'`).
- **Lifecycle axis:** `provider` (factory with `on_startup`/`on_shutdown`), `hook` (observation-only, `async (immutable_ctx) -> None | HookDecision`).

The original five-kind proposal (§2.1) included a separate `guard` kind; it collapses into `interceptor`. Spring AOP's twenty-year "least-powerful-advice" doctrine and NestJS's documented production-collapse pattern (issues #541, #9269, #337) both show that within one axis distinct kinds without distinct expressive power decay into ceremony. A guard is an interceptor that returns deny via `ShortCircuitResponse`.

`interceptor` carries two capability flags: `observe_only` and `may_short_circuit`. Orthogonality is enforced — `observe_only: true` combined with `may_short_circuit: true` is a startup `plugin_capability_conflict` error. The flag set is capped at 2–4 flags for v1 to resist the monotone growth that has plagued VS Code's `enabledApiProposals`.

**Migration:** any earlier "kind: guard" thinking maps to `kind: interceptor` with `may_short_circuit: true, observe_only: false`.

### 2. Plugin manifest format

Per analysis §7.2: a Backstage-style envelope (`apiVersion: sox.dev/v1`, `kind: SoxPlugin`, `metadata.{id, version}`, `spec.{...}`). The `id` is a reverse-DNS string (`org.example.sox-jwt-auth`), ASCII-only or NFC-normalized.

Five universal fields, drawn from the cross-language convergence finding: `id`, `version`, `kind`, `capabilities`, `applies_to`.

**Entry-point hints are explicitly OUT of the manifest body.** They live in language-specific package metadata: Python `pyproject.toml [project.entry-points."sox_protocol.plugins"]`, Node `package.json#sox` plus `exports`. Backstage, Envoy, and OPA all made the same choice; it is the only way to keep the manifest genuinely language-neutral.

`signatures: []` is reserved from v1.0 (empty list permitted). v1.x adds optional manifest-hash pinning; v2.0 considers in-band verification. The OPA bundle precedent shows the retrofit cost of adding signing later is high; the reservation is cheap.

### 3. Protocol-version negotiation

Per analysis §7.3 (ratified §7.8.3): a single `protocol_version` semver-range field. The wire form is **dual**: PEP 440 canonical (`>=1.0,<2.0`) is the primary form; npm caret (`^1.0.0`) is documented as informative-but-supported. Both must parse on both runtimes. Pre-release markers normalize between PEP 440 (`1.0.0a1`) and npm (`1.0.0-alpha.1`).

Negotiation is **boot-time hard-reject**. Lazy refusal is forbidden; Envoy's xDS API_VERSIONING.md establishes that lazy refusal is acceptable only when the API surface is too large to enumerate, which is not SOX's case. The refusal envelope is structured: `{error_code: "plugin_protocol_version_mismatch", plugin_id, plugin_declares, host_supports, remediation}`.

### 4. Discovery mechanism

- **Python:** `importlib.metadata.entry_points(group="sox_protocol.plugins")`.
- **Node:** top-level `"sox": "./sox-plugin.yaml"` key in `package.json`, scanned at startup.
- **In-tree:** `register_plugin(name, factory)` for composition and tests.

Production deployments **MUST** pass an explicit `--allow-plugins ID,...` CLI flag. `load_entry_points` is a code-execution boundary; an unconstrained allowlist is a supply-chain hazard (analysis §7.5 risk #1). The error taxonomy distinguishes the failure modes operators actually need to triage: `plugin_not_allowed` (config typo), `plugin_not_found` (deployment), `plugin_manifest_invalid` (build), `plugin_protocol_version_mismatch` (compat), `plugin_capability_conflict` (manifest), `plugin_ordering_cycle` (ordering).

### 5. Failure semantics per kind

Per analysis §7.5 risk #2 (ratified §7.8.6):

- `interceptor` exception → `internal_error` envelope.
- `transformer` exception → `validation_failed` envelope.
- `provider` startup exception → fail-fast; host refuses to start.
- `hook` exception → environment-controlled via `SOX_HOOK_FAILURE_MODE={swallow|alarm|raise}`. **Production default is `alarm`**: counter increment plus structured log, hook still does not block. CI/dev default is `raise`. Silent swallow is *not* the production default; the env-var is normative.

This explicitly closes ADR 0003's "Error propagation" open question.

### 6. Ordering algorithm

Per analysis §7.5 risk #3: `must_run_before` / `must_run_after` are resolved by **stable Kahn's topological sort** with **lexicographic plugin-id tie-break**. A cycle is a startup `plugin_ordering_cycle` error naming the participating ids. Order is computed once at startup and cached. Determinism across implementations is a normative requirement so that conformance fixtures can assert chain shape.

### 7. Configuration

Per analysis §7.5 risk #6 (ratified §7.8.4): **environment variables only for v1.** A `sox.yaml` config file is deferred to v1.x. Canonicalization: the reverse-DNS plugin id `org.example.sox-jwt-auth` becomes `SOX_PLUGIN_ORG_EXAMPLE_SOX_JWT_AUTH_<KEY>` — `.` and `-` replaced with `_`, uppercased. Env-vars carry zero schema-evolution cost; a config file is a future quality-of-life add, not a blocker.

### 8. Observability

Per analysis §7.5 risk #7: each dispatch produces a structured `metadata["pipeline_trace"]` array. Per-record fields: `{plugin_id, kind, started_at, finished_at, verdict, error_code?, correlation_id}`. `correlation_id` is echoed from the request envelope's frozen `MiddlewareContext.correlation_id` field. OTel spans are deferred to v1.x — the structured array is sufficient for `grep` and CI assertions in v1.

### 9. v1 limitations spec'd defensively

Per analysis §7.5 risk #4: composition is **static at startup** in v1. Two normative spec notes follow:

- Implementations MUST NOT depend on stable Pipeline identity across reloads.
- **Plugin authors MUST NOT cache references to host-provided objects (registries, contexts, config) across plugin lifetime.**

v2.x may relax this to support add/remove. Locking in static-only forever would be a spec hazard; documenting the limitation while reserving the relaxation path is the cheap-now/expensive-later tradeoff inverted.

### 10. B1 framing

This engagement produces a *candidate* contract. B2 conformance fixtures may surface issues that force minor B1 amendments — Postel's rough-consensus-and-running-code, not a defect.

## Consequences

### Positive

- Closes four of ADR 0003's six open questions (versioning, error propagation, hook execution model, chain introspection via `pipeline_trace`).
- Single-axis kind taxonomy with capability flags lets future kinds enter without invalidating existing manifests.
- Backstage/Kubernetes-shaped envelope is familiar to operators; the `apiVersion: sox.dev/v1` pattern lets the schema evolve without breaking content versions.
- Boot-time refusal plus deterministic ordering means conformance suites can assert chain shape statically.
- Reserved `signatures: []` keeps the supply-chain story open without paying the v1 cost.

### Negative

- **Two-file authoring story** for plugin authors (manifest + language-specific package metadata). The single-file alternative was rejected per §7.8.2 because it leaks language semantics into the language-neutral document.
- **Dual wire form for `protocol_version`** asks every parser to handle both PEP 440 and npm caret. The translation is small but real.
- **`SOX_HOOK_FAILURE_MODE` proliferates env-var surface.** Acceptable given the alternative is silent swallow, which is the worse failure mode.
- **No hot reload in v1** is a real ergonomic loss for development. Mitigated by the static-only spec note that preserves the relaxation path.

### Neutral

- Capability flags will accrete; the 2–4 cap is a cultural commitment more than a mechanical one.
- The `--allow-plugins` allowlist adds a deploy-time step. Production operators are already comfortable with this shape (Envoy, OPA).

## Alternatives Considered

- **A. Five-kind taxonomy with separate `guard`** (original §2.1). Rejected per §7.1: NestJS production data and Spring AOP doctrine both show distinct kinds within one axis collapse to whichever is most expressive.
- **B. Single-file manifest with embedded entry-point.** Rejected per §7.8.2: simpler for authors, but bakes language semantics into the language-neutral document. Backstage, Envoy, and OPA all separate these layers.
- **C. Multi-axis versioning (semver + capability matrix).** Rejected per §7.3: Kubernetes' 3-D compatibility cube is the documented anti-pattern.
- **D. Lazy / per-call protocol-version refusal.** Rejected per §7.3: only acceptable when API surface is too large to enumerate (gRPC), which is not SOX.
- **E. `sox.yaml` config schema in v1.** Rejected per §7.5 risk #6: introduces new artifact, schema, validator, and migration story without v1 blocker justification.
- **F. Silent-swallow hook failure as production default.** Rejected per §7.8.6: fails-quiet is the documented worst-case observability mode; `alarm` is the minimum responsible default.
- **G. Pure-runtime plugin discovery without allowlist.** Rejected per §7.5 risk #1: `load_entry_points` is a code-execution boundary; production needs explicit consent.

## References

- ADR 0003 — `docs/adr/0003-extensibility-mechanism.md` (predecessor; mechanism vs contract)
- Analysis — `.workflow/plans/plugin-architecture/analysis.md` §7 (revisions, 2026-05-01) — authoritative decision set
- Optimizer second pass — `.workflow/plans/plugin-architecture/suggestions-v2.md`
- Research — `~/.claude/plugins/workflow/memory/research/plugin-manifest-formats/cross-language-convergence.md`
- Research — `~/.claude/plugins/workflow/memory/research/plugin-taxonomies/multi-kind-vs-unified-middleware.md`
- Research — `~/.claude/plugins/workflow/memory/research/plugin-protocol-versioning/version-declaration-and-negotiation.md`
- Backstage RFC 18372 — `catalog-info.yaml` envelope (`apiVersion`/`kind`/`metadata`/`spec`)
- Envoy `API_VERSIONING.md` — boot-time hard-reject; permanent-no-field-removal
- OPA bundles — signed-bundle precedent for `signatures: []` reservation
- Spring AOP — least-powerful-advice doctrine
- NestJS issues #541, #9269, #337 — production usage collapse
- Fastify `fastify-plugin` — encapsulation and registration shape
- PEP 440 — canonical wire form for `protocol_version`
