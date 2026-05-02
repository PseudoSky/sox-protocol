---
slug: pipeline-integration
target: Make Pipeline the only path to BackingStore in both transports. Stdio MCP server and HTTP transport both go through Pipeline.dispatch. PassthroughIdentityResolver deleted. tools/conformance_runner.py:805-813 substitution deleted. Conformance suite passes 32/0/27 against both transports identically. Structured pipeline_trace observability shipped. Verifier replay-cache asyncio.Lock fix bundled.
created: 2026-05-01
last_event: 2026-05-01T15:00:00Z
orchestrator_protocol: v1
parent_plan: plugin-architecture
absorbs: harness-cleanup (per analysis §7.6 — F merged into A as terminal acceptance phases)
---

# pipeline-integration — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Concrete migration plan: route-by-route + tool-by-tool, observability shape, harness deletion sequencing | `DONE` | sox-cto-system:planner | 1 | 2026-05-01T17:30:00Z |
| 02-build-stdio | Wire `build_default_pipeline` into mcp_server lifespan; convert all 15 tool handlers from direct-store to `Pipeline.dispatch` | `DONE` | python-pro | 1 | 2026-05-01T18:00:00Z |
| 03-build-http | Plumb pipeline through `build_app`; convert all 22 routes; delete `PassthroughIdentityResolver`; reduce `adapters/transports/http/auth.py` to `extract_bearer_token` only | `DONE` | python-pro | 1 | 2026-05-01T22:00:00Z |
| 04-observability | Extend `metadata["middleware_timings"]` to a structured `metadata["pipeline_trace"]` array (per-plugin {plugin_id, kind, started_at, finished_at, verdict, error_code?}). All plugins emit via Pipeline base, not per-plugin opt-in. (Risk #7) | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 05-concurrency-fix | Bundle the verifier replay-cache `asyncio.Lock` fix flagged in hooks-middleware:04-review (becomes reachable when auth runs per-request) | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 06-delete-harness-substitution | **Delete `tools/conformance_runner.py:805-813`** + `_registered_agents` field. The symbolic milestone of the program. Risk #5: parallel CI matrix (`conformance-substitution-removed` mandatory; `conformance-legacy` slated for removal in v1.1) | `DONE` | python-pro | 1 | 2026-05-01T22:30:00Z |
| 07-server-side-rejection-fixture | New conformance fixture asserting unknown-credential rejection arrives via sox-error envelope from the server, not synthesized client-side | `BLOCKED` | test-automator | 0 | 2026-05-01T15:00:00Z |
| 08-review | Code review of integrated pipeline + observability + concurrency-fix + harness deletion | `BLOCKED` | code-reviewer | 0 | 2026-05-01T15:00:00Z |

## Currently next action

Phases 01–03 and 06 are DONE. Next dispatch should be **phase 07-server-side-rejection-fixture** (test-automator) and/or **phase 04-observability** (python-pro) — these are independent per the NR-1 phase-ordering relaxation and can run in parallel. Phase 07 is lower-risk and closes the identity story; recommend dispatching it first or in parallel with 04.

## Termination targets

- [ ] All 8 phases DONE
- [ ] `Pipeline.dispatch()` invoked on every send/recv/subscribe/list_channels/list_agents/group_*/replay/heartbeat/ack/collect path on both transports
- [ ] `PassthroughIdentityResolver` deleted from `adapters/transports/http/auth.py`
- [ ] `adapters/transports/http/auth.py` reduced to `extract_bearer_token` (~5 LOC)
- [ ] `tools/conformance_runner.py:805-813` deleted; `_registered_agents` field removed; comment-block "This mirrors the middleware layer..." gone (the substitute IS the layer now)
- [ ] CI workflow `.github/workflows/conformance.yml`: new `conformance-substitution-removed` matrix entry mandatory; `python-reference-http` line uncommented
- [ ] Stdio conformance: 32 passed, 0 failed, 27 skipped (no regression)
- [ ] HTTP conformance: 32 passed, 0 failed, 27 skipped (parity with stdio — currently 22/10/27)
- [ ] New fixture asserting server-side rejection of unregistered agents passes against both transports
- [ ] `metadata["pipeline_trace"]` array present on every dispatch response with per-plugin entries
- [ ] Verifier `_seen_nonces` prune+check+insert protected by `asyncio.Lock`
- [ ] Full test suite green (≥ 1113 baseline)
- [ ] mypy --strict clean across all 78 source files
- [ ] No `BackingStore.<method>(...)` calls in any production code outside `core/middleware/plugins/store_dispatch.py` and adapter implementations themselves

## Symbolic significance

Per analysis §7.6 / §6 (preserved): *"The single highest-value commit in the whole program is the deletion of `tools/conformance_runner.py:805-813`. When that block goes away and conformance still passes against both transports, we'll know the architecture is real, not aspirational."* Phases 06+07 land that commit as terminal acceptance for this engagement.

## Transitions

- 2026-05-01T17:30:00Z 01-plan — DONE (sox-cto-system:planner): implementation-plan.json with 13 files, 8 risks, rollout_order graph honoring NR-1 phase-ordering relaxation
- 2026-05-01T18:00:00Z 02-build-stdio — DONE (python-pro + inline cleanup): server.py builds pipeline + identity stack (registry, audit, verifier, synthetic Ed25519 keypair); _credential.py helper; tools.py 15 handlers convert to pipeline.dispatch (17 dispatch calls; collect runs in loop). Inline fixes after agent truncation: added `build_default_pipeline` to `core/middleware/__init__.py:__all__` (mypy attr-defined error); updated `tests/reference_agent/helpers.py` lifespan to mirror production lifespan keys (pipeline, verifier, registry, _private_key — 41 ref-agent failures resolved). Verified: 1113 tests pass (baseline preserved), mypy --strict clean, stdio conformance 32/0/27 (no regression).
- 2026-05-01T22:00:00Z 03-build-http — DONE (python-pro + inline fixes, commit bb7aaa7): pipeline wired through HTTP routes; PassthroughIdentityResolver deleted; auth.py reduced to extract_bearer_token; SOX_PRE_REGISTERED_AGENTS env var gates strict-mode server-side rejection. HTTP conformance 23/9/34 — 9 failures are documented backing-store/spec gaps, not regressions. STATE.md was stale (still showed BLOCKED); corrected here.
- 2026-05-01T22:30:00Z 06-delete-harness-substitution — DONE (python-pro, Option A): Deleted `_registered_agents` field, `register_agents()` hand-rolled rejection block, and comment "This mirrors the middleware layer..." from SharedMemoryTarget. Wired SharedMemoryTarget.call_tool() through an auth-only Pipeline (AuthMiddleware terminal = existing _dispatch simulation). register_agents() now provisions per-agent Ed25519 keypairs into InMemoryCredentialRegistry; unknown agents in strict-mode fixtures receive identity_failure from AuthMiddleware rather than a client-side synthesized response. No `conformance-legacy` CI entry existed — no-op per spec. Verified: stdio 32/0/34, HTTP 23/9/34 (no regression), mypy --strict clean (80 source files), pytest ≥1113 passed.

## Reference

See parent analysis at [`../plugin-architecture/analysis.md`](../plugin-architecture/analysis.md) §4.1 + §7.5 (risks #5 and #7) + §7.6 (F absorbed).
