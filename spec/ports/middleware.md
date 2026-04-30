<!-- SPDX-License-Identifier: Apache-2.0 -->
# Middleware Port — Behaviour Contract

**Version:** 1.0  
**Status:** Normative  
**Scope:** Language-neutral. This document specifies the inspect/mutate/short-circuit pipeline contract, not any specific framework, library, or language binding.

---

## 1. Purpose

The **Middleware** port specifies a composable pipeline through which every tool call passes before reaching the backing store. Each middleware unit can:

- **Inspect** — read the operation name, input arguments, and connection context without modifying them.
- **Mutate** — modify the input arguments before they reach the next stage (e.g. inject a server-assigned `sender` field, normalise a channel name).
- **Short-circuit** — return a response without forwarding to the backing store (e.g. reject an unauthenticated caller, serve a cached result).

This is the standard pipes-and-filters pattern applied to SOX tool calls.

---

## 2. Pipeline structure

A middleware pipeline is an ordered list of middleware units. Tool calls flow through units left-to-right (request direction); responses flow right-to-left (response direction):

```text
Tool call → [MW-1] → [MW-2] → [MW-3] → BackingStore
                                              ↓
Tool response ← [MW-1] ← [MW-2] ← [MW-3] ←─┘
```

Each middleware unit MUST:

1. Receive the (operation, input, context) tuple from the preceding unit.
2. Either pass it to the next unit (possibly mutated) or short-circuit with a response.
3. On the response path, receive the response from the next unit and either pass it through (possibly mutated) or substitute its own response.

---

## 3. Context object

Each middleware unit receives a **context object** containing:

| Field | Type | Description |
|---|---|---|
| `operation` | string | One of `send`, `recv`, `subscribe`, `list_channels` |
| `input` | object | The tool call input arguments (mutable by middleware) |
| `agent_id` | string or null | The server-bound agent identity, if already resolved |
| `connection_id` | string | Opaque identifier for the connection that issued this call |
| `metadata` | object | Extensible key-value map for inter-middleware communication |

The context object is scoped to a single tool call. It MUST NOT be shared across concurrent calls.

---

## 4. Middleware ordering convention

The following order is the **normative default chain** (per ADR 0003). Implementations MAY deviate for specific use cases but MUST document any deviation. Each link is independently removable; removing `auth` or `namespace_resolver` from a production deployment is a security misconfiguration.

1. **`namespace_resolver`** — derives the active namespace from the connection's claimed `agent_id` (pre-auth hint) and attaches it to the request context. MUST run before auth. Removing this middleware breaks namespace routing. (See `spec/primitives/namespace.md`)
2. **`auth` (Identity middleware)** — verifies the agent credential (Ed25519 signature in the reference implementation), binds the verified `agent_id` to context, sets `input.sender` for `send` operations. MUST run after `namespace_resolver` and before all other chain links. (See `spec/ports/identity.md`, docs/adr/0002)
3. **`rate_limit`** — enforces per-agent and per-channel rate limits. Runs after auth so limits are keyed on verified identity.
4. **`schema_validator`** — validates `input.body` against the channel's registered JSON Schema (fetched from the backing store via `get_channel_schema`). Short-circuits with `VALIDATION_FAILED` error on schema violation. **Default-on** in the reference deployment; removable for performance-sensitive deployments where producers are trusted. (See `docs/decisions/schema-validation-layer.md`)
5. **`idempotency`** — checks the idempotency cache for duplicate `send` calls. Short-circuits with the cached result if a valid entry exists. Runs before `store_dispatch` so duplicate sends never reach the store.
6. **`store_dispatch`** — calls the backing store. The only chain link that performs persistence.
7. **`audit_log`** — writes a structured log entry for every tool call (operation, agent_id, namespace, timestamp, outcome). Runs on the response path after `store_dispatch`.

---

## 5. Short-circuit semantics

A middleware unit that short-circuits MUST return a response conforming to the relevant output schema for the operation:

- For `send`: `spec/operations/send.output.schema.json` (on success) or `spec/envelopes/sox-error.schema.json` (on rejection).
- For `recv`: `spec/operations/recv.output.schema.json` (on success, e.g. empty result from cache) or `spec/envelopes/sox-error.schema.json`.
- For `subscribe`: `spec/operations/subscribe.output.schema.json` or `spec/envelopes/sox-error.schema.json`.
- For `list_channels`: `spec/operations/list_channels.output.schema.json` or `spec/envelopes/sox-error.schema.json`.

A middleware unit that short-circuits MUST NOT forward the call to the next unit in the pipeline.

---

## 6. Mutability constraints

| What | May mutate? | Notes |
|---|---|---|
| `input.channel` | Yes | Middleware may normalise channel names (e.g. lowercase). MUST document if it does. |
| `input.body` | Yes | Middleware may add metadata fields (e.g. server-assigned timestamps). MUST NOT remove fields set by the caller. |
| `input.correlation_id` | No | Caller-assigned; middleware MUST NOT overwrite. |
| `context.agent_id` | Only by identity MW | Once set, subsequent middleware MUST NOT change it. |
| `context.connection_id` | No | Assigned at connection time; read-only in middleware. |

---

## 7. Error handling

If a middleware unit encounters an unrecoverable internal error (not a caller error):

- It MUST short-circuit and return a `sox-error` with `error_code: "internal_error"`.
- It MUST log the error with enough detail to diagnose the failure.
- It MUST NOT propagate uncaught exceptions to the caller in a way that leaks internal implementation details.

---

## 8. `schema_validator` middleware — contract

The `schema_validator` middleware:

1. On each `send` call, fetches the registered schema for the target channel via `get_channel_schema(namespace, channel)`.
2. If no schema is registered (`null`), passes through without validation.
3. If a schema is registered, validates `input.body` against it using JSON Schema (draft 2020-12).
4. On validation failure, short-circuits with error code `VALIDATION_FAILED` and a structured error body listing all violations.
5. On validation success, passes through to `store_dispatch`.

The backing store is explicitly forbidden from performing body validation — it is schema-agnostic. Only the `schema_validator` middleware enforces channel schemas.

**Default-on:** The reference deployment ships with `schema_validator` enabled. Disabling it silently accepts malformed messages on typed channels; operators MUST document this if they disable it.

---

## 9. Conformance

A middleware pipeline implementation is conformant when:

- [ ] `namespace_resolver` runs before `auth` in the default chain.
- [ ] `auth` (identity) middleware runs before all other chain links and sets `context.agent_id` from a verified credential.
- [ ] `schema_validator` is present in the default chain and defaults to enabled.
- [ ] No middleware overwrites `correlation_id`.
- [ ] Short-circuit responses conform to the relevant output schema.
- [ ] Pipeline order is documented; any deviation from the normative default is documented.
- [ ] Internal errors produce `sox-error` responses, not implementation-specific exceptions.
- [ ] The pipeline is reentrant: concurrent tool calls MUST NOT share context objects.
- [ ] The conformance suite asserts the default chain refuses an unauthenticated `send`.
