---
phase_id: 01-extract
title: Extract protocol spec from current implementation
agent: api-designer
profile: spec
estimated_effort: 2-3 days
prereqs: []
unblocks: [02-review]
parallelizable_with: []
writes: ["spec/**", "docs/adr/**", "README.md"]
reads:  ["spec/**", "docs/CONTRACTS.md", "docs/DESIGN.md", "packages/python/src/**", "TODO.md", ".workflow/plans/bucket-classification/classified.json"]
context_size: large
---

# 01 — Extract spec

## Objective

Lift the protocol-level concepts out of `packages/python/src/sox_protocol/` into a language-agnostic `spec/` directory. Audit and complete what already exists in `spec/`. Produce JSON Schemas for every operation envelope and protocol primitive. Write the ADR formalizing the protocol-vs-implementation split.

## Inputs

- `/Users/nix/dev/ai/sox-protocol/packages/python/src/sox_protocol/` — current Python implementation; lift protocol semantics from here
- `/Users/nix/dev/ai/sox-protocol/spec/` — existing spec directory (audit + extend)
- `/Users/nix/dev/ai/sox-protocol/docs/CONTRACTS.md`, `docs/DESIGN.md` — design docs that already encode much of the protocol
- `/Users/nix/dev/ai/sox-protocol/TODO.md` — bucket-classified backlog; the items tagged `protocol` are the spec surface
- `/Users/nix/dev/ai/sox-protocol/.workflow/plans/bucket-classification/classified.json` — machine-readable classification

## Prompt (verbatim)

```text
You are establishing SOX Protocol's canonical, language-agnostic spec surface. SOX is a real-time many-to-many messaging protocol where LLM agents are first-class peers (channels, groups, threads, presence, ACK/NACK, DMs).

Your job: lift everything currently encoded only in Python into language-neutral spec artifacts under `spec/`. Audit and extend what's already there. Produce JSON Schemas for every operation and envelope. Write the ADR.

READ FIRST:
- /Users/nix/dev/ai/sox-protocol/spec/ — entire directory tree
- /Users/nix/dev/ai/sox-protocol/docs/CONTRACTS.md
- /Users/nix/dev/ai/sox-protocol/docs/DESIGN.md
- /Users/nix/dev/ai/sox-protocol/packages/python/src/sox_protocol/core/ — protocol-level code; not adapters/
- /Users/nix/dev/ai/sox-protocol/.workflow/plans/bucket-classification/classified.json — every TODO item tagged protocol/pitch/implementation. The protocol-tagged items are scope here.

DELIVERABLES (under spec/):

1. spec/protocol.md — top-level overview. The four core operations (send/recv/subscribe/list_channels). Message envelope shape. The novelty claim ("group chat for LLM agents"). One screen, links into the rest.

2. spec/primitives/ — one file per primitive. At minimum: channels.md, groups.md, dms.md, threads.md, presence.md, ack-nack.md, pending-state.md, sequence-numbers.md, trace-ids.md. Each describes the concept, its operations, its state, and its interaction with other primitives.

3. spec/ports/ — port interfaces (behaviour contracts, not language-specific):
   - transport.md (existing or new — audit)
   - backing-store.md (existing — audit, extend if needed)
   - identity.md (NEW — describes the *guarantee* of verified sender; credential primitive is implementation-defined)
   - middleware.md (NEW — describes the inspect/mutate/short-circuit pipeline; specific framework is implementation-defined)

4. spec/state-machines/ — message lifecycle (sent → delivered → acked → replied/nacked) and agent presence states. Mermaid diagrams welcome but not required.

5. spec/envelopes/ — JSON Schema 2020-12 for every reserved body type:
   - sox-ack.schema.json
   - sox-nack.schema.json
   - sox-error.schema.json
   - sox-invite.schema.json

6. spec/operations/ — JSON Schema 2020-12 for every tool's request and response:
   - send.input.schema.json, send.output.schema.json
   - recv.input.schema.json, recv.output.schema.json
   - subscribe.input.schema.json, subscribe.output.schema.json
   - list_channels.input.schema.json, list_channels.output.schema.json

7. docs/adr/0001-protocol-vs-implementation-split.md — ADR explaining the split:
   - Context: SOX wants to be a protocol, not a Python library. Need a clear line between spec and reference impl.
   - Decision: spec/ is canonical and language-neutral; packages/python is one reference implementation; transport, store, identity, middleware are ports.
   - Consequences: cross-language implementations possible; conformance suite consumes spec/ schemas; impl-only changes don't bump spec version.

8. Update top-level README.md: add a "What is in spec/" callout near the top so visitors understand the layering. Keep changes minimal — bigger README rewrite is `launch-narrative`.

HARD CONSTRAINTS:

- Do NOT touch packages/. This phase is spec-only.
- spec/ MUST contain zero references to "packages/" — `grep -r packages/ spec/` must be empty.
- Spec is language-neutral: no Python ABCs, no Rust traits. Behaviour contracts only.
- Every JSON Schema has $schema, $id, title, type, required, properties, additionalProperties: false, examples block.
- If a contract is ambiguous in CONTRACTS.md, file a TODO comment in the schema rather than guessing.
- Use {{placeholder}} syntax for any concrete tool names that vary by adapter (e.g. mcp__sox__channels__send → {{send_tool}}). Spec stays neutral; install adapters substitute.

ACCEPTANCE (self-check):
- [ ] All seven spec/ deliverables produced
- [ ] All schemas validate as JSON Schema 2020-12
- [ ] grep -r packages/ spec/ returns nothing
- [ ] ADR committed at docs/adr/0001-...

REPORT: a one-paragraph summary plus a tree of spec/ plus the first ~10 lines of each schema for verification.
```

## Exit criteria

Universal (`spec` profile):
- [ ] `npx ajv compile -s 'spec/operations/*.json' --spec=draft2020 && npx ajv compile -s 'spec/envelopes/*.json' --spec=draft2020`
- [ ] `! grep -rn 'packages/' spec/`
- [ ] `npx markdownlint 'spec/**/*.md'`

Engagement-specific:
- [ ] `test -f spec/protocol.md`
- [ ] `for f in channels groups dms threads presence ack-nack pending-state sequence-numbers trace-ids; do test -f spec/primitives/$f.md || exit 1; done`
- [ ] `for f in transport backing-store identity middleware; do test -f spec/ports/$f.md || exit 1; done`
- [ ] `for f in send recv subscribe list_channels; do test -f spec/operations/$f.input.schema.json && test -f spec/operations/$f.output.schema.json || exit 1; done`
- [ ] `for f in sox-ack sox-nack sox-error sox-invite; do test -f spec/envelopes/$f.schema.json || exit 1; done`
- [ ] `test -f docs/adr/0001-protocol-vs-implementation-split.md`

## Outputs

- `spec/` (extended)
- `docs/adr/0001-protocol-vs-implementation-split.md`
- `README.md` (minor update)

## Next state

Promote `02-review` → READY.
