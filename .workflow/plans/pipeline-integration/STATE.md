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
| 01-plan | Concrete migration plan: route-by-route + tool-by-tool, observability shape, harness deletion sequencing | `READY` | sox-cto-system:planner | 0 | 2026-05-01T15:00:00Z |
| 02-build-stdio | Wire `build_default_pipeline` into mcp_server lifespan; convert all 15 tool handlers from direct-store to `Pipeline.dispatch` | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 03-build-http | Plumb pipeline through `build_app`; convert all 22 routes; delete `PassthroughIdentityResolver`; reduce `adapters/transports/http/auth.py` to `extract_bearer_token` only | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 04-observability | Extend `metadata["middleware_timings"]` to a structured `metadata["pipeline_trace"]` array (per-plugin {plugin_id, kind, started_at, finished_at, verdict, error_code?}). All plugins emit via Pipeline base, not per-plugin opt-in. (Risk #7) | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 05-concurrency-fix | Bundle the verifier replay-cache `asyncio.Lock` fix flagged in hooks-middleware:04-review (becomes reachable when auth runs per-request) | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 06-delete-harness-substitution | **Delete `tools/conformance_runner.py:805-813`** + `_registered_agents` field. The symbolic milestone of the program. Risk #5: parallel CI matrix (`conformance-substitution-removed` mandatory; `conformance-legacy` slated for removal in v1.1) | `BLOCKED` | python-pro | 0 | 2026-05-01T15:00:00Z |
| 07-server-side-rejection-fixture | New conformance fixture asserting unknown-credential rejection arrives via sox-error envelope from the server, not synthesized client-side | `BLOCKED` | test-automator | 0 | 2026-05-01T15:00:00Z |
| 08-review | Code review of integrated pipeline + observability + concurrency-fix + harness deletion | `BLOCKED` | code-reviewer | 0 | 2026-05-01T15:00:00Z |

## Currently next action

`01-plan` is `READY`. Wait for second workflow-optimizer pass on the umbrella parent before dispatching planner.

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

## Reference

See parent analysis at [`../plugin-architecture/analysis.md`](../plugin-architecture/analysis.md) §4.1 + §7.5 (risks #5 and #7) + §7.6 (F absorbed).
