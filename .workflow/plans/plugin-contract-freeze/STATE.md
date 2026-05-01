---
slug: plugin-contract-freeze
target: Freeze the plugin contract in spec — sufficient to unblock downstream implementation work (plugin-discovery-py, reference-plugins, plugin-architecture-ts). ADR 0004; sox-plugin.yaml JSON Schema; plugin-contract spec section (kinds + failure semantics + ordering algorithm); versioning rules. Does NOT include directory restructure or conformance fixtures (that's plugin-spec-polish).
created: 2026-05-01
last_event: 2026-05-01T15:00:00Z
orchestrator_protocol: v1
parent_plan: plugin-architecture
supersedes: plugin-manifest-spec (split into B1 contract-freeze + B2 spec-polish per analysis §7.6)
---

# plugin-contract-freeze — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-adr | Draft ADR 0004 — plugin architecture (4-kind 2-axis taxonomy; manifest envelope; versioning; supply-chain stance; v1 limitations including no-hot-reload) | `DONE` | architect-reviewer | 1 | 2026-05-01T15:00:00Z |
| 02-manifest-schema | Author `spec/schemas/sox-plugin.schema.json` (Backstage-style apiVersion/kind/metadata/spec envelope) + ADR cross-reference | `DONE` | api-designer | 1 | 2026-05-01T15:00:00Z |
| 03-plugin-contract | Author `spec/ports/middleware/03-plugin-contract.md` — kind taxonomy normative semantics, failure-semantics-per-kind, must_run_before/after topological-sort algorithm with cycle detection, allowlist requirement | `DONE` | api-designer | 1 | 2026-05-01T16:30:00Z |
| 04-versioning | Author `spec/ports/middleware/06-versioning.md` — PEP 440 wire form, semver range semantics, boot-time refusal envelope shape | `DONE` | api-designer | 1 | 2026-05-01T15:00:00Z |
| 05-review | Architectural review for cross-language portability (Python + TS without language-specific magic) | `DONE` | architect-reviewer | 1 | 2026-05-01T17:30:00Z |

## Currently next action

`01-adr` is `READY`. Wait for second workflow-optimizer pass on the umbrella parent before dispatching planner.

## Termination targets — what "frozen" means

- [ ] `docs/adr/0004-plugin-architecture.md` committed
- [ ] `spec/schemas/sox-plugin.schema.json` validates against draft-07 metaschema; round-trip-tested with three sample manifests (one per kind: interceptor, transformer, provider)
- [ ] `spec/ports/middleware/03-plugin-contract.md` defines:
  - 4-kind 2-axis taxonomy (interceptor / transformer on wire; provider / hook on lifecycle) with each kind's contract + failure-mode normative defaults
  - `interceptor` capability flags (observe_only, may_short_circuit) with runtime contract assertions
  - `must_run_before/after` resolution: stable Kahn topological sort, lexicographic-id tie-break, cycle → `plugin_ordering_cycle` error at startup with cycle named in message
  - Failure semantics per kind (interceptor → internal_error; transformer → validation_failed; provider startup → fail-fast; hook → swallow + log)
- [ ] `spec/ports/middleware/06-versioning.md` defines: single `protocol_version` semver range (PEP 440 wire form), boot-time refusal envelope, pre-release marker rules, `signatures: []` reserved field
- [ ] **Sufficient by itself for `plugin-discovery-py` and `reference-plugins` to start.** No further B-scope work needed before C/D begin.

## Design decisions ratified (per analysis §7)

- 4-kind 2-axis taxonomy: `interceptor`, `transformer` (wire) + `provider`, `hook` (lifecycle). Guard collapses into Interceptor (returns deny via ShortCircuitResponse).
- Manifest envelope: Backstage-style `apiVersion: sox.dev/v1` + `kind: SoxPlugin` + `metadata.{id,version}` + `spec.{...}`.
- Entry-point hints OUT of manifest body — live in language-specific package metadata (Python `pyproject.toml [entry-points]`, Node `package.json#sox`).
- `protocol_version`: single semver range, PEP 440 wire form (`>=1.0,<2.0`), boot-time refusal.
- `signatures: []` reserved (empty in v1, hash-pinning in v1.x, in-band sig in v2.0).
- `--allow-plugins` CLI allowlist mandatory for production.
- Failure semantics per kind normatively defined (per §7.5 risk #2).
- Composition is static at startup in v1; spec note explicitly forbids implementations from depending on stable Pipeline identity across reloads (§7.5 risk #4 hot-reload deferral).
- `sox.yaml` config descope — env-vars-only for v1 (`SOX_PLUGIN_<id>_<key>`); `sox.yaml` deferred to v1.x.
- `pipeline_trace` structured array in `metadata` for observability (§7.5 risk #7).

## Out-of-scope — handled by sibling engagements

- Directory restructure of `spec/ports/middleware.md` → `spec/ports/middleware/` — `plugin-spec-polish` (B2)
- 6 conformance fixtures — `plugin-spec-polish` (B2)
- Cross-references between docs — `plugin-spec-polish` (B2)

## Transitions

- 2026-05-01T15:30:00Z 01-adr — DONE (architect-reviewer)
- 2026-05-01T16:00:00Z 02-manifest-schema — DONE (api-designer)
- 2026-05-01T16:30:00Z 03-plugin-contract — DONE (api-designer)
- 2026-05-01T17:00:00Z 04-versioning — DONE (api-designer)
- 2026-05-01T17:30:00Z 05-review — DONE (architect-reviewer)

## Reference

See parent analysis at [`../plugin-architecture/analysis.md`](../plugin-architecture/analysis.md) §7 (revised) for full scope and rationale.
