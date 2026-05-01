<!-- SPDX-License-Identifier: Apache-2.0 -->
# Middleware Port — Default Chain Order

**Version:** 1.0
**Status:** Normative
**Scope:** Language-neutral. This document specifies the `DEFAULT_ORDER` constant, the normative ordering and purpose of each slot, and the `schema_validator` default-on contract.

**Related:**
- `spec/ports/middleware/01-context.md` — `MiddlewareContext` shape; `agent_id` monotonicity invariant (slot 2 depends on slot 1)
- `spec/ports/middleware/02-pipeline.md` — pipeline flow and short-circuit semantics that the default chain implements
- `spec/ports/middleware/03-plugin-contract.md` — §4.3 (default chain capability strings); how plugins slot into the default chain via capability strings
- `spec/ports/middleware/08-conformance.md` — conformance criteria that assert the default chain is correctly ordered
- `spec/ports/identity.md` — Identity port; slot 2 (`auth`) implements this contract
- `spec/ports/backing-store.md` — BackingStore port; slot 6 (`store_dispatch`) is the sole point of contact with the backing store
- `docs/adr/0003-extensibility-mechanism.md` — decision 2: "The default chain is normative"

---

## 1. The `DEFAULT_ORDER` Constant

The **`DEFAULT_ORDER`** constant defines the normative ordering for the built-in middleware chain. It is declared in the reference implementation and MUST be reproduced by all conformant host implementations.

```python
DEFAULT_ORDER = [
    "namespace_resolver",   # slot 1
    "auth",                 # slot 2
    "rate_limit",           # slot 3
    "schema_validator",     # slot 4
    "idempotency",          # slot 5
    "store_dispatch",       # slot 6
    "audit_log",            # slot 7
]
```

Each element is a **capability string** that identifies a slot in the chain. A plugin that provides one of these capability strings via `plugin_capabilities` fills that slot. If no loaded plugin provides a given capability string, the host's built-in implementation of that slot is used.

This capability-based slot resolution means that the default chain is reconfigurable without modifying the chain definition. An operator deploying a custom rate-limiter registers it with `plugin_capabilities: ["rate_limit"]`, and it fills slot 3 automatically.

---

## 2. Slot Specifications

### Slot 1 — `namespace_resolver`

**Purpose:** Derives the active namespace from the connection's claimed `agent_id` (a pre-auth hint) and attaches it to the request context via `context.metadata["namespace_resolver.namespace"]`.

**MUST run:** Before `auth` (slot 2). The namespace resolution context is needed by the identity middleware to scope credential lookups.

**Removal consequence:** Removing `namespace_resolver` breaks namespace routing. Multi-tenant deployments that rely on namespace isolation (`spec/primitives/namespace.md`) MUST NOT remove this slot.

**`must_run_before`:** `["auth"]`

**Context interaction:** Reads `context.agent_id` (may be `null` at this stage; the pre-auth hint is from the connection header, not a verified credential). Writes `context.metadata["namespace_resolver.namespace"]`.

### Slot 2 — `auth`

**Purpose:** Verifies the agent credential (Ed25519 signature in the reference implementation), binds the verified `agent_id` to `context.agent_id`, and sets `input.sender` for `send` operations.

**MUST run:** After `namespace_resolver` (slot 1) and before all wire-axis middleware units that follow. This is the load-bearing security guarantee: no request MUST reach the backing store without having passed through `auth`.

**Short-circuit:** On credential failure, `auth` MUST short-circuit with a `sox-error` envelope and MUST NOT call `next`. No backing-store access occurs on the failure path.

**Removal consequence:** Removing `auth` from a production deployment makes the server open to unauthenticated access. This is a **security misconfiguration**. The conformance suite (see `08-conformance.md`) asserts that the default chain refuses an unauthenticated `send`.

**Identity port:** This slot implements `spec/ports/identity.md`. The guarantee in that document — that `sender` is server-certified, not caller-claimed — is upheld by this slot's mutually-exclusive write to `context.agent_id` and `input.sender`.

**`must_run_after`:** `["namespace_resolver"]`

### Slot 3 — `rate_limit`

**Purpose:** Enforces per-agent and per-channel rate limits. Runs after `auth` so that rate limits are keyed on verified identity, not on a pre-auth hint that could be spoofed.

**MUST run:** After `auth` (slot 2). Running rate limits before auth would allow unauthenticated requests to consume rate-limit quota from verified agents' pools.

**Short-circuit:** On limit exceeded, `rate_limit` SHOULD short-circuit with a `sox-error` envelope carrying a `rate_limit_exceeded` error code. The response SHOULD include a `Retry-After`-equivalent field in the error body.

**`must_run_after`:** `["auth"]`

### Slot 4 — `schema_validator`

**Purpose:** Validates `input.body` against the channel's registered JSON Schema (fetched from the backing store via `get_channel_schema(namespace, channel)`). Short-circuits with `VALIDATION_FAILED` error on schema violation. See §3 for the `schema_validator` contract.

**MUST run:** After `auth` (slot 2) and before `store_dispatch` (slot 6). Validation must use verified identity context to scope channel lookups; schema validation must occur before persistence to prevent malformed messages from reaching the backing store.

**Default-on:** The `schema_validator` slot is **enabled by default** in the reference deployment. Disabling it is permitted for performance-sensitive deployments where producers are trusted; operators MUST document this configuration choice. See §3.

**`must_run_after`:** `["auth"]`
**`must_run_before`:** `["store_dispatch"]`

### Slot 5 — `idempotency`

**Purpose:** Checks the idempotency cache for duplicate `send` calls using the caller-supplied `correlation_id`. Short-circuits with the cached result if a valid entry exists, so that duplicate sends never reach the backing store.

**MUST run:** Before `store_dispatch` (slot 6). Idempotency deduplication only prevents double-write if it runs before the write.

**`must_run_before`:** `["store_dispatch"]`

**Note:** This slot reads `context.correlation_id` (frozen; set at ingress). It MUST NOT modify `correlation_id`.

### Slot 6 — `store_dispatch`

**Purpose:** Calls the backing store. This is the **only slot in the default chain that performs persistence** — the only slot with authority to read or write the `BackingStore` port (`spec/ports/backing-store.md`).

**MUST run:** After all upstream validation and auth slots. Must be the sole persistence point; any other slot that performs backing-store writes is a conformance violation.

**No short-circuit:** `store_dispatch` MUST NOT short-circuit under normal operation. It calls the backing store and returns the result to the response path.

**`must_run_after`:** `["auth", "schema_validator", "idempotency"]`

### Slot 7 — `audit_log`

**Purpose:** Writes a structured log entry for every tool call: operation, agent_id, namespace, correlation_id, timestamp, outcome. Runs on the **response path** after `store_dispatch`, so that the log entry captures the final outcome.

**MUST run:** On the response path, after the backing store returns. Running on the request path would produce log entries before the outcome is known.

**Observe-only by convention:** The `audit_log` slot MUST NOT mutate the response. It is semantically equivalent to an interceptor with `observe_only: true`.

**`must_run_after`:** `["store_dispatch"]` (response path)

---

## 3. `schema_validator` — Contract

The `schema_validator` middleware implements the following normative contract:

1. On each `send` call, the unit MUST fetch the registered schema for the target channel via `get_channel_schema(namespace, channel)`.
2. If no schema is registered (`null`), the unit MUST pass through without validation. Absence of a schema is not an error.
3. If a schema is registered, the unit MUST validate `input.body` against it using JSON Schema draft 2020-12.
4. On validation failure, the unit MUST short-circuit with error code `VALIDATION_FAILED` and a structured error body listing all constraint violations.
5. On validation success, the unit MUST pass through to `store_dispatch`.

The backing store is explicitly forbidden from performing body validation — it MUST be schema-agnostic. Only the `schema_validator` slot enforces channel schemas. Duplicating validation at the backing store level is not permitted and would create a split-authority conflict.

**Default-on:** The reference deployment ships with `schema_validator` enabled. Disabling it silently accepts malformed messages on typed channels; operators MUST document this configuration choice in their deployment records if they disable it.

**Performance-sensitive deployments:** A deployment where all producers are trusted and validated at the source MAY disable `schema_validator` for throughput. The capability string `schema_validator` MUST still appear in the chain slot; it may be filled with a pass-through unit. The chain MUST NOT skip the slot entirely, to preserve the ordering invariants that subsequent slots depend on.

---

## 4. Deviation from `DEFAULT_ORDER`

Implementations MAY deviate from `DEFAULT_ORDER` for specific use cases. All deviations MUST be:

1. **Documented** — the deployment's operational runbook or configuration must explicitly name the deviation and its rationale.
2. **Non-regressive on security** — deviations MUST NOT allow any operation to reach `store_dispatch` without passing through `auth`. This is the non-negotiable security invariant. Moving `rate_limit` or `schema_validator` is permitted; moving `auth` to after `store_dispatch` is not.
3. **Conformance-tested** — the conformance suite (`08-conformance.md`) MUST be run against any non-standard ordering and MUST pass all security-critical checks.

The most common safe deviations:

| Deviation | Safe? | Notes |
|---|---|---|
| Removing `rate_limit` | Yes (functionally) | No security impact; reduces protection against abuse. Document. |
| Removing `schema_validator` | Yes (if trusted producers) | No security impact; allows malformed messages. Document. |
| Moving `audit_log` before `store_dispatch` | Yes | Log entry will not capture outcome. Document the limitation. |
| Removing `auth` | **No** | Security misconfiguration. Forbidden in production. |
| Moving `auth` after `store_dispatch` | **No** | Allows unauthenticated backing-store access. Forbidden. |
| Moving `namespace_resolver` after `auth` | **No** | `auth` requires namespace context to scope credential lookups. |

---

## 5. Plugin Integration with the Default Chain

Third-party plugins may insert themselves into the default chain using the ordering constraint fields in their manifest (`must_run_before`, `must_run_after`). The capability strings in `DEFAULT_ORDER` are the normative anchor points:

- A plugin that must run before persistence: `must_run_before: ["store_dispatch"]`
- A plugin that must run after authentication: `must_run_after: ["auth"]`
- A plugin that provides a custom rate-limiter: `plugin_capabilities: ["rate_limit"]`

When a plugin fills a default-chain slot (by providing its capability string), the built-in implementation of that slot is replaced. The host MUST NOT run both the built-in unit and the plugin unit for the same slot.

See `03-plugin-contract.md` §4.3 for the complete capability-string resolution rules.
