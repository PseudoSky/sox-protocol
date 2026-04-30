# ADR 0001 — Protocol vs Implementation Split

**Date:** 2026-04-30  
**Status:** Accepted  
**Authors:** SOX Protocol maintainers

---

## Context

SOX Protocol's goal is to be a runtime-agnostic specification for peer N:N messaging among LLM agents — not a Python library. The core value proposition ("group chat for LLM agents with a documented speculative-execute-and-reconcile discipline") must be implementable in any language and on any LLM runtime.

At the time this ADR was recorded, the entire protocol was encoded implicitly in a single Python reference implementation (`packages/python/`). The spec directory (`spec/`) existed but was incomplete: it had JSON Schemas for the enforcer internals and tool I/O, plus a backing-store port contract in prose, but lacked:

- A top-level protocol overview.
- Primitive-level documentation (channels, groups, DMs, threads, presence, ACK/NACK, pending state, sequence numbers, trace IDs).
- Port contracts for transport, identity, and middleware.
- State machines for the message lifecycle and agent presence.
- Normative schemas for reserved envelope body types.
- A canonical, language-neutral home for all four operation schemas.
- An explicit statement of what constitutes the "spec" vs what is "one implementation."

Without a clear split, every Python design decision implicitly became a protocol decision. Adding a TypeScript or Rust port would require reverse-engineering intent from Python code. The conformance suite could not be the authority it was designed to be.

---

## Decision

**`spec/` is the canonical, language-neutral specification for SOX Protocol. `packages/<lang>/` are reference implementations of that specification.**

Specifically:

### 1. `spec/` is authoritative

Everything in `spec/` — JSON Schemas, markdown port contracts, primitive specs, state machines, the discipline document, and the conformance suite — defines SOX Protocol independently of any language. If `spec/` and any language-specific artefact disagree, `spec/` wins.

The protocol version lives in `spec/VERSION`. Bumping the protocol version requires a change to `spec/`, not to any package.

### 2. Four categories of port

The protocol surface is divided into four named ports, each with a normative behaviour contract in `spec/ports/`:

| Port | File | Direction | Description |
|---|---|---|---|
| BackingStore | `spec/ports/backing-store.md` | South / driven | Persistence boundary |
| Transport | `spec/ports/transport.md` | South / driven | Wire delivery layer |
| Identity | `spec/ports/identity.md` | North / driving | Verified sender guarantee |
| Middleware | `spec/ports/middleware.md` | North / driving | Inspect/mutate/short-circuit pipeline |
| DisciplineRenderer | `spec/ports/runtime-discipline-renderer.md` | North / driving | Prompt surface injection |
| EnforcerBinding | `spec/ports/runtime-enforcer-binding.md` | North / driving | Lifecycle-event wiring |

### 3. `spec/` contains zero implementation references

`spec/` MUST contain zero references to `packages/`. No file under `spec/` may import, link to, or assume the existence of any language-specific artefact. Language bindings (Python ABCs, TypeScript interfaces, Rust traits) are implementation details that express the port contracts in the implementation's idiom.

### 4. `packages/python/` is one reference implementation

`packages/python/` is the v1.0 reference implementation. It is SOX-conformant by construction and is the first to pass the `spec/conformance/` suite. It is not the definition of the protocol; it is a demonstration of it.

### 5. Implementation-only changes do not bump the spec version

A change that only affects `packages/python/` (bug fix, performance improvement, adapter addition) does not change `spec/VERSION`. A change that alters the wire format, semantics, or port contracts MUST change `spec/VERSION` and update all relevant schema and prose files in `spec/`.

### 6. The conformance suite is the verification authority

An implementation is "SOX v1.0-compliant" when it passes all scenarios in `spec/conformance/scenarios/` via `spec/conformance/runner/run.sh`. The suite tests wire-level correctness against the JSON Schemas in `spec/`. It does not test performance, operational characteristics, or adapter quality.

---

## Consequences

### Positive

- **Cross-language implementations are possible.** A TypeScript or Rust port can be built entirely from `spec/` without reading Python code. The port contracts define exactly what must be implemented.
- **Conformance suite is reusable.** `spec/conformance/` is Docker-based and language-agnostic. Any implementation can run it without modification.
- **Spec versioning is decoupled from implementation release cadence.** Python patch releases do not trigger spec version bumps; spec changes are deliberate protocol decisions.
- **Clearer contribution model.** Protocol proposals go to `spec/`; implementation improvements go to `packages/<lang>/`. Reviewers can reason about each in isolation.
- **No accidental protocol lock-in.** Because `spec/` has no language syntax, no Python-ism can accidentally become a protocol requirement.

### Negative / risks

- **Spec drift.** If `packages/python/` evolves without updating `spec/`, the two can diverge. Mitigation: CI runs `grep -r packages/ spec/` (must be empty) and runs the conformance suite against the Python reference on every push.
- **Maintenance overhead.** Port contracts in `spec/` must be updated whenever the Python implementation changes a behavioural guarantee. This requires discipline from contributors.
- **Spec completeness lag.** At the time this ADR was written, `spec/` was being brought to parity with the implicit Python implementation. This is a one-time cost; going forward, the spec leads the implementation.

### Neutral

- The Python ABC files in `packages/python/src/sox_protocol/core/ports/` remain as language bindings of the spec; they are not the spec themselves. Docstrings in those files cite the relevant `spec/ports/*.md` section; in case of disagreement, the `spec/ports/*.md` file wins.

---

## Alternatives considered

### A. Python code as the spec

Treat the Python ABCs and dataclasses as the normative spec and generate documentation from them. Rejected: Python syntax is not language-neutral; this locks out non-Python implementations and makes protocol decisions inseparable from implementation decisions.

### B. OpenAPI / AsyncAPI as the primary spec format

Use a standard API description format instead of JSON Schema + markdown. Rejected: SOX is not an HTTP API. MCP tool calls are closer to RPC than REST. JSON Schema 2020-12 covers the wire types; prose markdown covers the behavioural contracts that no machine-readable format captures well (atomicity, ordering, delivery semantics). The two together are more expressive than a single OpenAPI document.

### C. Single monorepo with no spec/packages split

Keep everything in one flat directory. Rejected: makes cross-language porting impossible and turns every library release into an implicit spec version bump.

---

## References

- `spec/protocol.md` — top-level overview
- `spec/ports/` — all six port behaviour contracts
- `spec/conformance/` — conformance suite
- `docs/CONTRACTS.md` — narrative mirror of the spec (non-normative)
- `docs/DESIGN.md §4` — architecture layers and adapter model
