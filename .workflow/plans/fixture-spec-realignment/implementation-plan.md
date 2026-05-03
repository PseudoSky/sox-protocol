# fixture-spec-realignment — implementation-plan (phase 01-plan)

Companion to `implementation-plan.json`. Same content in human-readable prose.

## Executive summary

The 9 HTTP conformance failures partition cleanly into:

| Category | Count | Fix-target | Phase |
|---|---|---|---|
| `reply_to` plumbing through send/recv | 3 | impl | 02 |
| Replay `since_seq` vs spec `since` | 2 | spec (fixture rename) | 03 |
| Unsubscribe queue discard | 1 | impl (likely SqliteStore) | 04 |
| Heartbeat emits on `sox/presence` | 1 | impl (both stores) | 05 |
| `list_channels` version block fixture | 1 | spec (fixture amend) | 05 |
| `group_invite` output shape | 1 | spec/impl alignment to spec shape | 06 |

**Largest single risk:** the `BackingStore.send` signature change for `reply_to` (Phase 02). It touches the abstract base, three concrete impls (memory, filesystem, sqlite), the middleware dispatcher, and every test that calls `store.send(...)` directly. Mitigation: add `reply_to: str | None = None` as a keyword-only kwarg with a default — preserves every existing call-site untouched.

**Second-highest risk:** Phase 05 heartbeat side-effect. The store's `heartbeat()` method becomes side-effecting (it now appends a message envelope on `sox/presence`). This is the spec's intent (`spec/primitives/presence.md §5`), but it changes the contract from pure-update-of-liveness-table to update-and-emit. Verify the reserved-prefix ACL allows `__server__` writes.

**Spec ambiguities not resolvable from the docs alone:**

1. *Phase 02 thread_depth*: the threading fixtures DO NOT assert on inlined ancestor arrays — only on `seq` and `reply_to`. So thread_depth ancestor-walk is likely NOT required to close them. But `spec/primitives/threads.md` may declare ancestor-walk as v1 MUST regardless. The Phase 02 agent must read that primitive spec before deciding.
2. *Phase 04 unsubscribe*: HTTP could be hitting MemoryStore (correct) or SqliteStore (unverified). Verification requires either reading `sqlite/store.py:unsubscribe` end-to-end or running the fixture with logging. This planning pass did not read SqliteStore's unsubscribe.
3. *Phase 05 list_channels augmentation site*: HTTP injects `_sox_protocol` in `routes.py:426-435`. Stdio relies on the simulator. The canonical injection site is unspecified — should it move into `BackingStore.list_channels`, or stay in the transport layer? Conservative: each transport layer owns the augmentation; remove the simulator's version and ensure the stdio MCP-tool wrapper has an equivalent injection.

---

## Per-fixture detail

### tsk_threading_01 — `threading/01-reply-to-link` (Phase 02-fix-reply-to)

**v1-scope anchor.** `docs/V1-SCOPE.md:14` (send tool — "Supports `reply_to` for threading"); line 41 (envelope `reply_to` row); line 92 (Threading row).

**Root cause.** `reply_to` is silently dropped at the `StoreDispatchMiddleware` boundary. Verified:

- `packages/python/src/sox_protocol/core/ports/backing_store.py:73-112` — abstract `send` signature has no `reply_to` parameter.
- `packages/python/src/sox_protocol/core/middleware/plugins/store_dispatch.py:100-121` — the `send` branch extracts only `channel`, `sender`, `body`, `correlation_id`. It NEVER reads `inp.get("reply_to")`.
- `packages/python/src/sox_protocol/adapters/backing_stores/memory/store.py:119-159` — `MemoryStore.send` constructs `_StoredMessage` without setting `reply_to`, even though the dataclass at line 41 already has the field (`reply_to: str | None = None`) and `to_wire` at line 55 emits it.
- `packages/python/src/sox_protocol/adapters/backing_stores/sqlite/store.py:61` — hard-coded `"reply_to": None` in the wire-output dict literal.
- The harness simulator at `tools/conformance_runner.py:996-1036` constructs `_StoredMessage` and `setattr(msg, "reply_to", reply_to)` to fake threading on stdio.

**Fix target.** impl.

**Files to touch.**

- `packages/python/src/sox_protocol/core/ports/backing_store.py` — add `reply_to: str | None = None` (keyword-only) to abstract `send`.
- `packages/python/src/sox_protocol/core/middleware/plugins/store_dispatch.py` — extract `inp.get("reply_to")`, pass through.
- `packages/python/src/sox_protocol/adapters/backing_stores/memory/store.py` — accept `reply_to`, set on `_StoredMessage`.
- `packages/python/src/sox_protocol/adapters/backing_stores/sqlite/store.py` — accept, persist (column likely already exists; verify migration), include in wire output.
- `packages/python/src/sox_protocol/adapters/backing_stores/filesystem/store.py` — accept, persist, include in wire output.

**Harness simulations to delete.**

- `tools/conformance_runner.py:996-1036` — entire `send` simulator branch.
- `tools/conformance_runner.py:1038-1055` — `recv` simulator branch (also patches `wire["reply_to"]`).
- `tools/conformance_runner.py:1110-1126` — `replay` simulator branch (patches `reply_to` augmentation; also covered by tsk_replay_01 deletion).

**Tests to add.**

- Unit: `MemoryStore.send(reply_to="msg-1")` round-trip via `recv`.
- Unit: same against SqliteStore.
- Middleware: `store_dispatch.send` extracts and forwards `reply_to`.

**Depends on.** none.

**Complexity.** M.

---

### tsk_threading_02 — `threading/02-deep-thread` (Phase 02)

Same root cause as tsk_threading_01. The fixture's `recv-deep` step asserts only on `seq:3` + `reply_to`. Closes when reply_to plumbs through. **Depends on** tsk_threading_01. Complexity S. **Open question Q3** — verify `spec/primitives/threads.md` does not require ancestor-walk in v1.

---

### tsk_threading_03 — `threading/03-thread-depth-zero` (Phase 02)

Same root cause; `thread_depth: 0` explicitly means no ancestor inlining. Closes when reply_to plumbs through. **Depends on** tsk_threading_01. Complexity S.

---

### tsk_replay_01 — `replay/01-replay-since-seq` (Phase 03-fix-replay-since)

**v1-scope anchor.** `docs/V1-SCOPE.md:22` ("Parameters: channel, since (seq), until (seq or null), limit").

**Root cause.** Wire-protocol field-name mismatch. Fixture sends `since_seq: 3`. Spec `replay.input.schema.json` requires `since` (line 7: `"required": ["channel","since","limit"]`). HTTP forwards body verbatim through to the middleware (`store_dispatch.py:217-232`) which reads `inp.get("since", 0)`. So `since_seq:3` is silently treated as `since:0` and all 4 messages return (expected: 2). Stdio-only "passes" because `tools/conformance_runner.py:1112` reads `args.get("since_seq", 0)`.

**Fix target.** spec — fixtures use the wrong field name. Canonical spec is `since`.

**Files to touch.**

- `spec/conformance/replay/01-replay-since-seq.yaml` — `since_seq: 3` → `since: 3`.
- `spec/conformance/replay/02-replay-empty-future-cursor.yaml` — same rename.

**Harness simulations to delete.** `tools/conformance_runner.py:1110-1126` — entire replay simulator branch.

**Depends on.** none. **Complexity.** S.

**Rejected alternative.** Adding `since_seq` as an input-schema alias was considered and rejected: pollutes a v1 contract for a typo in test fixtures. Spec wins.

---

### tsk_replay_02 — `replay/02-replay-empty-future-cursor` (Phase 03)

Same fix as tsk_replay_01. **Depends on** tsk_replay_01. Complexity S.

---

### tsk_unsubscribe_discard — `subscription-patterns/02-unsubscribe-discards-queue` (Phase 04)

**v1-scope anchor.** `docs/V1-SCOPE.md:17` (unsubscribe row — "Discards queued-but-unread messages").

**Root cause hypothesis.** Memory store IS correct (`memory/store.py:279-302` adds agent_id to `delivered_to` for matching channels and counts `pending_cleared`). The HTTP route remap is correct (`routes.py:402-403`). So the failure must be either (a) SqliteStore.unsubscribe is incomplete (this planning pass did not read it; **Q1**) or (b) there is an `agent_id` resolution mismatch between unsubscribe and the subsequent recv. The Phase 04 agent must:

1. Read `packages/python/src/sox_protocol/adapters/backing_stores/sqlite/store.py:unsubscribe` and confirm whether it implements the discard.
2. Run the fixture against HTTP with debug logging to see whether `pending_cleared > 0` is returned.

**Fix target.** impl (probably SqliteStore).

**Files to touch.** `packages/python/src/sox_protocol/adapters/backing_stores/sqlite/store.py` (likely).

**Harness simulations to delete.** `tools/conformance_runner.py:976-994` — `unsubscribe` simulator branch.

**Tests to add.** SqliteStore unit test mirroring the memory store contract; HTTP integration test for the full subscribe→send→unsubscribe→recv sequence.

**Depends on.** none. **Complexity.** S.

---

### tsk_presence_heartbeat — `presence/01-heartbeat-updates-presence-channel` (Phase 05)

**v1-scope anchor.** `docs/V1-SCOPE.md:21` ("Triggers events on `sox/presence`"); `spec/primitives/presence.md §5`.

**Root cause.** Both `MemoryStore.heartbeat` (lines 319-339) and `SqliteStore.heartbeat` (line 545+) update only the liveness table; they do NOT append a message on `sox/presence`. The simulator at `conformance_runner.py:1072-1108` hand-rolls this emit with body shape `{event, agent_id, state, changed_at}` (matches spec §5).

**Fix target.** impl.

**Files to touch.**

- `packages/python/src/sox_protocol/adapters/backing_stores/memory/store.py` — `heartbeat` appends a `_StoredMessage` on channel `sox/presence`, sender `__server__`, body per spec §5; sets `_new_message_event`.
- `packages/python/src/sox_protocol/adapters/backing_stores/sqlite/store.py` — equivalent, against the SQL schema.

**Harness simulations to delete.** `tools/conformance_runner.py:1072-1108` — heartbeat simulator emit.

**Tests to add.** Unit on each store: `heartbeat(...)` then `recv(...)` on `sox/presence` subscriber yields the documented body shape.

**Risk.** R2. The reserved-prefix ACL must allow `__server__` writes to `sox/`. Verify before commit.

**Coalescing.** Spec §5 says "coalesced — one event per state transition". v1 emits-on-every-call (simpler); coalescing is a SHOULD not MUST and can be a post-v1 optimization.

**Depends on.** none. **Complexity.** M.

---

### tsk_namespace_version_block — `namespace-isolation/02-version-block` (Phase 05)

**v1-scope anchor.** `docs/V1-SCOPE.md:18` (list_channels mandatory `_sox_protocol` block); line 89 (Version negotiation row).

**Root cause.** Two-part. (1) Fixture asserts on top-level `protocol_version: "{{any_string}}"` — a key the spec `list_channels.output.schema.json` does NOT define and which `additionalProperties:false` forbids. The simulator at `conformance_runner.py:1057-1067` hand-adds this top-level field to make stdio pass. (2) HTTP route already injects the spec-mandated `_sox_protocol` block (`routes.py:426-435`). Once the fixture is amended to assert `_sox_protocol.server_version` (or just `_sox_protocol` existence), HTTP passes.

**Fix target.** spec (fixture YAML).

**Files to touch.** `spec/conformance/namespace-isolation/02-version-block.yaml`.

**Harness simulations to delete.** `tools/conformance_runner.py:1057-1067`. Phase 05 agent should also evaluate whether the simulator's `list_channels` branch can be deleted entirely and the stdio path routed through the real `MemoryStore.list_channels` + a stdio-side `_sox_protocol` injection (open question Q2).

**Depends on.** none. **Complexity.** S.

---

### tsk_group_invite — `groups/01-create-invite-join` (Phase 06)

**v1-scope anchor.** `spec/operations/group_invite.output.schema.json` (canonical post-2fb72ac); `spec/primitives/groups.md §5.2`.

**Root cause.** Three-way mismatch.

- Spec output: `{invited:bool, agent_id:str, invited_at:int}` (`additionalProperties:false`, `required:["invited","agent_id","invited_at"]`).
- `BackingStore.group_invite` ABC docstring (backing_store.py:303): `{"invited": True, "agent_id": str, "invited_at": float}` — matches spec.
- Simulator (`conformance_runner.py:1213`): returns `{group_id, invited_agent, invited_at}` — legacy shape.
- Fixture `groups/01-create-invite-join.yaml:32-34`: expects `{group_id, invited_agent, invited_at}` — also legacy.
- MemoryStore + SqliteStore concrete impls: not directly read in this pass; likely return spec shape, but verify in Phase 06.

Canonical: spec (commit `2fb72ac` was the deliberate alignment in P3).

**Fix target.** spec/fixture/impl alignment with spec as the winner.

**Files to touch.**

- `spec/conformance/groups/01-create-invite-join.yaml` — change expected_output of `invite-member` step to `{invited: true, agent_id: agent-group-member, invited_at: "{{any_number}}"}`.
- `packages/python/src/sox_protocol/adapters/backing_stores/memory/store.py` — verify; fix if needed.
- `packages/python/src/sox_protocol/adapters/backing_stores/sqlite/store.py` — verify; fix if needed.

**Harness simulations to delete.** `tools/conformance_runner.py:1197-1213` (group_invite simulator). Phase 06 agent should also evaluate whether `_handle_group` (lines 1170+) can be deleted in toto.

**Risk.** R4 — search for downstream consumers reading `invited_agent` or `group_id` from the response (TUI, claude_code runtime).

**Depends on.** none. **Complexity.** M.

---

## Cross-cutting: harness simulator deletions

| Simulator branch | Lines | Delete in phase |
|---|---|---|
| `unsubscribe` | 976-994 | 04 |
| `send` | 996-1036 | 02 |
| `recv` (reply_to augmentation) | 1038-1055 | 02 |
| `list_channels` (top-level protocol_version + _sox_protocol) | 1057-1067 | 05 |
| `channels_heartbeat` (sox/presence emit) | 1072-1108 | 05 |
| `replay` | 1110-1126 | 03 |
| `_handle_group` group_invite branch | 1197-1213 | 06 |

By the end of phase 06, the only simulator branches that should remain are: `subscribe` (line 972-974, harmless passthrough), `channels_ack` (1069-1070, trivial), `list_agents` (1128-1162, may also be deletable), and `_handle_group` for group_create/join/leave/list_members (re-evaluate during phase 06). Phase 07 review verifies the residual surface is justified.

---

## Ordering DAG

```
tsk_threading_01 ──► tsk_threading_02
                 └─► tsk_threading_03

tsk_replay_01 ──► tsk_replay_02

tsk_unsubscribe_discard         (independent)
tsk_presence_heartbeat          (independent)
tsk_namespace_version_block     (independent)
tsk_group_invite                (independent)
```

Phase 02 must land first (gates 3 fixtures). Phases 03/04/05/06 are mutually independent and can be parallelized after 02 ships.

---

## Open questions (carry into phase dispatches)

- **Q1** — Phase 04: SqliteStore.unsubscribe correctness vs HTTP agent_id resolution mismatch. Resolve by reading the impl + running the fixture with logging.
- **Q2** — Phase 05: where does `_sox_protocol` injection canonically live (transport layer vs BackingStore.list_channels)?
- **Q3** — Phase 02: does `spec/primitives/threads.md` declare `thread_depth>=1` ancestor-walk as v1 MUST, or is the fixture's reply_to-only assertion sufficient?

These are non-blocking for phase 01-plan close; each is documented in the JSON `open_questions` array.
