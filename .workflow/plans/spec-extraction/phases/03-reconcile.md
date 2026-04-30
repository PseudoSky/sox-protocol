---
phase_id: 03-reconcile
title: Reconcile spec with architecture decisions
agent: api-designer
profile: spec
estimated_effort: 1 day
prereqs: [01-extract]
unblocks: [02-review]
parallelizable_with: []
writes: ["spec/**", "docs/V1-SCOPE.md"]
reads:  ["spec/**", "docs/decisions/**", "docs/adr/**", "packages/python/src/sox_protocol/core/**"]
context_size: large
---

# 03 — Reconcile spec with architecture decisions

## Objective

`01-extract` produced a spec reverse-engineered from the pre-decision Python
implementation. Since then, 19 architecture decisions and 3 ADRs were made that
change or extend the protocol surface. This phase updates `spec/` to reflect
every decision, resolves all conflicts between the current spec and the decisions,
fills every gap, and produces `docs/V1-SCOPE.md` as the canonical v1 reference
document for all downstream planners and implementers.

## Inputs

- `/Users/nix/dev/ai/sox-protocol/spec/` — current spec (accurate to pre-decision implementation; contains conflicts and gaps)
- `/Users/nix/dev/ai/sox-protocol/docs/decisions/` — all 19 architecture decisions (authoritative; decisions win over current spec in all conflicts)
- `/Users/nix/dev/ai/sox-protocol/docs/adr/0001-protocol-vs-implementation-split.md`
- `/Users/nix/dev/ai/sox-protocol/docs/adr/0002-agent-identity-primitive.md`
- `/Users/nix/dev/ai/sox-protocol/docs/adr/0003-extensibility-mechanism.md`
- `/Users/nix/dev/ai/sox-protocol/packages/python/src/sox_protocol/core/` — ground truth for what is currently implemented (read-only; do NOT modify)

## Prompt (verbatim — do not paraphrase when dispatching)

```text
You are updating SOX Protocol's canonical spec to reflect architecture
decisions made after the initial spec extraction. The spec was previously
reverse-engineered from the Python implementation. Since then, 19
architecture decisions and 3 ADRs were made. Your job is to reconcile the
spec with those decisions.

READ FIRST (in this order):
1. /Users/nix/dev/ai/sox-protocol/docs/decisions/ — all 19 decision files
2. /Users/nix/dev/ai/sox-protocol/docs/adr/0002-agent-identity-primitive.md
3. /Users/nix/dev/ai/sox-protocol/docs/adr/0003-extensibility-mechanism.md
4. /Users/nix/dev/ai/sox-protocol/spec/ — entire current spec
5. /Users/nix/dev/ai/sox-protocol/packages/python/src/sox_protocol/core/ — what is currently implemented

RULE: Where the current spec conflicts with a decision, the decision wins.
Where the spec is silent on something a decision specifies, add it.
Where a decision defers something to post-v1, add a clearly marked
`> **Post-v1:** <rationale>` callout in the relevant spec section.

---

## CONFLICTS TO RESOLVE (spec currently contradicts these decisions)

**1. DM naming and enforcement** (docs/decisions/dm-semantics.md)
- Current spec: `agent:<recipient-id>` naming convention, no enforcement
- Decision: `dm/<sorted-pair-of-agent-ids>` (lexicographically sorted, e.g.
  `dm/agent-alpha~agent-beta`), server enforces two-party constraint
- Action: Rewrite `spec/primitives/dms.md` entirely. Remove all `agent:`
  channel references. Document the `dm/` naming convention, server-side
  enforcement semantics, and the privacy model. The `~` separator between
  agent IDs is the recommended delimiter (avoids `/` ambiguity).

**2. ACK/NACK mechanism** (docs/decisions/ack-mechanism.md)
- Current spec: ACK = SOX message with reserved `body.type: sox-ack`, sent
  over ordinary channels, appears in channel history and replay
- Decision: ACK = dedicated `channels__ack` tool; ACKs do NOT enter channel
  history; optional derived `sox/acks` channel for audit consumers
- Action: Rewrite `spec/primitives/ack-nack.md` to describe the tool model.
  The `spec/envelopes/sox-ack.schema.json` and `sox-nack.schema.json` remain
  valid but are now the body schemas for `channels__ack` tool responses, not
  for channel messages. Add `spec/operations/channels_ack.input.schema.json`
  and `channels_ack.output.schema.json`.

**3. Groups model** (docs/decisions/groups-model.md)
- Current spec: "Protocol does not maintain a membership list. Membership is
  implicit — an agent is 'in' a group when it has an active subscription."
- Decision: Group = managed channel under `group/<group-id>` prefix with
  server-maintained membership table; lifecycle verbs separate from messaging
  verbs (`group_create`, `group_invite`, `group_join`, `group_leave`,
  `group_list_members`)
- Action: Rewrite `spec/primitives/groups.md`. Document the managed channel
  model, the membership table contract, and the lifecycle verb semantics.
  Add `spec/operations/` schemas for each lifecycle verb.

**4. Sequence numbers** (docs/decisions/seq-ordering-scope.md)
- Current spec `spec/primitives/sequence-numbers.md` states explicitly: "SOX
  does not use explicit integer sequence numbers in v1.0."
- Decision: Per-channel monotone `seq` counter (integer, starts at 1) on every
  message; optional advisory `ts` (server-assigned monotonic timestamp) for
  cross-channel display ordering
- Action: Rewrite `spec/primitives/sequence-numbers.md`. Add `seq` and `ts`
  to the wire envelope in `spec/protocol.md`. Update `recv` output schema to
  include `seq` on each message object.

**5. Presence and heartbeat** (docs/decisions/heartbeat-mechanism.md)
- Current spec `spec/primitives/presence.md` states: "no dedicated presence
  sub-protocol; no heartbeat or keep-alive mechanism is built into v1.0"
- Decision: Dedicated `channels__heartbeat` tool; server emits derived
  `sox/presence` channel of coalesced state-transitions (online/offline/busy)
- Action: Rewrite `spec/primitives/presence.md`. Add
  `spec/operations/channels_heartbeat.input.schema.json` and
  `channels_heartbeat.output.schema.json`.

---

## GAPS TO FILL (decisions made, spec currently silent)

**Wire envelope** — update `spec/protocol.md` envelope shape to add:
- `seq` (integer) — per-channel monotone counter
- `reply_to` (string | null) — message_id this message is replying to; used for threading
- `delivered_to` (string[] | null) — agent_ids that have recv'd this message; populated by server for deadlock detection
- `origin_server` (string | null) — server_id in federated deployments; null in single-server v1

**New operation schemas** — add to `spec/operations/`:
- `channels_ack.input.schema.json` — params: `message_id`, `status` enum (`received|processing|done|nack`), optional `reason`
- `channels_ack.output.schema.json` — confirmation shape
- `channels_heartbeat.input.schema.json` — params: `status` enum (`online|busy|offline`), optional `ttl`
- `channels_heartbeat.output.schema.json` — confirmation + server-assigned expiry
- `channels_collect.input.schema.json` — params: `reply_to` (message_id), `count` (integer), `timeout` (seconds), optional `status_filter`; mark with `"x-status": "planned"` and inline open-questions comment (quorum semantics, cancel verb, multiple collectors)
- `channels_collect.output.schema.json` — shape: `{received: Message[], missing: string[], timed_out: bool}`; mark with `"x-status": "planned"`
- `replay.input.schema.json` — params: `channel`, `since` (seq integer), `until` (seq integer | null), `limit`
- `replay.output.schema.json` — shape: `{messages: Message[], has_more: bool}`

**Updated operation schemas** — modify existing:
- `send.input.schema.json` — add `idempotency_key` (string | null, optional; server deduplicates within 24h TTL)
- `send.output.schema.json` — add `backpressure` object: `{queue_depth: int, threshold: int, state: "ok"|"warn"|"over"}`
- `recv.input.schema.json` — add `thread_depth` (integer, default 0; 0=message IDs only, n=n levels of reply chain, -1=full chain), add `include_meta` (bool, default true; false omits observability metadata)
- `list_channels.output.schema.json` — replace flat `protocol_version` string with structured `_sox_protocol` object: `{server_version: string, supported_versions: string[], min_client_version: string}`

**Port contracts** — update `spec/ports/`:
- `backing-store.md` — add: (a) all operations parameterised by `namespace` (string, default `"default"`); (b) `get_channel_schema(namespace, channel) -> JSONSchema | null`; (c) `set_channel_schema(namespace, channel, schema)`; (d) `sweep_idempotency_cache(ttl_seconds)` — mandatory operation, called periodically by server
- `transport.md` — add: (a) CORS requirement for HTTP binding; (b) long-poll or SSE requirement for `channels__collect` efficient implementation; note that stdio binding satisfies collect via asyncio blocking (no extra transport needed)

**Namespace isolation** — add `spec/primitives/namespace.md` documenting the `namespace` concept: every channel and message is tagged; `mode: shared` (WHERE clause) vs `mode: isolated` (separate DB/schema); default namespace is `"default"`; namespace-resolver middleware derives active namespace from principal

**Schema validation** — update `spec/ports/backing-store.md` with `get_channel_schema` / `set_channel_schema` (above); add a section to `spec/ports/middleware.md` documenting the `schema_validator` middleware as a default-on plugin

**Idempotency** — add a section to `spec/primitives/` or extend `spec/ports/backing-store.md` documenting the idempotency model: `idempotency_key` on send, 24h default TTL, `sweep_idempotency_cache` contract

**Version negotiation** — the `_sox_protocol` block change to `list_channels.output.schema.json` above covers this

**Replay access control** — add `replay_policy` field to channel config object in `spec/primitives/channels.md`: `subscriber | admin_only | custom`, default `subscriber`. Document that `replay` verb is gated by the same middleware chain as `recv` under `subscriber` policy.

**Observability** — add `include_meta` to recv.input (above). Document the `_meta` envelope extension in `spec/protocol.md`: optional object carrying `{trace_id, middleware_timings[], server_node_id}`; present when `include_meta: true` (default), absent when false.

**Backpressure** — `backpressure_mode` field on channel config: `advisory` (default) | `enforced`. Document in `spec/primitives/channels.md`. The send.output backpressure object (above) is always present regardless of mode.

**Deadlock detection** — document `delivered_to` field in envelope (above). Add a section to `spec/state-machines/` or `spec/primitives/` explaining wait-graph computation from `reply_to` + `delivered_to` at query time. Mark as a SHOULD-implement feature.

**Federation slot** — `origin_server` in envelope (above). Add a note to `spec/protocol.md` explaining the federation-aware design: `origin_server` is null in single-server v1 deployments; populated in federated v2. The identity structure `<server-id>/<agent-id>` should be documented in `spec/ports/identity.md` with the server-id portion being optional/implicit in v1.

---

## PRODUCE: docs/V1-SCOPE.md

This document is the canonical fast-path reference for all downstream planners,
implementers, and SDK authors. Format:

```markdown
# SOX Protocol — v1 Scope Reference

**Status:** Authoritative  
**Source:** spec/ (this document summarises; spec/ wins on conflict)

## Protocol operations (8 tools)

| Tool | Status | Brief |
|---|---|---|
| `{{send_tool}}` | v1 MUST | ... |
...

## Wire envelope

Every message has this shape: ...field table...

## Post-v1 (explicitly deferred)

- `channels__collect` — planned; quorum semantics unresolved; stdio-compatible but long-poll recommended for HTTP
- Groups lifecycle verbs — [if any deferred]
- [others]

## Key architecture decisions

| Concern | Decision | Spec location |
|---|---|---|
| Identity primitive | Ed25519 keypair (reference impl); spec describes guarantee only | spec/ports/identity.md, docs/adr/0002 |
| Extensibility | Middleware-primary hybrid; hooks are observation-only sugar | spec/ports/middleware.md, docs/adr/0003 |
| DM routing | dm/<sorted-pair> naming, server-enforced two-party | spec/primitives/dms.md |
...

## Port contract summary

What each port requires of implementers: ...
```

---

## HARD CONSTRAINTS

- Do NOT touch `packages/`. This phase is spec-only.
- `grep -r packages/ spec/` must return nothing for newly written or modified files.
- Spec is language-neutral. No Python ABCs, no Rust traits.
- Every JSON Schema: `$schema`, `$id`, `title`, `type`, `required`, `additionalProperties: false`, `examples` block.
- `channels__collect` schemas are REQUIRED but must carry `"x-status": "planned"` at the top level and an `"x-open-questions"` array field documenting: quorum semantics (count of ACKs vs count of any reply), cancel verb, multiple-collector semantics.
- The `delivered_to` and deadlock detection section must note it is a SHOULD-implement feature, not MUST.
- `origin_server` in envelope must be marked optional (`null` in v1 single-server deployments).

## ACCEPTANCE (self-check before reporting done)

- [ ] All 5 conflicts resolved — dms.md, ack-nack.md, groups.md, sequence-numbers.md, presence.md rewritten
- [ ] All 8 new operation schemas exist under spec/operations/ (channels_ack ×2, channels_heartbeat ×2, channels_collect ×2, replay ×2)
- [ ] send/recv/list_channels schemas updated with new fields
- [ ] Envelope in spec/protocol.md carries seq, reply_to, delivered_to, origin_server
- [ ] backing-store.md has namespace parameterisation + schema registry + idempotency sweep
- [ ] transport.md has CORS + long-poll/SSE notes
- [ ] spec/primitives/namespace.md exists
- [ ] docs/V1-SCOPE.md exists and covers all 8 operations, full envelope, post-v1 list, key decisions
- [ ] `grep -r packages/ spec/` returns nothing (new/modified files only)
- [ ] All JSON schemas are valid JSON

REPORT: one paragraph summary + count of files modified vs created + spec/operations/ tree.
```

## Exit criteria

Universal (`spec` profile):
- [ ] `npx ajv compile -s 'spec/operations/*.json' --spec=draft2020 && npx ajv compile -s 'spec/envelopes/*.json' --spec=draft2020`
- [ ] `! grep -rn 'packages/' spec/primitives/ spec/operations/ spec/ports/ spec/state-machines/ spec/protocol.md docs/V1-SCOPE.md`
- [ ] `npx markdownlint-cli2 'spec/primitives/*.md' 'spec/ports/*.md' 'spec/state-machines/*.md' 'spec/protocol.md' 'docs/V1-SCOPE.md'`

Engagement-specific:
- [ ] All 5 conflict files rewritten: `for f in dms ack-nack groups sequence-numbers presence; do test -f spec/primitives/$f.md || exit 1; done`
- [ ] All 8 new operation schemas present: `for f in channels_ack channels_heartbeat channels_collect replay; do test -f spec/operations/$f.input.schema.json && test -f spec/operations/$f.output.schema.json || exit 1; done`
- [ ] Updated schemas have new fields: `python3 -c "import json; s=json.load(open('spec/operations/send.input.schema.json')); assert 'idempotency_key' in s['properties'], 'missing idempotency_key'"`
- [ ] Updated schemas have new fields: `python3 -c "import json; s=json.load(open('spec/operations/send.output.schema.json')); assert 'backpressure' in s['properties'], 'missing backpressure'"`
- [ ] Updated schemas have new fields: `python3 -c "import json; s=json.load(open('spec/operations/recv.input.schema.json')); assert 'thread_depth' in s['properties'], 'missing thread_depth'"`
- [ ] list_channels has _sox_protocol block: `python3 -c "import json; s=json.load(open('spec/operations/list_channels.output.schema.json')); assert '_sox_protocol' in s['properties'], 'missing _sox_protocol'"`
- [ ] Namespace primitive exists: `test -f spec/primitives/namespace.md`
- [ ] V1 scope document exists: `test -f docs/V1-SCOPE.md`
- [ ] Envelope has new fields: `python3 -c "import json; t=open('spec/protocol.md').read(); assert 'seq' in t and 'reply_to' in t and 'delivered_to' in t and 'origin_server' in t, 'envelope missing fields'"`

## On verification failure

If markdownlint fails: most likely cause is missing blank lines around lists or unlabelled fenced code blocks. Add language tag (`json`, `text`) to all fenced blocks; ensure lists have blank lines before and after.

If schema validation fails: check `additionalProperties: false` is present, `$schema` is `https://json-schema.org/draft/2020-12/schema`, and all `required` fields are defined in `properties`.

## Outputs

- `spec/protocol.md` — updated envelope shape (seq, reply_to, delivered_to, origin_server, _meta)
- `spec/primitives/dms.md` — rewritten (dm/<sorted-pair> model)
- `spec/primitives/ack-nack.md` — rewritten (channels__ack tool model)
- `spec/primitives/groups.md` — rewritten (managed channel + membership table)
- `spec/primitives/sequence-numbers.md` — rewritten (per-channel seq)
- `spec/primitives/presence.md` — rewritten (channels__heartbeat + sox/presence)
- `spec/primitives/namespace.md` — new
- `spec/operations/channels_ack.input.schema.json` — new
- `spec/operations/channels_ack.output.schema.json` — new
- `spec/operations/channels_heartbeat.input.schema.json` — new
- `spec/operations/channels_heartbeat.output.schema.json` — new
- `spec/operations/channels_collect.input.schema.json` — new (x-status: planned)
- `spec/operations/channels_collect.output.schema.json` — new (x-status: planned)
- `spec/operations/replay.input.schema.json` — new
- `spec/operations/replay.output.schema.json` — new
- `spec/operations/send.input.schema.json` — updated (idempotency_key)
- `spec/operations/send.output.schema.json` — updated (backpressure)
- `spec/operations/recv.input.schema.json` — updated (thread_depth, include_meta)
- `spec/operations/list_channels.output.schema.json` — updated (_sox_protocol block)
- `spec/ports/backing-store.md` — updated (namespace, schema registry, idempotency sweep)
- `spec/ports/transport.md` — updated (CORS, long-poll/SSE notes)
- `docs/V1-SCOPE.md` — new canonical v1 reference

## Next state

When this phase reaches DONE, promote `02-review` → READY.

## Notes

**Why this phase exists:** `01-extract` reverse-engineered the spec from the
Python implementation (accurate to what was built). Separately, 19 architecture
decisions were made that extend and in some cases change the protocol design.
The implementation predates all decisions; the spec extracted from it therefore
reflects neither the decisions nor the intended v1 surface.

**Decisions are authoritative.** Where the current spec and a decision conflict,
update the spec. Do not modify the decision documents.

**channels__collect is planned, not deferred.** Include it in the spec with
`x-status: planned` and documented open questions. It is implementable on stdio
(asyncio blocking tool call) — the transport concern is HTTP scalability only.
Downstream planners need to know it exists and roughly what shape it takes.

**Risk tier:** HIGH (spec profile, ≥9 declared outputs). Use incremental
discipline — complete each conflict resolution before moving to gap filling.
Signal PARTIAL_COMPLETION if context runs short.
