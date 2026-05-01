<!-- SPDX-License-Identifier: Apache-2.0 -->
# Middleware Port — Conformance Criteria

**Version:** 1.0
**Status:** Normative
**Scope:** Language-neutral. This document specifies the conformance checklist for middleware pipeline implementations and provides pointers to the `plugin-contract/` fixture suite.

**Related:**
- `spec/ports/middleware/01-context.md` — context object invariants tested by the checklist
- `spec/ports/middleware/02-pipeline.md` — pipeline flow and short-circuit semantics tested by the checklist
- `spec/ports/middleware/03-plugin-contract.md` — plugin contract; the fixture suite exercises its normative requirements
- `spec/ports/middleware/07-default-chain.md` — default chain order requirements tested by the checklist
- `spec/conformance/README.md` — conformance suite overview, harness invocation, pending-fixture semantics
- `spec/conformance/plugin-contract/` — fixture directory; 7 YAML fixtures for the plugin contract (pending until P4 + P5 ship)

---

## 1. Pipeline Conformance Checklist

A middleware pipeline implementation is conformant when all of the following conditions hold. Each item is independently verifiable.

### 1.1 Default Chain Ordering

- [ ] `namespace_resolver` runs before `auth` in the default chain.
- [ ] `auth` (identity middleware) runs before all other chain links that follow it and sets `context.agent_id` from a verified credential.
- [ ] `schema_validator` is present in the default chain and defaults to enabled.
- [ ] `store_dispatch` is the only slot that performs backing-store reads or writes.
- [ ] `audit_log` runs on the response path after `store_dispatch`.

### 1.2 Context Invariants

- [ ] No middleware unit overwrites `context.correlation_id` or `input.correlation_id`.
- [ ] `context.agent_id` is not changed by any unit after the identity middleware sets it.
- [ ] The pipeline is reentrant: concurrent tool calls do not share `MiddlewareContext` objects.

### 1.3 Short-Circuit Semantics

- [ ] Short-circuit responses conform to the relevant output schema for the operation.
- [ ] A unit that short-circuits does not forward the call to the next unit.
- [ ] `ShortCircuitResponse` is not logged as an error condition.

### 1.4 Error Handling

- [ ] Internal errors produce `sox-error` envelopes with `error_code: "internal_error"`, not implementation-specific exceptions surfaced to the caller.
- [ ] Validation errors produce `sox-error` envelopes with `error_code: "VALIDATION_FAILED"` (not `internal_error`).
- [ ] The pipeline order is documented; any deviation from `DEFAULT_ORDER` is documented and tested.

### 1.5 Security Invariants

- [ ] The conformance suite asserts the default chain refuses an unauthenticated `send`.
- [ ] No path through the pipeline allows `store_dispatch` to be reached without passing through `auth`.
- [ ] Removing `auth` from the chain is documented as a security misconfiguration, not a supported operation.

---

## 2. Plugin Contract Conformance Checklist

A host implementation's plugin contract is conformant when all of the following conditions hold. Each item maps to a normative section of `03-plugin-contract.md`.

### 2.1 Manifest Validation (`03-plugin-contract.md` §5)

- [ ] Every discovered manifest is validated against `spec/schemas/sox-plugin.schema.json` before factory instantiation.
- [ ] A manifest failing schema validation produces `plugin_manifest_invalid` and does not proceed to load.

### 2.2 Version Negotiation (`06-versioning.md`)

- [ ] Both PEP 440 and npm semver range forms are accepted for `spec.protocol_version`.
- [ ] The compatibility check occurs at plugin load time during startup; lazy refusal is not used.
- [ ] A version mismatch produces the five-field `plugin_protocol_version_mismatch` envelope.
- [ ] A mismatched plugin is not instantiated.

### 2.3 Allowlist (`03-plugin-contract.md` §6)

- [ ] In production mode, plugins not in the allowlist are not loaded.
- [ ] `plugin_not_allowed` is produced for discovered-but-not-allowlisted plugins.
- [ ] `plugin_not_found` is produced for allowlisted-but-missing plugins.

### 2.4 Ordering (`03-plugin-contract.md` §4)

- [ ] Kahn's topological sort with lexicographic plugin-id tie-break is used.
- [ ] A cycle produces `plugin_ordering_cycle` naming all cycle members.
- [ ] The order is computed once at startup and cached; not recomputed per request.

### 2.5 Failure Semantics (`03-plugin-contract.md` §3)

- [ ] Interceptor exceptions produce `internal_error` envelopes.
- [ ] Transformer `ValidationError` exceptions produce `validation_failed` envelopes.
- [ ] Provider `on_startup` exceptions cause fail-fast with a non-zero exit code.
- [ ] Hook exceptions respect `SOX_HOOK_FAILURE_MODE`; default (unset) is `alarm`.

### 2.6 Capability Flags (`03-plugin-contract.md` §2.3)

- [ ] `observe_only: true` + `may_short_circuit: true` produces `plugin_capability_conflict` at startup.
- [ ] An `observe_only: true` interceptor that returns `ShortCircuitResponse` at runtime is converted to `internal_error` (not propagated as a short-circuit).

### 2.7 Observability (`03-plugin-contract.md` §8)

- [ ] Every dispatch response includes a `pipeline_trace` array in `metadata["pipeline_trace"]`.
- [ ] Each record contains: `plugin_id`, `kind`, `started_at`, `finished_at`, `verdict`, `correlation_id`.
- [ ] `error_code` is present in records where `verdict == "error"` and absent otherwise.

---

## 3. Plugin-Contract Fixture Suite

### 3.1 Location and Status

Conformance fixtures for the plugin contract are located at:

```
spec/conformance/plugin-contract/
├── 01-plugin-loads-via-entry-point.yaml
├── 02-version-mismatch-refused.yaml
├── 03-kind-taxonomy-enforced.yaml
├── 04-applies-to-scope.yaml
├── 05-must-run-before-after.yaml
├── 06-short-circuit-explicit.yaml
└── 07-provider-lifecycle-synthetic.yaml
```

All 7 fixtures carry `pending: true`. They are **skipped in `--strict` mode** (CI) until the following engagements ship:

- **P4 (`plugin-discovery-py`)** — wires the Python entry-point loader; unblocks fixtures 01, 02, 03, 04, 05, 06.
- **P5 (`reference-plugins`)** — ships the `io.sox.schema-strict` transformer; provides real-plugin context for fixture 03.
- The synthetic provider fixture (07) requires only a stub harness, which MUST be provided by P4.

When P4 and P5 are complete, `pending: true` MUST be removed from all fixtures that pass. Any fixture that cannot be un-skipped at that point MUST have a documented reason explaining why it remains pending.

### 3.2 Fixture Descriptions

| Fixture | Spec reference | What it verifies |
|---|---|---|
| `01-plugin-loads-via-entry-point.yaml` | `03-plugin-contract.md` §5; `05-discovery.md` §2 | A plugin registered via Python `importlib.metadata` entry-point is discovered, validated, and loaded successfully |
| `02-version-mismatch-refused.yaml` | `06-versioning.md` §4–§5 | A plugin declaring an incompatible `protocol_version` range produces the five-field `plugin_protocol_version_mismatch` envelope and is not instantiated |
| `03-kind-taxonomy-enforced.yaml` | `03-plugin-contract.md` §2.3 | An interceptor declaring `observe_only: true` that returns `ShortCircuitResponse` at runtime produces `internal_error`, not a short-circuit response |
| `04-applies-to-scope.yaml` | `03-plugin-contract.md` §2; `04-manifest.md` §4.4 | A plugin scoped to `applies_to: ["send"]` is invoked for `send` operations and not invoked for `recv` operations |
| `05-must-run-before-after.yaml` | `03-plugin-contract.md` §4 | `must_run_before` and `must_run_after` ordering constraints produce the declared execution order; a cycle produces `plugin_ordering_cycle` |
| `06-short-circuit-explicit.yaml` | `03-plugin-contract.md` §2.1.1, §3.1 | An interceptor declaring `may_short_circuit: true` that raises `ShortCircuitResponse` halts the pipeline; downstream units are not invoked; `pipeline_trace` verdict is `"short_circuit"` |
| `07-provider-lifecycle-synthetic.yaml` | `03-plugin-contract.md` §2.2.1, §10.3 | A synthetic in-memory provider plugin records `on_startup` and `on_shutdown` invocations; the fixture asserts both were called in correct order, bracketing the host lifespan (NR-2 per `suggestions-v2.md` §Q6) |

### 3.3 Running the Fixtures

Once P4 ships:

```bash
# Run plugin-contract fixtures only (expect 7 skipped until pending removed)
python3 tools/conformance_runner.py \
  --target packages/python \
  --category plugin-contract \
  --strict

# Run full suite (existing 32 + 7 new pending = 32 passed, 7 skipped in --strict)
python3 tools/conformance_runner.py --target packages/python --strict
```

The existing 32 conformance fixtures MUST continue to pass after the `plugin-contract/` directory is added. Adding pending fixtures MUST NOT break the strict-mode pass count.

### 3.4 Cross-Language Requirement

Plugin-contract fixtures are **cross-language**. Both the Python reference implementation and any future TypeScript implementation (engagement P6, `plugin-architecture-ts`) MUST pass all non-pending fixtures. The fixture format is language-neutral YAML; no fixture file references Python-specific or TypeScript-specific constructs.
