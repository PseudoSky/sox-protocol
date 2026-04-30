<!-- SPDX-License-Identifier: Apache-2.0 -->
# spec-extraction 01-extract review

## Verdict
PASS-WITH-NOTES

(Spec is structurally sound, language-neutral, and the five high-risk decision items from the prompt all manifest. Several v1 protocol-tagged TODOs from classified.json have no operation schema or primitive section — these are the bulk of findings below and are warning-level: downstream consumers will discover the gaps but the existing surface is internally consistent.)

## Coverage matrix

Universe: 73 items in `classified.json` with `bucket="protocol"`. Matrix focuses on v1-milestone items (post-v1/deferred items are noted only when surprising omissions). "Adequate?" = "Yes / Partial / No".

| Protocol-tagged TODO id | Spec location | Adequate? |
|---|---|---|
| identity-bound-at-connection-not-claimed | `spec/ports/identity.md` §2 | Yes |
| channel-acls-backed-on-verified-identity | `spec/ports/identity.md`; `spec/primitives/groups.md` §4 | Yes |
| signed-messages-server-signs-each-persisted (post-v1) | `spec/ports/identity.md` §post-v1 | Yes (deferred) |
| credential-rotation-agents-can-rotate (post-v1) | `spec/ports/identity.md` §post-v1 | Yes (deferred) |
| self-send-exclusion-agents-currently-receive (v1) | not present | **No** |
| since-parameter-on-recv-accept (v1) | not in `spec/operations/recv.input.schema.json` (only `replay.since` exists) | **No** |
| ttl-message-expiry (post-v1) | `spec/ports/backing-store.md` retention prose | Partial |
| inbox-clear-explicit-flush-inbox (post-v1) | not present | No (acceptable for post-v1) |
| list-agents-tool-return-agent-id (v1) | no `list_agents.*.schema.json`; mentioned indirectly via `group_list_members` and `sox/presence` | **No** |
| agent-can-list-groups-channels-they (v1) | partly via `channels__list_channels` + `group_list_members` (groups.md §5.5); no dedicated `list_groups` schema | Partial |
| agent-can-request-another-agent-join (v1) | `group_invite` (groups.md §5.2) + `sox-invite.schema.json` | Yes |
| reply-to-field-on-send (v1) | `send.input.schema.json` `reply_to` | Yes |
| filter-recv-by-reply-to-and-sender (v1) | `recv.input.schema.json` has `channels` + `thread_depth` only — no `reply_to`/`sender` filter | **No** |
| list-pending-tool-returns-both-sides (v1) | referenced in prose (presence.md, ack-nack.md) but no `list_pending` operation schema exists | **No** |
| auto-prioritize-recv-unreplied-directs-first (v1) | not specified in `recv.output.schema.json` ordering rules | Partial |
| enforcer-uses-unreplied-as-stop-signal (v1) | `spec/discipline/discipline.md` (not re-read in detail; presumed) | Partial |
| define-spec-ports-transport-md (v1) | `spec/ports/transport.md` | Yes |
| standardize-transport-env-vars (v1) | `spec/ports/transport.md` | Yes |
| first-class-dm-primitive (v1) | `spec/primitives/dms.md`; `dm/<sorted-pair>` reserved | Yes |
| recv-surfaces-dms-separately (v1) | not differentiated in `recv.output.schema.json` (DMs returned as ordinary channel messages) | Partial |
| explicit-ack-signal-channels-ack (v1) | `spec/operations/channels_ack.*` + `spec/primitives/ack-nack.md` | Yes |
| list-pending-surfaces-ack-state (v1) | depends on missing `list_pending` schema | No |
| ack-clears-enforcer-stop-block (v1) | enforcer prose; not in `channels_ack.output.schema.json` | Partial |
| standard-error-envelope (v1) | `spec/envelopes/sox-error.schema.json` | Yes |
| list-pending-surfaces-nacks (v1) | depends on missing `list_pending` | No |
| enforcer-awareness-nack (v1) | enforcer prose | Partial |
| logical-clock-sequence-number (v1) | `spec/primitives/sequence-numbers.md`; `seq` in envelope | Yes |
| thread-ordering-guarantee (v1) | not explicitly stated in `recv.output.schema.json` or threads.md (channels.md §5 covers per-channel ordering only) | Partial |
| channels-create-group + join/leave/list/send (v1, groups bucket) | `spec/primitives/groups.md` §5; **no JSON Schemas under `spec/operations/`** for `group_create`, `group_invite`, `group_join`, `group_leave`, `group_list_members` | Partial |
| channels-send-extended-to-accept-group-id (v1) | `send.input.schema.json` accepts only `channel`; group sends require `group/<id>` channel name (documented) | Yes (by convention) |
| channels-list-groups (v1) | no dedicated schema; subsumed by `list_channels` + `group_list_members` | Partial |
| channels-group-members (v1) | `group_list_members` in groups.md §5.5; no JSON Schema | Partial |
| group-invite-flow (v1) | `group_invite` in groups.md §5.2; `sox-invite.schema.json` | Yes |
| channels__unsubscribe (v1) | not present anywhere | **No** |
| unsubscribe-cleans-up-pending-messages (v1) | not present | No |
| circuit-breaker-on-backing-store (v1) | not present in `spec/ports/backing-store.md` (no error-class taxonomy on store unavailability) | **No** |
| channels__health (v1) | no `health` operation schema | **No** |
| formal-version-negotiation-on-connection (v1) | `_sox_protocol` block in `list_channels.output.schema.json` covers fail-fast on first call | Yes |
| deprecation-policy-in-spec (v1) | `protocol.md` §Versioning prose; no `@deprecated` field convention | Partial |
| formalize-agent-bootstrap-sequence (v1) | not found as a normative section | **No** |
| channels__replay (post-v1 in classified, but treated as v1 here) | `spec/operations/replay.*` | Yes |
| broadcast_and_collect (post-v1) | `spec/operations/channels_collect.*` (x-status: planned) | Yes (deferred via $comment) |
| federation deferred | `protocol.md` §Federation-aware design; `origin_server` field; identity.md `<server-id>/<agent-id>` | Yes |
| namespace items (post-v1) | `spec/primitives/namespace.md` | Yes |
| trace_id / `_meta` observability (post-v1) | `recv.input.include_meta`; `recv.output._meta` | Yes |
| idempotency-key on send (post-v1) | `send.input.schema.json` `idempotency_key` | Yes |

### Architect-decision spot-checks (from prompt §7)

| Decision | Spec manifestation | Status |
|---|---|---|
| `_sox_protocol` block in `list_channels` | `spec/operations/list_channels.output.schema.json` lines 11–48 (`server_version`, `supported_versions`, `min_client_version`) | Present |
| `origin_server` in envelope | `spec/protocol.md` line 67; in `recv.output` and `replay.output` schemas | Present |
| `replay` as a distinct verb | `spec/operations/replay.input.schema.json`, `replay.output.schema.json`; `protocol.md` op table line 44 | Present |
| `channels__ack` as a dedicated tool | `spec/operations/channels_ack.*`; `spec/primitives/ack-nack.md` | Present |
| `backpressure` field on send response | `spec/operations/send.output.schema.json` lines 23–47 (always-present object with `state` enum) | Present |

All five decisions manifest. No silent drops detected on the prompt's high-risk list.

## Findings

### Blocking

None. The five architect decisions all land in the spec, the `_sox_protocol` negotiation block is in place, and no language-specific idioms leak into the canonical spec text.

### Warning

**W1. `recv.input.schema.json` is missing the `since` filter (v1 TODO)**
- `since-parameter-on-recv-accept` is `bucket=protocol, milestone=v1` in `classified.json`.
- `spec/operations/recv.input.schema.json` exposes only `channels`, `max_messages`, `thread_depth`, `include_meta`. No `since` (timestamp) and no `since_seq`.
- Without it an agent that pauses cannot resume cleanly without re-draining or relying on `replay`. Two impls could disagree on whether re-draining is allowed.
- Suggested fix: add `since` (Unix epoch seconds, optional) and/or `min_seq` to `recv.input.schema.json`, or file an explicit deferral note in the schema `$comment` citing the TODO id.

**W2. `recv.input.schema.json` is missing `reply_to` and `sender` filters (v1 TODO)**
- `filter-recv-by-reply-to-and-sender` is v1 protocol-tagged.
- Schema currently has no filter fields beyond `channels`. The threading primitive depends on this for "auto-prioritize unreplied directs first."
- Suggested fix: add optional `reply_to` (string|null) and `sender` (string|null) filters to `recv.input.schema.json`, or document explicit deferral.

**W3. No `list_pending` operation schema**
- Three v1 protocol items require it: `list-pending-tool-returns-both-sides`, `list-pending-surfaces-ack-state`, `list-pending-surfaces-nacks`.
- The string "list_pending" appears in `spec/primitives/presence.md` (lines 111, 131) and `spec/primitives/ack-nack.md` but no `spec/operations/list_pending.*.schema.json` exists.
- Conformance suite cannot test it; ts-sdk cannot bind it.
- Suggested fix: add `spec/operations/list_pending.input.schema.json` and `.output.schema.json` with the `awaiting_reply` / `unread_directs` / `nacked` arrays the prose implies — OR mark it post-v1 explicitly in `protocol.md` and downgrade the prose references.

**W4. No `list_agents` operation schema**
- `list-agents-tool-return-agent-id` is v1 protocol-tagged. Spec mentions agent enumeration only via `sox/presence` (event-driven) and `group_list_members` (per-group). Neither covers "all agents in the deployment" discovery.
- Suggested fix: add `list_agents` schema (returning `[{agent_id, presence_state, channels}]`) or document deferral and remove the prose claim that `list_pending`/`list_agents` exists.

**W5. No `channels__unsubscribe` operation schema**
- Two v1 items: `channels__unsubscribe(pattern)` and `unsubscribe-cleans-up-pending-messages`.
- `subscribe.input.schema.json` exists but no `unsubscribe.*.schema.json`. Subscriptions are described as persistent across restarts (channels.md §3.3) — without an unsubscribe verb, an agent cannot reduce its footprint without restarting under a new identity.
- Suggested fix: add `spec/operations/unsubscribe.input.schema.json` and `.output.schema.json`.

**W6. No `channels__health` operation schema (v1 graceful-degradation item)**
- `circuit-breaker-on-backing-store` and `health-check-tool-channels-health-returns` are v1 protocol items. Neither has a schema or a primitive section; `spec/ports/backing-store.md` does not enumerate the error taxonomy a circuit breaker would expose.
- Suggested fix: add `health.output.schema.json` with `{store_status, listener_queue_depth, uptime_seconds}` or downgrade items to post-v1 explicitly.

**W7. Group lifecycle verbs documented in prose only — no JSON Schemas**
- `spec/primitives/groups.md` §5.1–5.5 specify `group_create`, `group_invite`, `group_join`, `group_leave`, `group_list_members` with parameter / return text but no machine-readable schemas under `spec/operations/`.
- Cross-impl portability test: a Rust developer reading only `spec/` would have to hand-translate the prose into a schema, with no source of truth for required vs. optional fields, exact error names (`GROUP_MEMBERSHIP_REQUIRED` is referenced but not enumerated), or `id_mode` value space.
- Suggested fix: produce `spec/operations/group_create.{input,output}.schema.json` (and the four siblings), mirroring the pattern used for `channels_ack` and `channels_collect`.

**W8. `protocol.md` operation table claims eight operations but `unsubscribe`, `list_pending`, `list_agents`, group lifecycle verbs are absent**
- `spec/protocol.md` line 34: "All SOX-conformant implementations expose exactly these eight operations." Table lists send, recv, subscribe, list_channels, channels__ack, channels__heartbeat, replay, channels__collect.
- This contradicts groups.md §5 (which adds five more verbs as MUST-implement for groups), the missing `unsubscribe` (subscribe without unsubscribe is asymmetric), and prose mentions of `list_pending` / `list_agents`.
- Suggested fix: either expand the operation table to enumerate group lifecycle + unsubscribe + list_pending + list_agents, or explicitly demote the orphan prose references to post-v1 with rationale.

**W9. `recv.output.schema.json` does not separate DMs from channel messages**
- `recv-surfaces-dms-separately-from-channel` is v1 protocol-tagged. Current output is a single `messages[]`. DM identification is left to the caller (parsing `dm/` prefix on `channel`).
- Suggested fix: either add a `dms[]` sibling array or document explicitly that the `dm/` prefix is the contractual separator and remove the implication of separate surfacing.

**W10. Thread ordering guarantee not stated**
- `thread-ordering-guarantee` is v1. `spec/primitives/threads.md` was not located by the targeted greps; `channels.md` §5 specifies only per-channel ordering. Per-thread-chain ordering inside a channel is implied but not spelled out.
- Suggested fix: add a normative paragraph in `spec/primitives/threads.md` (or in `recv.output.schema.json` description): "Within a single channel, messages with the same `reply_to` chain are returned in `seq`-ascending order; an ancestor with `seq=k` always precedes a descendant with `seq>k`."

**W11. Bootstrap sequence not formalised**
- `formalize-agent-bootstrap-sequence-in-spec` is v1. No section in `spec/` enumerates `subscribe → list_agents → list_channels → recv` (or whatever the canonical sequence is). The `_sox_protocol` block on `list_channels` is the only handshake-like artefact.
- Suggested fix: add `spec/protocol.md` §"Connection bootstrap" with the ordered sequence and the `_sox_protocol` check as step 1.

**W12. ACK transition reverse-rejection is SHOULD, not MUST**
- `spec/operations/channels_ack.input.schema.json` line 23 ("Transitions MUST be forward-only within a session") and `spec/primitives/ack-nack.md` §3 ("The server SHOULD reject a transition that moves backward") disagree. Conformance suite needs one or the other.
- Suggested fix: align both to MUST (preferred — deterministic) or both to SHOULD with rationale in ack-nack.md.

**W13. `replay.output.schema.json` envelope drops `delivered_to` (and `_meta`)**
- `spec/operations/replay.output.schema.json` enumerates envelope fields explicitly but omits `delivered_to` (advertised in `protocol.md` line 67 as part of the canonical envelope) and `_meta`.
- Effect: an impl could legitimately strip these on replay vs. preserve them on `recv`, and two impls could disagree.
- Suggested fix: add `delivered_to` (string[]|null) and `_meta` (object|null) to the replay envelope item, or add a normative note that replay intentionally drops them.

**W14. `_sox_protocol` block exists only on `list_channels`, not on every response**
- ADR / decision intent (per `protocol.md` line 41 and `list_channels.output.schema.json` description) is fail-fast on first call. Acceptable, but contracts should state explicitly that "skipping list_channels assumes latest server version at client's risk" is the only fallback. The schema description does say this; the prose in `protocol.md` could surface it more prominently.
- Suggested fix: add to `protocol.md` §Versioning a one-liner: "Clients that skip `list_channels` proceed without a version handshake at their own risk."

### Nit

**N1. `protocol.md` line 130 references "asyncio listener"**
- "Layer 2 — MCP server (four tools; asyncio listener)" leaks Python runtime vocabulary into the canonical spec. The rest of `spec/` is language-neutral.
- Suggested fix: change "asyncio listener" → "non-blocking listener" or "event-loop listener". Also update "four tools" — there are eight in §"Protocol operations".

**N2. `spec/README.md` line 69 cites `packages/python/src/sox_protocol/...` path**
- Concrete impl path inside the canonical spec README. Acceptable as an example but should be marked as such.
- Suggested fix: prefix with "Example for the reference Python implementation:".

**N3. `channels_collect.input.schema.json` description mentions "asyncio blocking"**
- Line 6: "the stdio binding satisfies collect via asyncio blocking with no extra transport." Same Python leak as N1.
- Suggested fix: replace with "the stdio binding satisfies collect via a blocking await on the server's runtime, with no extra transport requirement."

**N4. `channels.md` §2 still lists the deprecated `agent:<target-agent-id>` DM convention while `dms.md` mandates `dm/<sorted-pair>`**
- `spec/primitives/channels.md` line 30 row "Direct channel (DM) | `agent:<target-agent-id>`" contradicts `spec/primitives/dms.md` §2 (the reserved `dm/` prefix is normative).
- Suggested fix: update `channels.md` §2 row to `dm/<sorted-pair>` and remove the `agent:` example, or mark `agent:<id>` as deprecated.

**N5. `channels.md` §6.3 lists three reserved prefixes (`dm/`, `group/`, `sox/`); §7 still describes ACKs as "messages sent back to the originating channel with a reserved body type"**
- `channels.md` §7 last interaction row contradicts the new `channels__ack` model (`ack-nack.md` §1: "ACK is NOT a channel message"). Stale narrative.
- Suggested fix: update §7 ACK interaction row to "ACKs are control-plane signals via `channels__ack`; they do not enter channel history."

**N6. `spec/primitives/sequence-numbers.md` line 47 says `ts` type is "implementation-defined"**
- Two impls could disagree (integer ns vs. ISO-8601 string), breaking wire-level interop.
- Suggested fix: pick one (recommend integer nanoseconds, matching `protocol.md` line 76) and forbid the other.

**N7. `spec/conformance/docker-compose.yml` exists inside `spec/`**
- Strict spec/impl split would put runnable infrastructure outside `spec/`. Acceptable if treated as a reference harness; flag that it is not normative.
- Suggested fix: add a header comment to the compose file: "Reference harness for the conformance suite. Not normative; implementations MAY use any orchestration."

**N8. No TODO markers found inside the JSON Schemas themselves**
- The prompt asked about TODO markers deliberately filed by phase 01. None were found in `spec/operations/*.schema.json`. The `x-status: planned` comment on `channels_collect` is the closest analogue and is well-formed. This is informational, not a defect.

## Sign-off

Verdict is PASS-WITH-NOTES. Downstream consumers (conformance-suite, http-transport, ts-sdk) can begin work, but the orchestrator should be aware of:

1. **Eight operations is wrong, or the missing schemas are wrong.** Findings W3–W7 collectively mean roughly 8–12 v1 protocol-tagged TODOs have prose hooks but no JSON Schema. Either the schemas land before conformance-suite freezes, or `protocol.md` should explicitly demote those items to post-v1 with rationale. The conformance-suite phase will trip on this.
2. **`recv` filtering is thinner than the v1 TODO list implies.** No `since`, no `reply_to` filter, no `sender` filter, no DM separation. ts-sdk authors will work around this, then a later schema patch will rebreak them.
3. **Group verbs are prose-only.** Five operations specified in markdown without machine-readable schemas. Cross-impl interop is at risk; a Rust impl following only `spec/operations/` will not implement groups at all.
4. **Two stale references to Python runtime vocab** (`asyncio` in `protocol.md` and in `channels_collect.input.schema.json`). Quick fix; matters because the language-neutrality claim is foundational to ADR 0001.
5. **One deprecated DM convention is still listed in `channels.md`** alongside the new `dm/<sorted-pair>` rule. Remove or mark deprecated.
6. **MUST/SHOULD disagreement** between `channels_ack.input.schema.json` and `ack-nack.md` on backward transition rejection. Pick one.
7. **Federation, observability, idempotency, and namespace decisions all manifest cleanly.** No silent drops on the prompt's five high-risk decision spot-checks.

Recommended immediate action before downstream phases: address W1, W2, W5, W7 (schema gaps that block ts-sdk binding) and N1, N3 (language-neutrality fixes). The remaining warnings can be deferred but must be tracked as a follow-up phase rather than rediscovered by each consumer.
