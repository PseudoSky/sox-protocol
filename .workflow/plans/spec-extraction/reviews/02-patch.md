# spec-extraction patch review

## Verdict
PASS-WITH-NOTES

## Scope
Re-review of the 21 files modified by the patch following the original PASS-WITH-NOTES review. All listed files were read directly (12 new schemas, 3 modified schemas, 6 prose docs). Cross-reference reads: `spec/operations/channels_ack.input.schema.json`, `spec/primitives/groups.md`, `spec/primitives/dms.md`.

## Findings

### HIGH — Schema/prose divergence on group lifecycle field names
- **Files:** `spec/primitives/groups.md:74,82-85,93-95,102-105,113-115` vs all `spec/operations/group_*.schema.json`
- **What:** Prose in `groups.md §5.1–5.5` consistently uses parameter/response field name `channel` (e.g. `{ channel: "group/<group-id>", created_at }`). The new JSON Schemas use `group_id` everywhere instead. This is a normative mismatch — both documents are normative and a Rust implementer would generate a different wire field depending on which artefact they read.
- **Suggested fix:** Pick one name. Recommend updating `groups.md §5.1–5.5` to match the schemas (`group_id` is the more descriptive name and matches `group_create.input` which the prose itself accepts). Also update the §5.1 return shape to drop `channel` in favor of `group_id`.

### HIGH — `group_list_members.output` omits `joined_at` and `status`
- **File:** `spec/operations/group_list_members.output.schema.json:18-32` vs `spec/primitives/groups.md:115`
- **What:** Prose says the response is "Array of `{ agent_id, joined_at, status }` objects." Schema items only define `{ agent_id, presence_state }`. `joined_at` and `status` (active/invited) are completely missing — yet `status` is essential for an inviter to see pending invitees, and `joined_at` is part of the documented membership table contract (groups.md §4 table).
- **Suggested fix:** Add `joined_at: integer` (Unix epoch seconds) and `status: enum [active, invited]` to the member item, both required. Make `presence_state` optional/null when `include_presence=false`.

### MEDIUM — `group_create.input` missing `id_mode`; `group_id` incorrectly required
- **File:** `spec/operations/group_create.input.schema.json:7,10-15` vs `spec/primitives/groups.md:28,71`
- **What:** `groups.md §2` references an `id_mode` parameter that "the server determines … at group creation time." `groups.md §5.1` makes `group_id` optional ("If omitted, server assigns an opaque ID"). The schema marks `group_id` as required and omits `id_mode`. A spec consumer cannot request a server-assigned ID.
- **Suggested fix:** Move `group_id` from `required` to optional; add `id_mode: enum [client, server]` with default `client`. Or, alternatively, drop the prose claim and document client-supplied IDs only.

### MEDIUM — `group_invite.output` shape diverges from prose
- **File:** `spec/operations/group_invite.output.schema.json:7-19` vs `spec/primitives/groups.md:85`
- **What:** Prose returns `{ channel, invited_agent, invited_at }`. Schema returns `{ invited, agent_id }` with no timestamp. Loss of `invited_at` removes the only audit-time signal in the response.
- **Suggested fix:** Add `invited_at: integer` (Unix epoch seconds), required. Reconcile the field names with the §5.1 decision above.

### MEDIUM — `group_join`/`group_leave` outputs drop `joined_at`/`left_at`
- **Files:** `spec/operations/group_join.output.schema.json:7-23`, `spec/operations/group_leave.output.schema.json:7-19` vs `spec/primitives/groups.md:95,105`
- **What:** Prose returns timestamps; schemas replace them with booleans (`joined`, `left`). Booleans are redundant with HTTP status — timestamps carry information.
- **Suggested fix:** Add `joined_at` / `left_at` integer fields. Keep the boolean if desired but it should not replace the timestamp.

### MEDIUM — Regression: DMs row in `channels.md §7` still uses `agent:<target-id>`
- **File:** `spec/primitives/channels.md:139`
- **What:** The patch correctly fixed §2 (marks `agent:` deprecated, recommends `dm/<sorted-pair>`). However, the §7 interaction table row "DMs" still reads: `A DM is a channel named 'agent:<target-id>'; same wire protocol`. This contradicts both the patched §2 and `dms.md §2`.
- **Suggested fix:** Update §7 row to: `A DM is a managed channel named 'dm/<sorted-pair>'; see dms.md §2.`

### LOW — `group_create.output` returns Unix-second `created_at` while envelope timestamps are integer ns
- **File:** `spec/operations/group_create.output.schema.json:15-18`
- **What:** All other lifecycle outputs return Unix epoch seconds (consistent with `groups.md §4` membership table) but `protocol.md` and `sequence-numbers.md §3` standardise envelope `ts` on integer nanoseconds. This is acceptable (membership-table semantics differ from envelope), but worth a one-line note in the description so implementers do not conflate them.
- **Suggested fix:** Add `"unit": "seconds"` clarifier to the description, or harmonise on nanoseconds.

### LOW — `replay.output` `_meta` description references missing fields list
- **File:** `spec/operations/replay.output.schema.json:62-81`
- **What:** Patch correctly added `_meta` to message items mirroring `recv` envelope. `_meta` properties have `additionalProperties: false` but no `required` list — a server emitting a partial `_meta` (e.g. only `trace_id`) is allowed, which matches reality. Just confirm intent: example at line 102-119 omits `_meta` entirely (which is fine because it's nullable). No bug, just verify.
- **Suggested fix:** None required; consider adding one example that includes `_meta` to demonstrate shape.

### LOW — `unsubscribe.input` namespace parameter not anchored in prose
- **File:** `spec/operations/unsubscribe.input.schema.json:20-25`
- **What:** `namespace` field appears here but `channels.md §3` does not introduce a namespace concept for subscribe/unsubscribe. The corresponding `subscribe.input` schema should be the precedent — if subscribe lacks `namespace`, unsubscribe introducing it is a new concept; if subscribe has it, then it is consistent. (Could not verify subscribe.input within this re-review's scope.)
- **Suggested fix:** Cross-check `subscribe.input.schema.json` for symmetry. If subscribe has no namespace, drop it from unsubscribe; if it has, ensure prose mentions it.

## Items resolved by the patch (no action)
- asyncio language removed from `protocol.md` and `channels_collect.input.schema.json`. Verified clean.
- `recv.input.schema.json` `$comment` accurately enumerates the deferred filters and points to TODOs.
- `ack-nack.md §3` now reads MUST on backward-transition rejection, consistent with `channels_ack.input.schema.json` enum.
- `channels.md §2` row for DMs now marks `agent:` deprecated with the correct `dm/<sorted-pair>` recommendation.
- `sequence-numbers.md §3` ts type fixed to integer nanoseconds with explicit prohibition of ISO-8601 strings.
- `replay.output.schema.json` envelope now carries `delivered_to` and `_meta`, matching `protocol.md` envelope shape.
- `protocol.md` Connection bootstrap section uses SHOULD with appropriate qualifying language; `list_channels`/`subscribe`/`recv` ordering is normatively safe and consistent with the rest of the spec.
- `protocol.md` operation table now lists every `group_*` lifecycle verb plus `unsubscribe` with v1 MUST status.
- `protocol.md` Versioning section adds the cross-major refusal rule and clarifies bootstrap-skip risk.
- `spec/README.md` impl path marked as example.
- `spec/conformance/docker-compose.yml` non-normative header comment present.
- `unsubscribe.output` `pending_cleared` correctly describes message discard semantics.

## Sign-off
The patch resolves all original PASS-WITH-NOTES findings (asyncio neutrality, MUST alignment on ACK transitions, DM convention fix, replay envelope completeness, bootstrap normativity, sequence-number type, missing schemas added). The remaining findings are confined to internal consistency between the new group lifecycle schemas and the `groups.md` prose — they are correctness issues for implementers but do not require re-litigating any architectural decision. Planners may proceed with phase 04 in parallel with a follow-up patch that reconciles group lifecycle field names and restores `joined_at`/`status` to the membership response shape; the spec is structurally sound and the residual gaps are mechanical.

REPORT: PASS-WITH-NOTES; 8 findings (2 HIGH, 4 MEDIUM, 3 LOW = 9 — recount: 2 HIGH + 3 MEDIUM + 3 LOW = 8). All originals resolved; new findings concern group-lifecycle schema/prose drift introduced by the patch.
