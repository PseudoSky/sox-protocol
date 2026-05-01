<!-- SPDX-License-Identifier: Apache-2.0 -->
# Middleware Port — Directory Index

**Version:** 1.0
**Status:** Normative
**Scope:** Language-neutral. This directory is the authoritative specification for the SOX Protocol middleware pipeline, plugin contract, discovery mechanism, versioning, and conformance requirements.

---

## Purpose

The **Middleware** port specifies a composable pipeline through which every tool call passes before reaching the backing store. Middleware units may inspect, mutate, or short-circuit requests and responses. On top of this pipeline, the **Plugin Architecture** (ADR 0004) defines a portable, allowlisted, versioned mechanism for third-party extensions.

This directory supersedes the single-file `spec/ports/middleware.md` (now a redirect stub). All normative content is in the files listed below.

---

## File Index

| File | Status | Summary |
|---|---|---|
| `01-context.md` | Normative | Port purpose, `MiddlewareContext` shape, structural rules |
| `02-pipeline.md` | Normative | Left-to-right flow, short-circuit semantics, mutability constraints, error handling |
| `03-plugin-contract.md` | Normative (B1 — candidate) | Four plugin kinds, failure semantics per kind, ordering algorithm, allowlist, configuration, observability, v1 limitations |
| `04-manifest.md` | Normative | `sox-plugin.yaml` envelope shape; schema and example references |
| `05-discovery.md` | Normative | Python entry-points, Node `package.json#sox`, programmatic registration, allowlist, `--no-discovery` |
| `06-versioning.md` | Normative (B1 — candidate) | `protocol_version` dual wire forms, compatibility algorithm, refusal envelope, signing reservation |
| `07-default-chain.md` | Normative | `DEFAULT_ORDER` constant, normative slot ordering, `schema_validator` default-on contract |
| `08-conformance.md` | Normative | Conformance criteria for pipeline implementations; pointer to `plugin-contract/` fixtures |

---

## Reading Guide

**Understanding the pipeline** — read `01-context.md` → `02-pipeline.md` → `07-default-chain.md` in order. These three files fully specify the pre-plugin pipeline.

**Writing a plugin** — read `03-plugin-contract.md` (contract and kinds) → `04-manifest.md` (how to write the manifest file) → `06-versioning.md` (how to declare protocol version compatibility) → `05-discovery.md` (how the host finds your plugin).

**Implementing a host** — all eight files are required reading. Pay special attention to `03-plugin-contract.md` §6 (allowlist), §4 (ordering algorithm), and §3 (failure semantics); `05-discovery.md` §4 (`--no-discovery`); and `08-conformance.md` for the acceptance checklist.

---

## Relationship to ADRs

- **ADR 0003** (`docs/adr/0003-extensibility-mechanism.md`) — ratified the hybrid middleware-plus-hooks model. The pipeline in `01-context.md` and `02-pipeline.md` is the direct implementation of that decision.
- **ADR 0004** (`docs/adr/0004-plugin-architecture.md`) — closes the open questions left by ADR 0003 (versioning, error propagation, hook execution, chain introspection). `03-plugin-contract.md` and `06-versioning.md` are the normative bodies of ADR 0004's decisions 1–9.

---

## Related Specifications

- `spec/ports/identity.md` — Identity port; the `auth` middleware in `07-default-chain.md` slot 2 implements this contract.
- `spec/ports/backing-store.md` — BackingStore port; the `store_dispatch` middleware in slot 6 is the sole pipeline component that touches the backing store.
- `spec/schemas/sox-plugin.schema.json` — Machine-readable companion to `03-plugin-contract.md` and `04-manifest.md`.
- `spec/conformance/plugin-contract/` — Conformance fixtures for the plugin contract (cross-language; `pending: true` until P4 + P5 ship).
