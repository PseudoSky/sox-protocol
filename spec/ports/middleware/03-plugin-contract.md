<!-- SPDX-License-Identifier: Apache-2.0 -->
# SOX Protocol Plugin Contract

**Version:** 1.0
**Status:** candidate (2026-05-01)
**Scope:** Language-neutral. Normative for all SOX Protocol v1 host implementations and plugin authors. Transport-specific concerns and the runtime composition root are out of scope.

**Related:**
- `docs/adr/0004-plugin-architecture.md` — companion ADR (all numbered decisions below correspond directly)
- `docs/adr/0003-extensibility-mechanism.md` — predecessor ADR (hybrid middleware + hooks model)
- `spec/schemas/sox-plugin.schema.json` — machine-readable schema this contract corresponds to
- `spec/ports/middleware.md` — predecessor single-file middleware spec (B2 restructure pending)

---

## 1. Purpose & Scope

The SOX Protocol middleware model (ADR 0003) established that middleware is the load-bearing primitive and hooks are an observation-only sugar layer. ADR 0003 deliberately left several follow-on questions open: versioning, error propagation per kind, hook execution model, and chain introspection. This document closes those questions for v1.

A **plugin contract** is the normative agreement between a plugin author and a SOX host. It specifies:

- The four plugin kinds and the precise function signature each kind exports.
- The capability flags a plugin declares and how the host validates them.
- The failure behaviour the host MUST exhibit when a plugin raises an exception, returns an unexpected type, or declares a contradictory capability set.
- The algorithm the host MUST use to order plugins at startup.
- The supply-chain allowlist the host MUST enforce in production.
- The configuration namespace the host MUST derive from a plugin's identifier.
- The observability record the host MUST append to every dispatch response.
- The v1 static-composition limitations plugin authors MUST respect.

**In scope:** `kind: interceptor`, `kind: transformer`, `kind: provider`, `kind: hook`. The plugin manifest schema (`spec/schemas/sox-plugin.schema.json`) is the machine-readable companion to this document; citations below refer to it as "the schema."

**Out of scope:** transport-specific middleware (HTTP body parsing, stdio framing); the runtime composition root (how the host assembles the Pipeline object); the directory restructure of `spec/ports/middleware/` (deferred to `plugin-spec-polish`, engagement B2); conformance fixture authorship (B2); OTel span emission (deferred to v1.x).

This document corresponds to ADR 0004 decisions 1 through 9. Where this document and ADR 0004 conflict, ADR 0004 is authoritative. Where ADR 0004 is silent, this document is authoritative.

---

## 2. Plugin Kinds — 4-Kind 2-Axis Taxonomy

SOX v1 defines exactly four plugin kinds, organised on two axes. ADR 0004 §1 ratified this taxonomy after reviewing NestJS production-collapse data (issues #541, #9269, #337) and Spring AOP's twenty-year "least-powerful-advice" doctrine. The fifth kind from the original five-kind proposal — a separate `guard` kind — is subsumed by `kind: interceptor` with `may_short_circuit: true`. See §2.3 for the explicit migration table.

The `plugin_kind` field in `spec/schemas/sox-plugin.schema.json` is an enum over exactly `["interceptor", "transformer", "provider", "hook"]`. A manifest declaring any other value MUST be rejected at startup with `plugin_manifest_invalid`.

### 2.1 Wire-Axis Kinds

Wire-axis plugins are invoked per-message, inline in the Pipeline dispatch path.

#### 2.1.1 `kind: interceptor`

**Contract:** `async (ctx: MiddlewareContext, next: Callable) -> DispatchResponse`

The interceptor wraps the downstream chain. It receives the full mutable `MiddlewareContext` and a `next` callable representing everything downstream (including the store dispatch). The interceptor MAY call `next` exactly once, zero times (short-circuit), or — only if declared `observe_only: true` — call `next` and then inspect the response without modifying it.

Calling `next` more than once in a single dispatch is a contract violation. The host SHOULD detect and log this condition; behaviour of the downstream chain after a second `next` call is undefined.

An interceptor MAY raise `ShortCircuitResponse` instead of calling `next`. When `ShortCircuitResponse` is raised, the host propagates it as the final response for that dispatch. This is the intended mechanism for authentication denial, rate-limit rejection, and any other early-exit decision. It is not an error condition; the host MUST NOT log it as one.

This kind subsumes the originally-considered `guard` kind. A guard is an interceptor that never calls `next` when it denies — it raises `ShortCircuitResponse`. Spring AOP's "least-powerful-advice" doctrine holds that distinct kinds within one axis add ceremony without adding expressive power once one kind is strictly more powerful than the others. `interceptor` is that strictly-more-powerful kind on the wire axis.

See `spec/schemas/examples/sox-plugin.example.interceptor.yaml` for a concrete `kind: interceptor` manifest (JWT auth, `may_short_circuit: true`).

#### 2.1.2 `kind: transformer`

**Contract:** `async (ctx: MiddlewareContext) -> MiddlewareContext`

The transformer receives the mutable context and returns a (potentially new) context. It operates exclusively pre-dispatch — before `next` would be called by any interceptor. It MUST NOT call any downstream callable; the host does not provide a `next` argument to a transformer.

A transformer MUST NOT produce a `DispatchResponse`. It returns a `MiddlewareContext` or raises an exception. If validation logic rejects the input, the transformer MUST raise `ValidationError`; the host catches this and returns a `validation_failed` envelope (see §3.2).

Because a transformer cannot call `next` and cannot return a response, it cannot short-circuit the chain. A transformer that attempts to short-circuit via side-channel (for example, by raising `ShortCircuitResponse`) is a contract violation; the host MUST treat the raised exception as an uncaught error per §3.2.

See `spec/schemas/examples/sox-plugin.example.transformer.yaml` for a concrete `kind: transformer` manifest (schema-strict body validator).

### 2.2 Lifecycle-Axis Kinds

Lifecycle-axis plugins are not invoked per-message. They interact with the host's startup and shutdown sequence.

#### 2.2.1 `kind: provider`

**Contract:** factory `() -> Resource`; optional hooks `on_startup(ctx: ServerContext) -> None` and `on_shutdown(ctx: ServerContext) -> None`.

A provider is a resource factory. The host calls the factory once at startup to obtain the resource object and registers it under the capability strings declared in `plugin_capabilities`. Other plugins that declare a matching capability string in their `requires` field receive the resource handle via the host's dependency-injection mechanism.

Lifecycle: server-singleton by default. A provider MAY opt into request-scoped provisioning by declaring `lifecycle: request` in its manifest spec (v1.x; reserved, not enforced in v1.0).

`on_startup` is called after the factory but before the host begins accepting requests. `on_shutdown` is called when the host initiates graceful shutdown. Both are optional. If `on_startup` raises, the host MUST fail-fast (see §3.3). If `on_shutdown` raises, the host MUST log the error and continue shutdown.

`applies_to` is irrelevant for providers. Including it in a provider manifest is permitted by the schema but the host MUST ignore it. See `spec/schemas/examples/sox-plugin.example.provider.yaml`.

#### 2.2.2 `kind: hook`

**Contract:** `async (ctx: ImmutableMiddlewareContext) -> None | HookDecision`

A hook receives an immutable view of the context. It MUST NOT mutate the request payload, response, or any field of the context. The host MUST enforce immutability; a hook that attempts mutation raises a runtime error which the host handles per §3.4.

Hooks are classified as pre-hooks (invoked before dispatch) or post-hooks (invoked after dispatch). The classification is declared in the plugin manifest's `applies_to` phase field (v1.x; in v1.0, all hooks are registered as pre-hooks unless the host's API provides explicit ordering).

A pre-hook MAY return `HookDecision(action='deny', error=...)` to short-circuit the pipeline. The host MUST honour this decision as equivalent to a `ShortCircuitResponse` raised by an interceptor. A post-hook's return value is ignored by the host.

Hooks are the primary extension point for observability, audit, and tracing plugins. Because they receive an immutable context, they cannot affect the semantics of the dispatch — only observe them.

### 2.3 Capability Flag Rules

Capability flags are declared in `plugin_capabilities` as single-key objects alongside free-form capability strings. Two boolean flags are defined for v1; no others are normative.

**`observe_only`** (boolean, interceptor-only): When `true`, the plugin promises never to mutate the context and never to short-circuit. The host MAY enforce this at runtime by wrapping the plugin's return path with an assertion. A plugin that declares `observe_only: true` and then returns a `ShortCircuitResponse` at runtime is a contract violation; the host MUST log the violation and convert the response to an `internal_error` envelope (§3.1). For static-inferable violations (e.g. plugin source analysis, test environments), the host MAY refuse to load the plugin at startup.

**`may_short_circuit`** (boolean, interceptor-only): When `true`, the plugin may return a response without calling `next()`, bypassing the remaining chain. This is the canonical declaration that replaces `kind: guard`.

**Orthogonality constraint (normative):** `observe_only: true` combined with `may_short_circuit: true` is a logical contradiction — a plugin cannot simultaneously promise never to short-circuit and declare that it may. This combination is a `plugin_capability_conflict` startup error. The schema (`spec/schemas/sox-plugin.schema.json`) encodes this via an `if/then` constraint; the host MUST also assert it at runtime independent of schema validation.

**Flag-set cap:** The set of defined boolean flags is capped at 2–4 for v1. New flags MUST NOT be added without a companion ADR. This cap exists to resist the monotone flag-creep that NestJS's `enabledApiProposals` and VS Code's API proposals list have demonstrated.

**Migration table — from former `kind: guard` to v1 contract:**

| Former declaration | v1 equivalent |
|---|---|
| `kind: guard` | `plugin_kind: interceptor` |
| _(implicit deny-only)_ | `may_short_circuit: true` |
| _(implicit no-observe)_ | `observe_only: false` |

Any plugin previously authored with a `kind: guard` concept MUST be re-declared as shown above. The host MUST reject a manifest with `plugin_kind: guard` as `plugin_manifest_invalid` (since `guard` is not a valid enum value in the schema).

### 2.4 Capability Strings — `requires` and `provides`

`requires` and `provides` (via `plugin_capabilities`) are arrays of capability strings. Capability strings identify what a plugin needs or supplies, without naming specific plugin identifiers. This decoupling allows the host to satisfy a dependency with any loaded plugin that declares the matching capability, not a specific named one.

Capability string format: `<namespace>.<feature>` as the key, with an optional version-range or label value (e.g. `auth.method: "jwt-bearer"`, `rate_limit.backend: ">=1.0"`, `identity.registry`). Namespaces SHOULD be reverse-DNS or well-known SOX namespaces. Free-form keys are permitted; stability is the plugin author's responsibility.

The host resolves `requires` entries against the `plugin_capabilities` declarations of all loaded plugins at startup. If a required capability is not provided by any loaded plugin, the host MUST refuse to start with `plugin_requirement_unmet`, naming the unsatisfied capability string and the plugin that declared the requirement.

Capability string matching is exact-string by default in v1. Version-range matching in `requires` (e.g. `rate_limit.backend: ">=1.0"`) is a v1.x extension; v1 hosts MAY implement it as a best-effort match.

---

## 3. Failure Semantics

Failure semantics are normative per kind. The host MUST NOT allow a plugin exception to propagate unhandled to the caller.

### 3.1 Interceptor Failure

**Uncaught exception:** The host catches any exception not of type `ShortCircuitResponse`. It MUST log the exception with the `correlation_id` from `MiddlewareContext.correlation_id` (a frozen field; see §8). It MUST return an `internal_error` envelope conforming to `spec/envelopes/sox-error.schema.json`. The downstream chain is not called.

**`ShortCircuitResponse`:** Not an error. The host propagates it as the dispatch response. Pipeline trace verdict is `"short_circuit"` (§8).

**`observe_only` contract violation:** If a plugin declared `observe_only: true` returns a `ShortCircuitResponse`, the host MUST log a contract-violation warning including the plugin id and MUST convert the response to an `internal_error` envelope. The plugin is not unloaded at runtime (v1); however, a host operating in strict mode MAY refuse to load such a plugin at startup if static analysis reveals the violation.

### 3.2 Transformer Failure

**Uncaught exception (not `ValidationError`):** The host catches, logs with `correlation_id`, and returns an `internal_error` envelope.

**`ValidationError`:** The host catches and returns a `validation_failed` envelope conforming to `spec/envelopes/sox-error.schema.json`. The `validation_failed` error code signals a caller-correctable input error, distinct from an internal fault.

Because transformers operate pre-dispatch, a transformer failure MUST NOT have any downstream side-effects. The host MUST NOT proceed to wire-axis dispatch after a transformer raises.

### 3.3 Provider Failure

**`on_startup` exception:** Fail-fast. The host MUST log the exception, emit a structured error record (including `plugin_id` and `error_code: "plugin_startup_failed"`), and exit with a non-zero status code. The host MUST NOT attempt to continue startup with a partially-initialised provider. This is the Spring "context refresh failed" pattern; it is intentional. Silent degradation of startup failures produces systems that appear healthy while missing critical resources.

**`on_shutdown` exception:** Non-fatal. The host MUST log the exception and continue shutdown. No recovery semantics are defined; the host SHOULD drain remaining shutdown hooks regardless.

**Factory exception:** Treated as an `on_startup` exception. Fail-fast applies.

### 3.4 Hook Failure

Hook failure handling is environment-controlled via the `SOX_HOOK_FAILURE_MODE` environment variable. The host MUST honour this variable. Three values are defined:

| Value | Behaviour | Default for |
|---|---|---|
| `swallow` | Exception is silently discarded. No log entry, no counter increment. Explicit opt-in only. | — |
| `alarm` | Exception is caught; a structured log entry is emitted at `ERROR` level including `plugin_id`, `hook_phase`, `correlation_id`, and exception message; an internal counter (`sox.hook.failure_count`) is incremented. The hook does NOT block the pipeline. | **Production** (`SOX_ENV=production` or unset) |
| `raise` | Exception is caught and re-raised as `internal_error`, propagating to the caller. | **CI / development** (`SOX_ENV=development`, `SOX_ENV=ci`) |

When `SOX_HOOK_FAILURE_MODE` is absent, the host MUST default to `alarm`.

CI test suites SHOULD set `SOX_HOOK_FAILURE_MODE=raise` so that hook exceptions surface immediately rather than being absorbed. A hook author who tests only in `alarm` mode will not discover failures until production, where the `alarm` mode provides a metric signal but does not fail the request.

The rationale for `alarm` as the production default rather than `swallow` is operational: `swallow` is how observability plugins silently mask production incidents. Datadog's APM tracer has documented multi-year issues where buggy instrumentation hooks consumed exceptions from application code, leaving operators with only "metrics look weird" as a signal. `alarm` retains the non-blocking contract of hooks while ensuring the failure is observable.

`swallow` is retained as an explicit opt-in for scenarios where a hook's failure is genuinely inconsequential and the operator has audited this. It MUST NOT be the default.

---

## 4. Ordering Algorithm

### 4.1 Topological Sort

`must_run_before` and `must_run_after` fields in the manifest declare ordering constraints. Both fields accept plugin ids or capability strings as values. At startup, the host MUST resolve capability strings to the set of loaded plugins that provide that capability, then build a directed acyclic graph (DAG) over all loaded plugins.

The host MUST execute a **stable Kahn's topological sort** over this DAG to determine the pipeline execution order. Specifically:

1. Compute in-degree for every node.
2. Enqueue all nodes with in-degree zero, sorted in **lexicographic order by plugin id** (UTF-8 byte order; the schema regex constrains plugin ids to ASCII, so this is byte-equivalent to ASCII lexicographic order).
3. Dequeue in order; for each dequeued node, decrement the in-degree of its successors; enqueue any newly-zero-in-degree successors in lexicographic order.
4. Repeat until the queue is empty.

Lexicographic tie-breaking is normative. Implementations MUST produce identical ordering for the same set of loaded plugins and constraints. This determinism is required so that conformance fixtures can assert chain shape statically across Python and TypeScript implementations.

The computed order MUST be calculated once at startup and cached. Implementations MUST NOT recompute the order per-request. The pipeline order is a property of the loaded plugin set, not of individual requests. Per-request recomputation would be wasteful and would introduce a nondeterminism risk if the plugin list could mutate mid-process (it cannot in v1, but the cached-once rule documents that intent).

### 4.2 Cycle Detection

If the DAG contains a cycle — that is, if Kahn's algorithm terminates with nodes remaining at non-zero in-degree — the host MUST refuse to start with `plugin_ordering_cycle`. The error message MUST name every node in the cycle, using arrow notation:

```
plugin_ordering_cycle: org.example.plugin-a -> org.example.plugin-b -> org.example.plugin-a
```

Omitting the cycle members from the error is not acceptable; operators need the cycle named to resolve the constraint conflict. Kahn's algorithm makes this straightforward: the remaining non-zero-in-degree nodes at termination are precisely the cycle members.

### 4.3 Default Chain Integration

The seven `DEFAULT_ORDER` slots defined in the predecessor middleware spec (`spec/ports/middleware.md`) are reserved **capability strings**, not plugin ids:

| Slot | Capability string |
|---|---|
| 1 | `namespace_resolver` |
| 2 | `auth` |
| 3 | `rate_limit` |
| 4 | `schema_validator` |
| 5 | `idempotency` |
| 6 | `store_dispatch` |
| 7 | `audit_log` |

A plugin that provides one of these capability strings via `plugin_capabilities` slots into that position in the default chain. A plugin that needs to run before persistence MAY declare `must_run_before: ["store_dispatch"]`; the host resolves `store_dispatch` to whichever loaded plugin provides the `store_dispatch` capability (or to the built-in store dispatch if no plugin claims it).

This capability-based resolution means plugin authors do not need to know or hard-code the id of the persistence plugin; they declare an intent (`must_run_before: ["store_dispatch"]`) and the host resolves it.

---

## 5. Discovery and Loading

Plugin discovery is described fully in `spec/ports/middleware/05-discovery.md` (authored in B2). This section provides a normative summary sufficient to understand startup behaviour.

**Python:** The host MUST scan `importlib.metadata.entry_points(group="sox_protocol.plugins")` at startup. Each entry point must map to a plugin factory callable. The entry point name MUST match the `metadata.id` in the corresponding `sox-plugin.yaml` manifest.

**Node:** The host MUST scan `package.json` files for a top-level `"sox"` key whose value is a relative path to a `sox-plugin.yaml` manifest. Example:

```json
{
  "name": "@myorg/sox-jwt-auth",
  "sox": "./dist/sox-plugin.yaml"
}
```

**Programmatic (in-tree):** `register_plugin(name, factory)` is available for composition in tests and for built-in plugins. This registration path bypasses entry-point scanning but is still subject to allowlist enforcement (§6) and manifest validation.

In all cases, the host MUST validate the discovered manifest against `spec/schemas/sox-plugin.schema.json` before attempting to load the plugin. A manifest that fails schema validation MUST produce `plugin_manifest_invalid` and MUST NOT proceed to factory instantiation.

Entry-point hints are intentionally absent from the manifest body. They live in language-specific package metadata (`pyproject.toml [project.entry-points]`, `package.json#sox`). These two layers are deliberately decoupled so the manifest remains language-neutral. See ADR 0004 §2 and `spec/schemas/sox-plugin.schema.json` description for the rationale.

---

## 6. Allowlist

### 6.1 Production Requirement

The host MUST support an explicit plugin allowlist. Two equivalent mechanisms are defined:

- `--allow-plugins ID,ID,...` CLI flag
- `SOX_ALLOWED_PLUGINS=ID,ID,...` environment variable

Both accept comma-separated lists of plugin ids (matching `metadata.id` in the manifest). When both are provided, the CLI flag takes precedence.

In **production mode** (`SOX_ENV=production`): an empty allowlist MUST cause the host to refuse to load any plugins. A non-empty allowlist MUST be treated as an exact filter; any discovered plugin whose id is not in the allowlist MUST be silently skipped (not an error). Any plugin in the allowlist that is not found MUST produce `plugin_not_found`.

In **development mode** (default, `SOX_ENV` absent or `development`): all discovered plugins are loaded. The host MUST emit a `stderr` warning for each discovered plugin that is not in the allowlist (if one is provided). An absent allowlist in development mode is not an error.

The allowlist requirement exists because `load_entry_points` is a code-execution boundary. An unconstrained allowlist in production is a supply-chain hazard (analysis §7.5 risk #1). Envoy and OPA both gate plugin loading behind explicit operator consent; `--allow-plugins` is SOX's equivalent gate.

### 6.2 Error Taxonomy

The following error codes are normative for plugin startup failures. They MUST be reported as structured log entries and, where applicable, returned to callers as `sox-error` envelopes.

| Error code | Cause | Action required |
|---|---|---|
| `plugin_not_allowed` | Plugin discovered via entry-points but not in allowlist | Config error — add id to `--allow-plugins` or verify id spelling |
| `plugin_not_found` | Plugin id in allowlist but no matching entry-point found | Deployment error — verify the plugin package is installed |
| `plugin_manifest_invalid` | Plugin installed, manifest fails schema validation | Build error — fix `sox-plugin.yaml` against schema |
| `plugin_protocol_version_mismatch` | Host's protocol version falls outside plugin's declared `protocol_version` range | Compatibility error — upgrade plugin or pin protocol version |
| `plugin_capability_conflict` | Manifest declares `observe_only: true` + `may_short_circuit: true` | Manifest authoring error — flags are mutually exclusive (§2.3) |
| `plugin_ordering_cycle` | `must_run_before` / `must_run_after` constraints form a cycle | Config error — remove contradictory ordering constraints (§4.2) |
| `plugin_requirement_unmet` | `requires` capability not provided by any loaded plugin | Deployment error — ensure the required plugin is installed and allowlisted |

These seven error codes are the complete set for v1 startup failures. The host MUST NOT emit generic "plugin failed to load" messages without one of the above codes; the distinction between config error, deployment error, build error, and compatibility error is operationally significant.

---

## 7. Configuration

### 7.1 v1 Scope

Plugin configuration is delivered exclusively via environment variables in v1. A `sox.yaml` configuration file is deferred to v1.x. Rationale: environment variables have zero schema-evolution cost, are idiomatic in container deployments (Kubernetes ConfigMap → env), and introduce no new artifacts requiring their own spec, validator, or migration story (ADR 0004 §7).

### 7.2 Canonicalization Rule (Normative)

The environment variable name for a plugin configuration key is derived from the plugin's `metadata.id` via the following deterministic algorithm:

1. Replace every `.` and `-` character in the id with `_`.
2. Convert the result to uppercase.
3. Prefix with `SOX_PLUGIN_`.
4. Append `_` followed by the configuration key, uppercased.

**Example:** plugin id `org.example.sox-jwt-auth`, configuration key `JWKS_URL`:

```
org.example.sox-jwt-auth
→ replace . and - with _: org_example_sox_jwt_auth
→ uppercase: ORG_EXAMPLE_SOX_JWT_AUTH
→ prefix + key: SOX_PLUGIN_ORG_EXAMPLE_SOX_JWT_AUTH_JWKS_URL
```

Hosts and plugin authors MUST use this algorithm without variation. If two implementations canonicalize differently, a plugin's configuration will resolve correctly on one runtime and silently fail on another. The canonicalization is normative; any deviation is a conformance failure.

See `spec/schemas/examples/sox-plugin.example.provider.yaml` for the applied form: the Redis pool plugin with id `com.myco.sox-provider-redis-pool` exposes configuration under `SOX_PLUGIN_COM_MYCO_SOX_PROVIDER_REDIS_POOL_*`.

A plugin MAY declare a `config_schema_ref` in its manifest pointing to a JSON Schema file that validates the environment-variable-derived configuration. The host MAY use this schema to validate configuration at startup and fail-fast on invalid values.

---

## 8. Observability

### 8.1 Pipeline Trace

Every dispatch response MUST include a `pipeline_trace` array in `metadata["pipeline_trace"]`. The array contains one record per plugin that participated in the dispatch, in execution order.

Each record MUST contain the following fields:

| Field | Type | Description |
|---|---|---|
| `plugin_id` | string | The `metadata.id` of the plugin, as declared in its manifest |
| `kind` | string | The `plugin_kind` enum value (`interceptor`, `transformer`, `provider`, `hook`) |
| `started_at` | float | Unix epoch seconds (float) at which the plugin's callable was invoked |
| `finished_at` | float | Unix epoch seconds (float) at which the plugin's callable returned or raised |
| `verdict` | string | One of `"continue"`, `"short_circuit"`, `"error"` |
| `correlation_id` | string | Echoed from `MiddlewareContext.correlation_id` (frozen field; set once at request ingress, never mutated by plugins) |

The `error_code` field MUST be present when `verdict == "error"`, containing the applicable error code string. It MUST be absent otherwise.

The `correlation_id` field is echoed from the request envelope's `MiddlewareContext.correlation_id`. This field is frozen — no plugin is permitted to mutate it. Its presence in every `pipeline_trace` record is what allows records from concurrent dispatches to be correlated across logs without an external trace context. Without `correlation_id`, `pipeline_trace` arrays from concurrent requests produce ambiguous log streams.

OTel span emission is deferred to v1.x. The structured array is sufficient for `grep`-based debugging and CI assertions in v1. The field names are chosen to be compatible with a future OTel mapping.

Lifecycle-axis plugins (`provider`, `hook`) MUST also emit records when they participate in the dispatch (hooks) or when they complete startup (providers, as a startup-phase record). Provider startup records use a synthetic `started_at` / `finished_at` bracketing the `on_startup` call; `verdict` is `"continue"` on success, `"error"` on exception.

---

## 9. v1 Limitations

### 9.1 Static Composition

In v1, the `MiddlewareRegistry` is loaded once at startup. Plugin registration, ordering, and capability resolution are performed at that time and are not repeated during the process lifetime. The host MUST NOT support adding or removing plugins from the registry after startup is complete. There is no hot-reload in v1.

Hosts MUST document the static-only nature of plugin composition in their startup logs (for example: `[sox] plugin registry frozen: 4 plugins loaded`).

### 9.2 No Cache of Host-Provided Objects (Normative)

Plugin authors MUST NOT cache references to host-provided objects — registries, contexts, configuration objects, or any other object provided by the host at plugin init time — across the plugin's lifetime. The host MAY rebuild any of these objects between v1 and v2. In v1, the host will not actually rebuild them; but v2-compatible plugin code must not assume they are stable.

This requirement is forward-compatibility insurance derived from the Backstage hot-reload experience: Backstage's `plugin-backend` team found that hot-reload could not land because plugin authors had cached `BackstageEnvironment` references. By the time the limitation was understood, reverting it required coordinated re-publication of every plugin in the ecosystem. The cost of caching in v1 is zero; the cost of uncaching at v2 would be high. This requirement is the cheap-now/expensive-later tradeoff inverted.

Plugin authors who need access to host state across multiple dispatch invocations SHOULD access it via a provider-supplied resource (§2.2.1) rather than by retaining a reference to the host context object.

### 9.3 v2 Relaxation Path

v2.x MAY relax the static-composition constraint to support add/remove of plugins at runtime. This document reserves the relaxation path by prohibiting plugins from assuming stable identity of host-provided objects. v1 hosts that do not support reload MUST document this in their startup logs (see §9.1).

---

## 10. Conformance and Testing

### 10.1 Reference Implementation

The reference implementation for this contract is in `packages/python/src/sox_protocol/core/middleware/`. The relevant modules are:

- `pipeline.py` — `Pipeline` class; chain dispatch; interceptor `next` chain construction
- `registry.py` — `MiddlewareRegistry`; discovery; allowlist enforcement; manifest validation
- `context.py` — `MiddlewareContext`; `correlation_id` frozen field; `ImmutableMiddlewareContext` wrapper
- `plugins/` — built-in plugins (`auth.py`, etc.) that exercise the contract

### 10.2 Conformance Fixtures

Conformance fixtures are authored in engagement B2 (`plugin-spec-polish`) under `spec/conformance/plugin-contract/`. Fixtures are cross-language: both the Python and TypeScript implementations are required to pass them.

Planned fixture categories:
- `01-interceptor-call-next.yaml` — interceptor calls `next` exactly once
- `02-interceptor-short-circuit.yaml` — interceptor raises `ShortCircuitResponse`
- `03-transformer-mutates-ctx.yaml` — transformer returns modified context
- `04-hook-observe-only.yaml` — hook receives immutable context
- `05-must-run-before-after.yaml` — ordering constraints produce deterministic chain

### 10.3 Provider Kind Conformance

The `provider` kind has zero runtime validation in v1 (the reference plugin `io.sox.schema-strict` is a transformer, not a provider). To prevent the first real `provider` plugin from discovering contract bugs in production, B2 MUST ship a synthetic in-memory provider conformance fixture that validates: factory call signature, `on_startup` invocation, `on_shutdown` invocation, capability registration, and `requires` resolution against the registered capability. This is per §Q6 NR-2 of `suggestions-v2.md`.

---

## 11. Candidate Contract Note

This document is a **candidate** plugin contract. Status: candidate (2026-05-01).

Promotion to `Status: stable` happens after the following conditions are met:

1. Conformance fixtures (B2, `plugin-spec-polish`) are authored and pass against the Python reference implementation.
2. The first reference plugin (`io.sox.schema-strict`, engagement P5) is authored against this contract and ships without requiring amendments.
3. The TypeScript contract spike (engagement E) validates that the manifest round-trips through TS YAML + AJV without schema discrepancies.

The name "plugin-contract-freeze" for the parent engagement (`plugin-contract-freeze`, STATE.md) refers to the B1 delivery milestone, not to the irrevocability of this document. Conformance fixtures in B2 and the reference plugin in P5 may surface issues that require minor amendments to this document. Such amendments are not a process failure — they are how Postel's "rough consensus and running code" produces durable specifications. A reviewer MUST NOT reject a post-B1 amendment PR on the grounds that "B1 was already merged."

The candidate status is documented here and in STATE.md so that downstream engagement authors (`plugin-discovery-py`, `reference-plugins`, `plugin-architecture-ts`) know to watch for and accommodate amendments rather than treating this document as frozen.
