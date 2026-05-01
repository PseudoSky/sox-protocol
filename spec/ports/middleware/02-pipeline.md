<!-- SPDX-License-Identifier: Apache-2.0 -->
# Middleware Port — Pipeline Flow, Short-Circuit Semantics, and Error Handling

**Version:** 1.0
**Status:** Normative
**Scope:** Language-neutral. This document specifies the left-to-right pipeline flow, short-circuit semantics, response-path behaviour, mutability constraints, and error handling rules for the SOX middleware pipeline.

**Related:**
- `spec/ports/middleware/01-context.md` — `MiddlewareContext` shape and structural invariants (prerequisite to this document)
- `spec/ports/middleware/07-default-chain.md` — the `DEFAULT_ORDER` constant and normative slot ordering
- `spec/ports/middleware/03-plugin-contract.md` — plugin kinds and per-kind failure semantics
- `docs/adr/0003-extensibility-mechanism.md` — decision rationale for the hybrid middleware + hooks model

---

## 1. Pipeline Structure

A middleware pipeline is an ordered list of middleware units. Tool calls flow through units **left-to-right** on the request path; responses flow **right-to-left** on the response path:

```text
Tool call → [MW-1] → [MW-2] → [MW-3] → BackingStore
                                              ↓
Tool response ← [MW-1] ← [MW-2] ← [MW-3] ←─┘
```

Each middleware unit MUST:

1. Receive the `MiddlewareContext` (see `01-context.md`) from the preceding unit or from the host dispatch machinery if it is the first unit.
2. Either pass the context to the next unit (possibly with authorised mutations) or short-circuit with a conformant response.
3. On the response path, receive the response from the next unit and either pass it through (possibly with authorised mutations) or substitute its own response.

The pipeline is executed synchronously within a single request-handling coroutine. The host MUST NOT execute multiple units concurrently for a single request. Units for different concurrent requests MUST each operate on their own independent context instances (see `01-context.md` §4.1).

The pipeline order is computed once at startup using the Kahn's algorithm specified in `03-plugin-contract.md` §4 and is thereafter cached. The order MUST NOT change between requests.

---

## 2. Short-Circuit Semantics

A middleware unit **short-circuits** when it returns a response without forwarding the call to the next unit in the pipeline. Short-circuiting is the intended mechanism for authentication denial, rate-limit rejection, cache serving, idempotency deduplication, and any other early-exit decision.

### 2.1 When Short-Circuit is Permitted

Any middleware unit MAY short-circuit unless it is declared `observe_only: true` (see `03-plugin-contract.md` §2.3). A unit declaring `observe_only: true` MUST call `next` and MUST NOT return a short-circuit response.

### 2.2 Short-Circuit Response Requirements

A unit that short-circuits MUST return a response conforming to the relevant output schema for the operation:

| Operation | Success schema | Error schema |
|---|---|---|
| `send` | `spec/operations/send.output.schema.json` | `spec/envelopes/sox-error.schema.json` |
| `recv` | `spec/operations/recv.output.schema.json` | `spec/envelopes/sox-error.schema.json` |
| `subscribe` | `spec/operations/subscribe.output.schema.json` | `spec/envelopes/sox-error.schema.json` |
| `list_channels` | `spec/operations/list_channels.output.schema.json` | `spec/envelopes/sox-error.schema.json` |

A unit that short-circuits MUST NOT forward the call to the next unit. Once a unit short-circuits, the remaining units in the request direction are skipped entirely.

### 2.3 `ShortCircuitResponse`

The host implementation MUST define a `ShortCircuitResponse` type (or equivalent language construct) that interceptor-kind plugins may raise to signal early exit. When `ShortCircuitResponse` is raised:

- The host MUST propagate it as the final dispatch response for that call.
- The host MUST NOT log `ShortCircuitResponse` as an error condition.
- The `pipeline_trace` record for the unit MUST carry `verdict: "short_circuit"` (see `03-plugin-contract.md` §8.1).

A `ShortCircuitResponse` raised by a plugin declaring `observe_only: true` is a contract violation. The host MUST handle it as specified in `03-plugin-contract.md` §3.1.

---

## 3. Response Path

After the backing store returns its response (or after a unit short-circuits), the response flows right-to-left through all units that participated in the request path. Units that were skipped by an earlier short-circuit do not participate in the response path.

On the response path, each unit MAY:

- **Inspect** the response without modifying it.
- **Mutate** the response by adding metadata fields, appending trace information, or augmenting the payload. Units MUST NOT remove fields set by the backing store or by earlier response-path units.
- **Substitute** the response with a different conformant response. Substitution is a stronger form of mutation and SHOULD be documented if a unit does it.

The response path is distinct from short-circuit: a unit that short-circuits does so on the *request* path before `next` is called. A unit that participates in the *response* path has already called `next` and is now processing the response on the way back out.

---

## 4. Mutability Constraints

These constraints apply to all middleware units on both the request and response paths. They supplement the per-field rules in `01-context.md` §3.

| What | May mutate? | Notes |
|---|---|---|
| `context.input.channel` | Yes | Middleware MAY normalise channel names (e.g. lowercase). MUST document if it does. |
| `context.input.body` | Yes (additive) | Middleware MAY add metadata fields (e.g. server-assigned timestamps). MUST NOT remove fields set by the caller. |
| `context.input.correlation_id` | No | Caller-assigned; any unit that overwrites `input.correlation_id` is a conformance violation. |
| `context.agent_id` | Identity middleware only | Once set by the identity unit, MUST NOT be changed by any subsequent unit. |
| `context.connection_id` | No | Assigned at connection time; read-only throughout the pipeline. |
| `context.correlation_id` | No | Frozen at request ingress; MUST NOT be changed by any unit. |
| `context.metadata` | Yes (by convention) | Any unit MAY read and write keys. Namespacing by unit id is RECOMMENDED. |
| Response `message_id` | No | Backing-store assigned; response-path units MUST NOT overwrite. |

---

## 5. Error Handling

### 5.1 Internal Errors

If a middleware unit encounters an unrecoverable internal error (an error caused by the unit's own implementation fault, not by a caller-supplied input error):

- The unit MUST short-circuit and return a `sox-error` envelope with `error_code: "internal_error"`.
- The unit MUST log the error with sufficient detail to diagnose the failure, including `context.correlation_id`.
- The unit MUST NOT propagate uncaught exceptions to the caller in a way that leaks internal implementation details (stack traces, internal paths, secret material).

For plugin-kind units, the host MUST catch any unhandled exception and apply the per-kind failure semantics defined in `03-plugin-contract.md` §3. The general rule here applies to built-in (non-plugin) middleware units.

### 5.2 Caller Input Errors

If a unit determines that the caller's input is invalid (for example, a schema violation detected by `schema_validator`):

- The unit SHOULD short-circuit with a `sox-error` envelope carrying an error code that describes the specific rejection (e.g. `VALIDATION_FAILED`).
- The error body SHOULD include actionable detail: which fields failed, what was expected, what was received.
- The unit MUST NOT return `internal_error` for caller-correctable conditions. Using `internal_error` for input validation is a misuse that removes diagnostic value from the caller's perspective.

### 5.3 Chain Integrity After Error

After any unit short-circuits (whether due to an internal error or a caller error), the remaining request-path units MUST NOT be invoked. The response path proceeds right-to-left only for units that ran before the short-circuit unit.

The host MUST ensure that a short-circuit on the request path does not corrupt the pipeline state for subsequent, unrelated requests. Per-call context isolation (`01-context.md` §4.1) is the primary mechanism for this guarantee.

---

## 6. Reentrance

The pipeline MUST be reentrant. Multiple concurrent tool calls MUST each proceed through the pipeline with full independence — no shared mutable state, no shared context objects, no ordering dependencies between calls.

Built-in middleware units MUST be implemented without per-call mutable state at the unit level. Any state that must persist across calls (for example, the idempotency cache or the rate-limit counter) MUST be stored in a shared resource accessed via a thread-safe or async-safe mechanism, not in the unit object itself.

Plugin-kind units are subject to the same reentrance requirement via `03-plugin-contract.md` §9.1 and `01-context.md` §4.1. The host MUST NOT rely on plugin units being reentrant in the absence of testing; the conformance fixtures in `spec/conformance/plugin-contract/` include assertions on concurrent dispatch.

---

## 7. `next` Call Semantics for Interceptors

Interceptor-kind plugin units (see `03-plugin-contract.md` §2.1.1) receive a `next` callable representing the remainder of the pipeline. The following rules govern `next` usage:

- Calling `next` exactly once on the request path is the standard case: the unit forwards the call and receives the response.
- Calling `next` zero times is short-circuiting: the unit returns a response without forwarding.
- Calling `next` more than once in a single dispatch is a **contract violation**. The host SHOULD detect this (for example, via a one-shot wrapper around `next`) and SHOULD log the violation. The behaviour of the downstream chain after a second `next` call is undefined; the host MUST NOT allow the second call to produce a second backing-store write.

A unit declaring `observe_only: true` MUST call `next` exactly once and MUST NOT modify the context before passing it. The host SHOULD enforce the no-mutation constraint via a context wrapper (see `03-plugin-contract.md` §2.3).

---

## 8. Async Semantics

The pipeline contract is **async-native**. All middleware units MUST be expressible as async callables. Synchronous units MUST be wrapped with an executor before registration; the host MAY provide a `sync_to_async` adapter for this purpose.

The rationale: a synchronous blocking call inside the pipeline stalls the entire event loop for async host implementations (ASGI, asyncio). Requiring async-native callables ensures that the pipeline does not become a latency sink due to unintentional blocking.

This requirement is explicitly deferred from `docs/adr/0003-extensibility-mechanism.md` open question #1 ("Async semantics"): the answer is async-only in the contract, with sync units wrapped by an executor.
