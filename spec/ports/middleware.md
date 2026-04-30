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

The following order is the RECOMMENDED default. Implementations MAY deviate from this order for specific use cases, but MUST document any deviation:

1. **Identity middleware** — verifies agent credential, binds `agent_id` to context, sets `input.sender` for `send` operations. MUST run first. (See `spec/ports/identity.md`)
2. **Rate-limit middleware** — enforces per-agent and per-channel rate limits. Runs after identity so limits are keyed on verified identity.
3. **Validation middleware** — validates input arguments against `spec/operations/*.input.schema.json`. Short-circuits with `sox-error` on schema violation.
4. **Audit middleware** — writes a structured log entry for every tool call (operation, agent_id, timestamp, outcome). SHOULD run after identity; MAY run at the end of the response path.
5. **BackingStore** — the actual persistence operation.

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

## 8. Conformance

A middleware pipeline implementation is conformant when:

- [ ] Identity middleware runs first and sets `context.agent_id` from a verified credential.
- [ ] No middleware overwrites `correlation_id`.
- [ ] Short-circuit responses conform to the relevant output schema.
- [ ] Pipeline order is documented.
- [ ] Internal errors produce `sox-error` responses, not implementation-specific exceptions.
- [ ] The pipeline is reentrant: concurrent tool calls MUST NOT share context objects.
