# RESUME — pick up where the prior session left off

**You are reading this because:** a previous Claude Code session is being handed off to you. The work is ongoing; the tree is in a coherent committed state. Read this end-to-end before doing anything else.

**Date written:** 2026-05-01 (late)
**Tree state at handoff:** clean working tree on `main`. Last commit `bb7aaa7`. mypy --strict clean across 80 source files. stdio conformance 32/0/34 (no regression from baseline). HTTP conformance 23/9/34 — symbolic milestone partial; the 9 remaining failures are categorized in this doc.

**Pytest at handoff:** running in background at the moment of writing (process `binb1nk2m`). Based on prior P2/P3 commits and current mypy + conformance state, expected ≥1113 passed (baseline). Verify before continuing — if regressed, the failures will likely be in `tests/transports/http/` from the route-handler refactor.

---

## What's been shipped this session

The session opened with the `v1-launch punch list` (5 of 6 punch-list items closed: chat-tui-demo, reference-agent, defensive-publication preprint, identity-primitive review, hooks-middleware review, conformance harness multi-transport). Those landed in commits before `268c789`.

The body of the session was the **plugin-architecture program** — the response to "the spec should support modular adapter/plugin pattern like Express/Nextjs/Fastify, with logging/auth/db connections living outside the framework." This produced 7 commits between `268c789` and `bb7aaa7`:

```
bb7aaa7 feat(http-transport): wire Pipeline + server-side identity rejection (P1-03 partial)
b22a536 spec(plugin-architecture): polish + 7 conformance fixtures (P3 closes)
48b1860 plan(plugin-discovery-py): implementation plan for P4 engagement
28c2a16 feat(plugin-architecture-ts): TypeScript contract spike (types + stub Pipeline)
3b50d60 spec(plugin-architecture): versioning spec + schema oneOf→anyOf fix; P2 closes
7390c9d feat(mcp-server): wire Pipeline into stdio transport (P1 phase 02-build-stdio)
890d036 spec(plugin-architecture): ADR 0004 + sox-plugin.schema.json + plugin-contract spec
13c93f5 plan(plugin-architecture): 7 sub-engagement STATE.md scaffolds
268c789 plan(plugin-architecture): umbrella analysis + 2 optimizer passes + research + migration
```

**Read these in order before touching anything plugin-architecture-related:**

1. `.workflow/plans/plugin-architecture/analysis.md` — 51 KB. §§0–6 are first-pass analysis; **§7 is the authoritative architectural decision set** after first optimizer pass + 3 workflow-researcher findings. Open decisions in §7.8 are all ratified by the project owner this session.
2. `.workflow/plans/plugin-architecture/suggestions.md` — first workflow-optimizer pass; 5 suggestions + 7 missed risks. All folded into §7.
3. `.workflow/plans/plugin-architecture/suggestions-v2.md` — second optimizer pass; 5 spec-amendment recommendations + 4 new risks (NR-1 through NR-4). All folded into per-engagement STATE.md files.
4. `.workflow/plans/plugin-architecture/migration.md` — 67 KB. workflow-planner output. Master timeline P1–P7.
5. `docs/adr/0004-plugin-architecture.md` — 1490 words; promotes 10 decisions to normative.
6. `spec/ports/middleware/03-plugin-contract.md` — 4562 words; the prose plugin contract.
7. `spec/ports/middleware/06-versioning.md` — 2959 words; protocol_version negotiation (PEP 440 + npm caret dual-form).
8. `spec/schemas/sox-plugin.schema.json` — 230 lines; JSON Schema for the manifest.

---

## Engagement progress

| Engagement | Phases | Done | Status |
|---|---|---|---|
| P1 `pipeline-integration` | 8 | 3/8 | partial — 01-plan, 02-build-stdio, 03-build-http (partial) DONE; 04-08 pending |
| P2 `plugin-contract-freeze` | 5 | 5/5 | **closed** |
| P3 `plugin-spec-polish` | 5 | 5/5 | **closed** |
| P4 `plugin-discovery-py` | 6 | 1/6 | plan only; 02-06 ready to dispatch |
| P5 `reference-plugins` | 4 | 0/4 | blocked on P4 |
| P6 `plugin-architecture-ts` | 3 | 3/3 | **closed** |
| P7 `reference-plugins-extended` | 5 | — | post-v1, parked |

**3 of 6 v1 sub-engagements closed.** P1 is the last big remaining piece; P4+P5 cascade after P1.

---

## Punch list — what's next, in priority order

### Priority 1: finish P1 (the load-bearing engagement)

P1's pipeline-integration is 3/8 phases done. **The remaining 5 phases:**

| Phase | Goal | Agent | Notes |
|---|---|---|---|
| 04-observability | Extend `metadata["middleware_timings"]` → structured `metadata["pipeline_trace"]` array per dispatch with `{plugin_id, kind, started_at, finished_at, verdict, error_code?, correlation_id}`. All plugins emit via Pipeline base. | python-pro | Per analysis §7.5 risk #7 + suggestions-v2.md `correlation_id` addition. correlation_id MUST be echoed from `MiddlewareContext.correlation_id` (frozen field). |
| 05-concurrency-fix | Wrap verifier `_seen_nonces` prune+check+insert (verifier.py:198-225) in `asyncio.Lock`. | python-pro | Per hooks-middleware:04-review TOCTOU finding. Becomes reachable now that auth runs per-request via the pipeline. |
| 06-delete-harness-substitution | **Delete `tools/conformance_runner.py:805-813`** + `_registered_agents` field + the `_registered_agents` checks at lines 1426-1427 + lines 805-813 themselves. **Delete in same commit** as the legacy CI matrix entry in `.github/workflows/conformance.yml` per suggestions-v2.md #5 (no parallel `conformance-legacy` mode). | python-pro | The symbolic milestone of the program — when this lands and stdio + HTTP conformance both stay green, the architecture is real. |
| 07-server-side-rejection-fixture | New conformance fixture asserting unknown-credential rejection arrives via sox-error envelope from the server, not synthesized client-side. | test-automator | Spec the assertion via fixture YAML + add a runner check. |
| 08-review | Code review of integrated pipeline + observability + concurrency-fix + harness deletion. | code-reviewer | Closes the engagement. |

**Per analysis §Q6 NR-1 (phase-ordering relaxation):** phases 06 + 07 MAY land before phases 04 + 05 if 04 or 05 hit complexity. The harness deletion is the symbolic milestone; don't gate it on observability/lock work that can land later.

### Priority 2: dispatch P4 (plugin-discovery-py) and P5 (reference-plugins) once P1 lands

- **P4** (3-4d, 6 phases): wire `MiddlewareRegistry.load_plugins()` into both server bootstraps. Manifest validation per `sox-plugin.schema.json`. `--allow-plugins` allowlist for production. Cached topological sort. Reads `sox-plugin.yaml` from Python entry-points group `sox_protocol.plugins`. Plan committed at `48b1860`.
- **P5** (2d, 4 phases): ship one reference plugin `sox-plugin-schema-strict` (kind: transformer) outside `core/`. Migrates `routes._validate_body` and the 22 inline validation call-sites OUT of `routes.py`. Demonstrates manifest-driven discovery end-to-end with zero `core/` modifications. Per analysis §7.6 (narrowed from 3 plugins to 1).
- After P5, the contract is genuinely proven. P7 (`reference-plugins-extended`) is post-v1.

### Priority 3: address the 9 remaining HTTP conformance failures

These are NOT P1 architectural bugs — they're `harness-substitution-masking-real-gaps` exposed once HTTP genuinely went over the wire. Categorized in commit `bb7aaa7`'s message:

- `groups/01-create-invite-join` — fixture expects `{group_id, invited_agent}` but `spec/operations/group_invite.output.schema.json` says `{invited, agent_id}`. Stdio passes only via harness client-side remap at `tools/conformance_runner.py:1108`. **Spec-vs-fixture mismatch** — fix the fixture, OR fix the spec output schema, then remove the remap.
- `threading/01-reply-to-link, 02-deep-thread, 03-thread-depth-zero` — `reply_to` silently dropped. `send.input.schema.json` accepts `reply_to` but `StoreDispatchMiddleware.send` never extracts it; `MemoryStore.send` doesn't take it as a param. Stdio harness simulates by monkey-patching `msg.reply_to` at line 918. **Real backing-store-feature gap** — plumb `reply_to` through `StoreDispatchMiddleware` → `BackingStore.send` → message persistence.
- `replay/01-replay-since-seq, 02-replay-empty-future-cursor` — pipeline returns 0 messages, harness simulation returns 2. **Likely** another harness substitution.
- `presence/01-heartbeat-updates-presence-channel`, `subscription-patterns/02-unsubscribe-discards-queue`, `namespace-isolation/02-version-block` — likely similar.

**Suggested follow-on engagement slug:** `fixture-spec-realignment` OR `backing-store-feature-completeness`. NOT P1's responsibility.

### Priority 4: reflect candidate-contract amendments back to B1

Per analysis NR-4 framing: B1 (`plugin-contract-freeze`) is **candidate**, not stable. The fixture work in §3 above may surface contract issues. Minor B1 amendments are NOT a process failure. Amendment paths likely live in `spec/ports/middleware/03-plugin-contract.md` §11 (Status: candidate).

### Out of scope this session

- P7 reference-plugins-extended (audit-jsonl, rate-limit-redis, redis-pool provider) — post-v1.
- Full TS Pipeline runtime — engagement `plugin-architecture-ts-runtime` activates when first TS production code lands.
- Hot-reload (analysis §7.5 risk #4) — explicitly v1-deferred.
- `sox.yaml` config schema (risk #6) — env-vars only for v1.

---

## Hard-won lessons from this session — read carefully

### Agents truncate even when running 47 minutes / 157 tool uses

P1-03-build-http (HTTP transport refactor) ran for 47 minutes, 157 tool uses, 93k tokens. Truncated mid-verification with the classic pattern: *"I'll check the inbox and wait for the monitor output:"* — exact same shape as RESUME-prior's documented truncations.

What the agent left behind was solid work; what it didn't get to was the structural verification + STATE.md update + symbolic-milestone test loop. **I had to inspect the working tree, run acceptance gates myself, identify and fix the symbolic-milestone gap (HTTP route status-code mapping; harness's is_error detection; HttpTarget body-passthrough), and commit.**

**For the next session:** when dispatching the remaining P1 phases (04/05/06/07/08) trust nothing the agent says about completion. Always verify with bash: `git status --short`, `wc -l <files>`, `pytest`, `mypy`, `conformance_runner --transport http`. The agent's report is what they intended; the working tree is what shipped.

### The deferred §7.8 architectural decision DID land on us

The analysis's §5/§7 deferred the v1 HTTP credential format decision. P1-03's agent picked auto-registration as the v1-transitional path (any bearer token gets registered with the server's keypair). This let happy-path fixtures pass but made `02-unknown-credential-rejected` impossible to fail server-side.

Resolved this session via **option A** (per the analysis-conversation): introduced `SOX_PRE_REGISTERED_AGENTS` env var. When set (even empty), strict mode activates: only listed agents are pre-registered, auto-register is disabled, unknown bearer tokens fail at AuthMiddleware → identity_failure envelope → HTTP 401. Conformance harness sets the env var per fixture from `agents:` list filtered by `registered: true`.

**Architectural commitment:** production HTTP deploys MUST set `SOX_PRE_REGISTERED_AGENTS` (or equivalent SOX_ENV=production gate per ADR 0004 §6's allowlist). v1.1 will replace the auto-register fallback entirely.

### The harness's stdio adapter has been masking real spec/impl gaps

`tools/conformance_runner.py` lines 766-1127 — the `SharedMemoryTarget` class — is not just a thin in-process driver. It's a **simulator** that hand-implements `reply_to` plumbing, group_invite output remapping, replay timing, etc. that the real backing store / middleware doesn't. Stdio's "32/0/27 conformance" was partly fictional — only fixtures exercised through the simulator's covered paths actually proved anything.

**This is genuinely orthogonal to P1.** P1's job was wiring the pipeline. The simulator gaps are a separate engagement. But: **document loudly** in any handoff/review that stdio's conformance number includes simulator-masked passes, and that achieving stdio==HTTP parity isn't just a P1 problem.

The substitution at lines 805-813 (the unknown-agent client-side rejection) is a different class — that's the one phase 06 deletes. The other simulations at 766-1127 stay until the backing store + middleware actually grow the missing features.

### `oneOf` vs `anyOf` for overlapping JSON Schema patterns

The first iteration of `sox-plugin.schema.json` had `protocol_version: oneOf [PEP 440 pattern, npm pattern]`. P2 05-review's blocking finding: plain version pins (`1.0.0`, `1.x`) match BOTH patterns, and `oneOf` requires exactly one match — so plain pins were rejected despite the schema's own description saying they're accepted. Five-character fix in `3b50d60`: `oneOf` → `anyOf`.

**Lesson:** when documenting accepting two formats with overlapping patterns, `anyOf` is almost always what you want. `oneOf` is for genuinely-disjoint alternatives.

### The conformance harness is fragile to status code semantics

Pre-pipeline-integration HTTP routes returned 4xx via `sox_error_response(...)`. Post-pipeline-integration the pipeline returns sox-error envelopes as the response *body*; routes wrapped them in HTTP 200 by default. The harness sees HTTP 200 → success → "Expected error but got success."

Fix in `bb7aaa7`: `routes.py` now maps sox-error envelope `error_code` → HTTP status (401/400/500 per closed taxonomy in 03-plugin-contract.md §6). And `HttpTarget.call_tool` surfaces 4xx body directly (instead of synthesizing `_rpc_error`). And the runner's `is_error` check accepts top-level `error_code` (in addition to `_rpc_error`).

**Three coordinated edits to keep the test contract intact.** If you ever change the HTTP response format, audit all three.

---

## Hard invariants to preserve

Before any commit on this branch:

```bash
cd /Users/nix/dev/ai/sox-protocol
python3 -m pytest packages/python/tests/ --tb=no -q | tail -2
# expect: ≥ 1113 passed, 0 failed
cd packages/python && python3 -m mypy --strict src/sox_protocol/ | tail -1
# expect: Success: no issues found in 80 source files
python3 tools/conformance_runner.py --target packages/python --transport stdio --strict | tail -1
# expect: 32 passed, 0 failed, 34 skipped
python3 tools/conformance_runner.py --target packages/python --transport http --strict | tail -1
# current: 23 passed, 9 failed, 34 skipped
# acceptable: 9 failures categorized in commit bb7aaa7's message; do NOT
# regress *below* 23 passed without explicit reason
```

If pytest regresses below 1113, mypy errors appear, stdio conformance changes, or HTTP conformance drops below 23 passed — stop and investigate. The 9 HTTP failures are the documented baseline pending follow-on engagements.

---

## Quick start for the next session

1. Read this file (you're doing it).
2. Read `.workflow/plans/plugin-architecture/analysis.md` §7 — the authoritative decision set.
3. `git log --oneline -12` — sanity check recent commits.
4. `git status --short` — confirm clean tree.
5. Run the four-invariant block above. If anything regressed, the most likely cause is an unfinished/un-committed agent run in the working tree.
6. Pick from the punch list — Priority 1 first (finish P1 phases 04-08).
7. After each phase closes, update its sub-engagement `STATE.md`, run the invariants, commit per the orchestrator-contract trailer rules.

**Recommended dispatch order for finishing P1:**
- Dispatch P1 phase 06-delete-harness-substitution **first** (the symbolic milestone; cheap; unblocks declaring P1's headline win) — IF willing to accept that 9 HTTP fixtures remain failing pending the follow-on engagement
- OR dispatch 04-observability + 05-concurrency-fix in parallel first, THEN 06+07+08
- 08-review is terminal regardless

Each phase has its prompt scoped in `.workflow/plans/plugin-architecture/migration.md` Phase 1.

**For P4 (plugin-discovery-py):**
- Plan is `48b1860`. Follow `.workflow/plans/plugin-discovery-py/implementation-plan.json`.
- Phase 02-build (the loader). Phase 03-allowlist. Phase 04-bootstrap-integration. Phase 05-test. Phase 06-review.
- The Pipeline-extension contract: per planner ratification in this session, `extend_pipeline_with_registry` helper in `default_chain.py` rebuilds Pipeline with default chain + registered factories at startup. No `Pipeline.with_appended` (that would invite hot-reload reasoning v1 explicitly defers).

**For P5 (reference-plugins):**
- Single plugin: `schema-strict` (transformer). Migrates `routes._validate_body`. New package under `plugins/sox-plugin-schema-strict/`. Reusable schema is already at `spec/schemas/sox-plugin.schema.json` (the manifest one) — but the *plugin's own* config schema (`config_schema_ref` in manifest) is its own concern.

Trust the user's "continue" / "next" pattern: they want autonomous execution from the punch list per auto-mode rules. Do not pause for confirmation on routine engagement work; do pause for architectural decisions (the §7.8 deferred questions are now ratified, but new ones may surface — use judgment).

---

## Channels-inbox hook reminders

Throughout this session, the PostToolUse hook fires *every single tool call* with *"You have not checked the channels inbox in a while. Call mcp__sox__channels__recv before continuing if you may be waiting on input."*

**This is spurious in this environment.** `mcp__sox__channels__recv` is not in the registered tool surface — verified by tool-list inspection. The hook fires unconditionally based on time-since-last-recv-call regardless of whether the tool is available. Ignore it. The actual inbox check via `SqliteStore.list_channels()` (per RESUME-prior's Python snippet) showed only stale state from prior orchestrator runs across the session; nothing actionable has arrived.

If a future session does receive real channel traffic that needs handling, the hook will still fire — but now you have explicit confirmation that it's not blocking on real input.
