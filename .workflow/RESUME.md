# RESUME — pick up where the prior session left off

**You are reading this because:** a previous Claude Code session is being handed off to you. The work is ongoing; the tree is in a coherent committed state. Read this end-to-end before doing anything else.

**Date written:** 2026-05-04 (late)
**Tree state at handoff:** clean working tree on `main`. Last commit `c2e4541`. mypy --strict clean across 81 source files. stdio conformance 33/0/34. HTTP conformance 24/9/34 (the 9 are documented in this doc). Pytest 1230 passed, 0 failed (excluding the pre-existing SSE hang covered below).

---

## What's been shipped this session

The prior session opened with P1 (`pipeline-integration`) at 3/8 phases. This session **closed the entire v1 plugin-architecture program** — all 6 v1 sub-engagements are now complete:

| Engagement | Status | Closing commit |
|---|---|---|
| P1 `pipeline-integration` | **closed** | `d22addd` (review APPROVED-WITH-FOLLOWUPS) |
| P2 `plugin-contract-freeze` | closed (pre-session) | `b22a536` |
| P3 `plugin-spec-polish` | closed (pre-session) | `b22a536` |
| P4 `plugin-discovery-py` | **closed** | `d5cd49b` (review APPROVED-WITH-FOLLOWUPS, 0 critical/0 high security) |
| P5 `reference-plugins` | **closed** | `c2e4541` (review APPROVED-WITH-FOLLOWUPS) |
| P6 `plugin-architecture-ts` | closed (pre-session) | `28c2a16` |

This session's commits (newest first):

```
c2e4541 docs(review): reference-plugins P5 phase 04 terminal review — APPROVED-WITH-FOLLOWUPS
35d1836 refactor(http): delete routes._validate_body + 22 inline call-sites; wire schema-strict plugin
a237f15 feat(reference-plugin): sox-plugin-schema-strict — proves contract end-to-end (P5-01+02)
d5cd49b docs(review): plugin-discovery-py P4 phase 06 terminal review
86bf8fb chore(test-fixtures): remove setuptools build artifacts; add .gitignore
74f7297 test(plugin-discovery): e2e stub fixtures + integration tests (P4 phase 05)
b6df560 feat(plugin-discovery): bootstrap wire-up + extend_pipeline_with_registry (P4-04)
4a24d78 feat(cli): --allow-plugins / --no-discovery + load_plugins allowlist semantics (P4-03)
ae8d741 feat(plugin-loader): manifest loader, typed errors, registry.load_plugins, unit tests
d22addd docs(review): P1 pipeline-integration phase 08 review — APPROVED-WITH-FOLLOWUPS
3df2e54 fix(identity): wrap nonce prune+check+insert in asyncio.Lock (P1-05)
c16ac45 feat(observability): pipeline_trace + correlation_id on every dispatch (P1-04)
619c211 test(conformance): server-side rejection fixture proves AuthMiddleware path (P1-07)
bb71125 refactor(conformance): delete harness identity substitution; route SharedMemoryTarget through auth Pipeline (P1-06)
```

---

## ⚠️ v1 is NOT shippable yet despite the program being "complete"

A late audit in this session surfaced two HIGH-priority gaps that the per-engagement reviews under-classified as "follow-on":

### Gap 1: 9 HTTP conformance failures map to spec-declared v1 MUST features

Per `docs/V1-SCOPE.md`, these are required-for-v1 capabilities that the implementation claims to support but silently mishandles:

- **`reply_to` silently dropped** (3 failures: `threading/01-03`) — `send.input.schema.json` accepts `reply_to`, the server returns success, but the field never reaches the backing store. Threading is broken end-to-end. **Data loss.**
- **`replay/since` cursor not honored** (2 failures: `replay/01-02`) — replay returns 0 messages where 2 are expected.
- **`unsubscribe` doesn't discard queue** (1 failure: `subscription-patterns/02`) — V1-SCOPE.md says "Discards queued-but-unread messages"; impl doesn't.
- **`heartbeat` doesn't emit on `sox/presence`** (1 failure: `presence/01`) — V1-SCOPE.md heartbeat row + `presence.md §2` mandate this.
- **`list_channels` missing `_sox_protocol` block** (1 failure: `namespace-isolation/02-version-block`) — V1-SCOPE.md `list_channels` row mandates the version-negotiation block.
- **`group_invite` output field mismatch** (1 failure: `groups/01-create-invite-join`) — spec says `{invited, agent_id}`; impl emits `{group_id, invited_agent}`. Stdio "passes" only via harness client-side remap.

Tracked in: **`.workflow/plans/fixture-spec-realignment/STATE.md`** (NEW).

### Gap 2: No live-Claude e2e test proving install→messaging works end-to-end

Every existing e2e/integration test uses deterministic Python simulating agents. There is NO test that:
1. `pip install`s SOX into a temp dir
2. Runs the claude_code installer against a fresh project
3. Spawns 2 actual `claude` subprocesses
4. Has them exchange messages via group_create / invite / join
5. Verifies the wire works

Without this, "the system works on install" is an assumption, not a verified fact.

Tracked in: **`.workflow/plans/live-install-e2e/STATE.md`** (NEW).

### Gap 3 (medium, non-blocking): architectural cleanup from REVIEWs

Aggregated from P1-08, P4-06, P5-04 REVIEW.md follow-up sections. None v1-blocking; cleanup that will compound if deferred.

Tracked in: **`.workflow/plans/core-cleanup/STATE.md`** (NEW).

---

## Engagement priority for next session

Open engagements, in priority order:

| # | Engagement | Priority | Status | Estimated phases |
|---|---|---|---|---|
| 1 | `fixture-spec-realignment` | **HIGH — v1 cannot ship without these** | phase 01-plan READY | 7 |
| 2 | `live-install-e2e` | **HIGH — without this, install path is unverified** | phase 01-plan READY | 5 |
| 3 | `core-cleanup` | MEDIUM — non-blocking | phase 01 READY (6 fix phases + review) | 7 |

#1 and #2 are independent and can run in parallel.

---

## Hard-won lessons preserved from prior sessions (still applicable)

### Agents truncate even when running 47–70 minutes

In this session, the P5-03 agent ran 70 minutes (4162s, 183 tool uses) before completing. Other agents truncated mid-verification with the classic pattern: *"Let me check..."* / *"Now run the plugin unit tests first to verify they pass:"*. **Always verify with bash. The working tree is what shipped, not anyone's report.**

For each phase dispatch in the new engagements: trust nothing the agent says about completion. Always re-run the four-invariant block (below) before believing.

### The harness's stdio adapter masks real spec/impl gaps

`tools/conformance_runner.py` lines 766–1127 — the `SharedMemoryTarget` class — is a SIMULATOR that hand-implements `reply_to` plumbing, group_invite output remapping, replay timing, etc. that the real backing store / middleware doesn't. Stdio's "33/0/34 conformance" includes simulator-masked passes.

**Every phase in `fixture-spec-realignment` must DELETE the corresponding harness simulation as part of the fix** — otherwise stdio silently keeps "passing" via the simulator while HTTP genuinely passes via the wire, defeating the point.

### Phase 06 (P1) fix-pattern: when in doubt, route through Pipeline

P1-06's Option A (wire SharedMemoryTarget through auth Pipeline rather than synthesize errors client-side) is the precedent: the harness should exercise real middleware paths, not simulate them. Apply the same principle to any new harness-substitution discovery.

### Test pollution from `enforcer/` tests

`asyncio.get_event_loop()` is deprecated in Python 3.13+ and doesn't auto-create a new loop after another test closed it. Use `asyncio.run(...)` for per-call event-loop isolation in any new test that uses asyncio.

### Status code vs envelope coordination

Three coordinated edits keep the test contract intact:
- `routes.py` maps sox-error envelope `error_code` → HTTP status (401/400/500 per `03-plugin-contract.md §6`)
- `HttpTarget.call_tool` surfaces 4xx body directly (instead of synthesizing `_rpc_error`)
- The runner's `is_error` check accepts top-level `error_code`

If you ever change the HTTP response format, audit all three.

### Pytest hang test — known and isolated

`tests/transports/http/test_coverage2.py::test_sse_endpoint_invalid_credential` hangs (pre-existing from `bb7aaa7` — `create_app(identity=...)` legacy kwarg not wired through the new pipeline). Workaround: always use `--ignore=packages/python/tests/transports/http/test_coverage2.py` in pytest invocations until it's fixed (candidate for `core-cleanup` phase 08 or a one-off fix).

---

## Hard invariants to preserve

Before any commit on this branch:

```bash
cd /Users/nix/dev/ai/sox-protocol
timeout 600 python3 -m pytest packages/python/tests/ --tb=line -q --ignore=packages/python/tests/transports/http/test_coverage2.py 2>&1 | tail -5
# expect: ≥ 1230 passed, 0 failed (the 2 pre-existing group_invite failures got fixed by P5-03 field-canonicalization)

cd packages/python && python3 -m mypy --strict src/sox_protocol/ | tail -1
# expect: Success: no issues found in 81 source files

cd /Users/nix/dev/ai/sox-protocol
python3 tools/conformance_runner.py --target packages/python --transport stdio --strict | tail -1
# expect: 33 passed, 0 failed, 34 skipped

python3 tools/conformance_runner.py --target packages/python --transport http --strict | tail -1
# current: 24 passed, 9 failed, 34 skipped
# acceptable: NO regression below 24/9. fixture-spec-realignment will move this to 33/0/34 when complete.
```

If any invariant regresses — stop and investigate. The most likely cause is an unfinished/un-committed agent run in the working tree.

---

## Quick start for the next session

1. Read this file (you're doing it).
2. `git log --oneline -15` — sanity check recent commits.
3. `git status --short` — confirm clean tree.
4. Run the four-invariant block above. If anything regressed, the most likely cause is an unfinished/un-committed agent run.
5. Pick from the priority table:
   - **Recommended start:** dispatch `fixture-spec-realignment` phase 01-plan to a planner agent. The plan should produce a per-fixture root-cause + file-touch + harness-deletion-list. Pass it the contents of `bb7aaa7`'s commit body and the failing fixture YAMLs.
   - **In parallel:** dispatch `live-install-e2e` phase 01-plan. The two engagements don't overlap.
   - **Later:** `core-cleanup` if bandwidth.

Each engagement's `STATE.md` lists its phases with a "Currently next action" pointer. Follow the same protocol that closed P1/P4/P5 in this session: dispatch one phase at a time, verify with bash, commit per orchestrator-contract trailer rules, then the next phase.

---

## Where things are

### Production code

- Plugin loader: `packages/python/src/sox_protocol/core/middleware/plugin_loader.py`
- Plugin registry: `packages/python/src/sox_protocol/core/middleware/registry.py` (with `load_plugins()`)
- Default chain: `packages/python/src/sox_protocol/core/middleware/default_chain.py` (with `extend_pipeline_with_registry()`)
- HTTP routes: `packages/python/src/sox_protocol/adapters/transports/http/routes.py` (`_validate_body` deleted in P5-03)
- HTTP bootstrap: `packages/python/src/sox_protocol/adapters/transports/http/server.py`
- Stdio bootstrap: `packages/python/src/sox_protocol/core/mcp_server/server.py`
- Identity verifier: `packages/python/src/sox_protocol/core/identity/verifier.py` (with `_nonces_lock` from P1-05)

### The reference plugin (proves the contract)

- `plugins/sox-plugin-schema-strict/` — installed via `pip install plugins/sox-plugin-schema-strict/`
- Entry-point: `io.sox.schema-strict` → `sox_plugin_schema_strict:factory`
- 29 unit tests + 7 e2e tests, all passing

### Conformance fixtures

- `spec/conformance/<group>/*.yaml` — protocol-level fixtures
- The 9 failing fixtures are listed in commit `bb7aaa7`'s body (also in `fixture-spec-realignment/STATE.md` phases 02–06)

### Reviews (read these before touching their respective territory)

- `.workflow/plans/pipeline-integration/REVIEW.md` — P1 final review (all P1 territory)
- `.workflow/plans/plugin-discovery-py/REVIEW.md` — P4 final review (loader/registry/bootstrap territory)
- `.workflow/plans/reference-plugins/REVIEW.md` — P5 final review (plugin + routes-deletion territory)

### Engagement state

- `.workflow/plans/<slug>/STATE.md` — every engagement has one
- Open engagements (created this session): `fixture-spec-realignment/`, `live-install-e2e/`, `core-cleanup/`
- Closed engagements have `state: complete` (not all use this field; use the phases table to confirm)

---

## What's NOT in scope for any of these engagements

Documented v1.x deferrals (intentional, NOT corrections):

- `signatures` field actual verification → future `plugin-supply-chain-v2` engagement (per ADR 0004 §6)
- Hot-reload → explicitly v1-deferred (analysis §7.5 risk #4)
- `sox.yaml` config schema → env-vars only for v1 (analysis §7.5 risk #6)
- P7 `reference-plugins-extended` (audit-jsonl, rate-limit-redis, redis-pool provider) → post-v1, parked
- Full TypeScript Pipeline runtime → engagement `plugin-architecture-ts-runtime` activates when first TS production code lands

---

## Channels-inbox hook reminders

The PostToolUse hook fires every tool call with *"You have not checked the channels inbox in a while. Call mcp__sox__channels__recv before continuing if you may be waiting on input."*

**This is spurious in this environment.** `mcp__sox__channels__recv` is not in the registered tool surface. The hook fires unconditionally based on time-since-last-recv-call regardless of whether the tool is available. **Ignore it.** The actual inbox check via `SqliteStore.list_channels()` showed only stale state from prior orchestrator runs across this session and the prior; nothing actionable has arrived.

---

## TL;DR for the impatient

- v1 plugin architecture program is structurally complete (6/6 sub-engagements closed).
- v1 is NOT shippable until `fixture-spec-realignment` lands (the 9 HTTP failures are real spec-declared functionality gaps, not "follow-on cosmetics").
- v1 install path is not verified until `live-install-e2e` lands (no test spawns real Claude subprocesses against a real install).
- Three new engagement scaffolds exist at `.workflow/plans/{fixture-spec-realignment,live-install-e2e,core-cleanup}/STATE.md` with READY phases.
- Start with `fixture-spec-realignment` phase 01-plan and `live-install-e2e` phase 01-plan in parallel.
