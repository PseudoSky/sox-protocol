<!-- SPDX-License-Identifier: Apache-2.0 -->
# Middleware Port — Context, Purpose, and Structural Rules

**Version:** 1.0
**Status:** Normative
**Scope:** Language-neutral. This document specifies the purpose of the Middleware port, the `MiddlewareContext` object shape, and the structural invariants that every host implementation MUST maintain.

**Related:**
- `spec/ports/middleware/02-pipeline.md` — pipeline flow, short-circuit semantics, mutability constraints (sequel to this document)
- `spec/ports/middleware/07-default-chain.md` — the `DEFAULT_ORDER` constant and normative slot ordering
- `spec/ports/middleware/03-plugin-contract.md` — plugin kinds and how plugins participate in the context lifecycle
- `docs/adr/0003-extensibility-mechanism.md` — decision rationale for the hybrid middleware + hooks model
- `docs/adr/0004-plugin-architecture.md` — plugin architecture decisions that extend this context model

---

## 1. Purpose

The **Middleware** port specifies a composable pipeline through which every SOX tool call passes before reaching the backing store. The port is defined as a pipes-and-filters chain: each middleware unit receives a context tuple, either forwards it (possibly mutated) to the next unit, or short-circuits with a response.

Each middleware unit MAY:

- **Inspect** — read the operation name, input arguments, and connection context without modifying them.
- **Mutate** — modify the input arguments before they reach the next stage (for example, inject a server-assigned `sender` field or normalise a channel name).
- **Short-circuit** — return a response without forwarding to the backing store (for example, reject an unauthenticated caller or serve a cached result).

This is the standard pipes-and-filters pattern applied to SOX tool calls. ADR 0003 ratified this model as the load-bearing primitive for SOX extensibility, with hooks defined as observation-only sugar on top of the same chain. The plugin contract in `03-plugin-contract.md` extends this model by classifying middleware units into four kinds with explicit capability flags.

The Middleware port exists to ensure that all host implementations — regardless of language, transport, or backing-store choice — expose the same extension surface to plugin authors. A plugin written against this port's context contract is portable across any conformant host.

---

## 2. `MiddlewareContext` Object

Each middleware unit receives a **`MiddlewareContext`** object for the duration of a single tool call. The context carries all information the unit needs to make its decision.

### 2.1 Required Fields

| Field | Type | Mutability | Description |
|---|---|---|---|
| `operation` | string | Read-only | One of `send`, `recv`, `subscribe`, `list_channels`. Set at request ingress; MUST NOT be changed by any middleware unit. |
| `input` | object | Conditionally mutable | The tool call input arguments. Individual sub-fields have their own mutability rules; see §3. |
| `agent_id` | string or null | Identity-middleware only | The server-bound agent identity, once resolved. `null` until the identity middleware runs. After the identity middleware sets this field, all subsequent units MUST treat it as read-only. |
| `connection_id` | string | Read-only | Opaque identifier for the connection that issued this call. Assigned at connection time; MUST NOT be changed by any middleware unit. |
| `correlation_id` | string | Frozen | A unique identifier for this individual request invocation. Set once at request ingress. MUST NOT be changed by any middleware unit, including the identity middleware. Present in every `pipeline_trace` record (§8 of `03-plugin-contract.md`). |
| `metadata` | object | Mutable by convention | Extensible key-value map for inter-middleware communication. Any middleware unit MAY read or write keys in this map. Key conflicts between units are the unit author's responsibility; namespacing by unit id is RECOMMENDED. |

### 2.2 Lifecycle

A `MiddlewareContext` object is created once per tool call at request ingress, before the first middleware unit is invoked. It is destroyed (or returned to a pool) after the final response is produced. No context object is reused across tool calls.

The context object is **scoped to a single tool call**. It MUST NOT be shared across concurrent calls, passed to another call, or retained by any middleware unit beyond the unit's own execution scope. This is the reentrance requirement: concurrent tool calls running in the same process MUST each have their own independent `MiddlewareContext` instance.

Plugin authors MUST NOT cache references to `MiddlewareContext` objects or any host-provided object reachable through them across dispatch invocations. See `03-plugin-contract.md` §9.2 for the forward-compatibility rationale.

---

## 3. Input Field Mutability Rules

The `context.input` object carries the tool call's arguments. Mutability is per sub-field:

| Sub-field | May mutate? | Rule |
|---|---|---|
| `input.channel` | Yes, with documentation | Middleware MAY normalise channel names (for example, lowercase). Any unit that mutates `input.channel` MUST document this behaviour. |
| `input.body` | Yes, with restrictions | Middleware MAY add metadata fields (for example, server-assigned timestamps). Middleware MUST NOT remove fields set by the caller. Additive mutation only. |
| `input.correlation_id` | No | Caller-assigned; any middleware unit that overwrites `input.correlation_id` is in violation of this contract. See also `context.correlation_id`. |
| `input.sender` | Identity middleware only | The identity middleware MUST overwrite `input.sender` with the verified `agent_id`. No other unit may set or change `input.sender`. |
| `input.reply_to` | No | Caller-assigned threading field; MUST NOT be overwritten by any middleware unit. |

Sub-fields not listed above are governed by the general rule: middleware SHOULD prefer additive mutation and MUST NOT remove or overwrite caller-supplied fields unless this contract explicitly permits it.

---

## 4. Structural Invariants

The following invariants are normative for all host implementations. Violating any of them is a conformance failure.

### 4.1 Per-call context isolation

No `MiddlewareContext` instance is shared between two concurrent tool calls. The host MUST allocate (or acquire from a pool) a fresh context for each call before invoking the first middleware unit. Two calls MUST NOT observe each other's context mutations.

### 4.2 `agent_id` monotonicity

Once `context.agent_id` is set by the identity middleware, no subsequent middleware unit is permitted to change it. The value MUST be treated as frozen from the moment of assignment.

Corollary: if the identity middleware short-circuits (for example, on credential rejection), `context.agent_id` will remain `null` for all units that might otherwise have run. Units that run after a short-circuit do not run at all; this is not a concern in practice. Units that run *before* the identity middleware (only `namespace_resolver` in the default chain) MUST handle `context.agent_id == null`.

### 4.3 `correlation_id` immutability

`context.correlation_id` is frozen at request ingress. No middleware unit — including the identity middleware — is permitted to mutate it. This field is the correlation anchor across all `pipeline_trace` records; mutating it mid-chain would produce unlinkable trace records.

### 4.4 Context does not outlive the call

Middleware units MUST NOT hold a reference to the `MiddlewareContext` after their callable returns. In particular, spawning background tasks that retain a reference to the live context is forbidden. Units that need to perform post-call work (for example, async audit logging) MUST capture the specific fields they need (operation, agent_id, correlation_id, outcome) before returning, not retain the whole context object.

### 4.5 No context sharing across the `next` boundary

An interceptor-kind plugin (see `03-plugin-contract.md` §2.1.1) MUST pass the same `MiddlewareContext` instance to `next` that it received — or a shallow copy with only the mutations it is authorised to make. It MUST NOT pass an unrelated context object to `next`. The downstream chain's behaviour is undefined if it receives a different context from the one associated with the current call.

---

## 5. Relationship to Plugin Kinds

The `MiddlewareContext` contract intersects with the plugin kind taxonomy in `03-plugin-contract.md`:

- **`kind: interceptor`** — receives the full mutable context and a `next` callable. May mutate fields permitted by §3. If declared `observe_only: true`, MAY NOT mutate any field; the host SHOULD enforce this via a wrapper assertion.
- **`kind: transformer`** — receives the mutable context; returns a (possibly new) context. Operates exclusively pre-dispatch. Governed by the same field mutability rules as §3.
- **`kind: hook`** — receives an `ImmutableMiddlewareContext` wrapper. The wrapper MUST prevent mutation of all fields in §3, raising a runtime error on any attempted write.
- **`kind: provider`** — does not receive a `MiddlewareContext` per-call. Interacts with `ServerContext` at lifecycle (startup/shutdown) events only.

For the full contract of each kind, see `03-plugin-contract.md` §2.

---

## 6. `metadata` Map Conventions

The `context.metadata` map is the intended communication channel between middleware units that need to pass information without modifying `input` fields. Examples:

- The `namespace_resolver` unit writes `metadata["namespace"]` for downstream units.
- The `auth` unit writes `metadata["auth_method"]` so the audit logger can record the credential type used.
- The `rate_limit` unit writes `metadata["rate_limit_remaining"]` for observability hooks.

Keys SHOULD be namespaced by the unit's capability string (for example, `namespace_resolver.namespace`, `auth.method`) to avoid collision. No key is reserved or normative in this document; each unit's documentation defines its own keys.

The `pipeline_trace` array is written into `metadata["pipeline_trace"]` by the host dispatch machinery, not by individual middleware units. Units MUST NOT write to `metadata["pipeline_trace"]` directly.
