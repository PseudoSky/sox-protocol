---
slug: spec-extraction
state: initialized
bucket: protocol
stream: A
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: critical
unblocks: [conformance-suite, defensive-publication, launch-narrative]
depends_on: [bucket-classification]
---

# Engagement: spec-extraction

## Objective
Extract a language-agnostic protocol spec from the current Python implementation. Reorganize the repo so `spec/` is the product and `packages/python/` is one reference implementation.

## Acceptance criteria
- [ ] `spec/protocol.md` — top-level protocol overview, message envelope shape, the four core operations
- [ ] `spec/primitives/` — one file per primitive: channels, groups, dms, threads, presence, ack-nack, pending-state, sequence-numbers, trace-ids
- [ ] `spec/ports/` — port interfaces: `transport.md`, `backing-store.md`, `identity.md`, `middleware.md`. (Some already exist — audit and complete.)
- [ ] `spec/state-machines/` — message lifecycle (sent → delivered → acked → replied/nacked), agent presence states
- [ ] `spec/envelopes/` — JSON Schema for every reserved body type: `sox/ack`, `sox/nack`, `sox/error`, `sox/invite`
- [ ] `spec/operations/` — JSON Schema for every tool's request/response (send, recv, subscribe, list_*)
- [ ] Spec is decoupled from MCP — describes operations and shapes, not MCP-specific bindings. MCP is one transport adapter.
- [ ] Top-level README updated to position `spec/` as canonical; `packages/python/` as reference impl
- [ ] Spec is licensed CC-BY-4.0 or Apache 2.0 with explicit notice

## Inputs
- `packages/python/src/sox_protocol/` (current implementation)
- Existing `spec/` directory (audit + extend)
- Bucket-classification output (knows what's protocol)

## Outputs
- Restructured `spec/` directory
- ADR at `docs/adr/0001-protocol-vs-implementation-split.md`
- Migration notes for any rename in `packages/python/`

## Suggested executor
`api-designer` for spec docs + JSON schemas; `architect-reviewer` for ADR.

## State transitions
- 2026-04-29 initialized — workflow-architect
