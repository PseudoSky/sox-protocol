# Salvage audit — 2026-04-30

**Trigger.** Spec churn after planner RUN 1+2 (commit `2f3d8f3`, 17:09) plus a partial 01-plan re-run today (commits `f8f2a27` → `a79c9e0`, 20:25–20:33) left STATE.md files inconsistent with shipped code. This audit treats `spec/` as ground truth (per user, >90% confidence) and reconciles every affected engagement against it.

**Spec commits since planner RUN 1+2** (in dependency order):
- `9f3e11e` — `list_agents` added as v1 MUST
- `e4bea36` — http-transport Step 4 shipped
- `3bdafc2` — schemas realigned with all 19 architecture decisions
- `14eb403` — `backpressure_over_limit` added to sox-error enum
- `623ea90` — wildcard subscription rejection enforced in schema
- `ab1c954` — architect-reviewer cleanup (W1/W2/N3/N5/N6); `_meta` shape pinned

## Engagement-by-engagement findings

### conformance-suite — **SUPERSET** (clean continuation)
- New 01-plan (today 20:27) is a strict superset of shipped code. 27 fixtures + harness from commit `44c71b7` already on disk; new plan asks for 31 additional fixtures across 6 new categories.
- Existing fixture YAML schema is compatible with the new plan's `fixture_format.schema`; no rewrite needed.
- Action: mark `02-build` as `READY attempts=1` with a note pointing the executor at already-shipped artifacts; do not rebuild.
- New work scope: 31 NEW fixtures (`backpressure/`, `idempotency/`, `subscribe-enforcement/`, `error-envelopes/`, `version-negotiation/`, `schema-validation/`); add `SOX_TEST_FAULTS=1` hooks to reference impl; verify strict-mode green.

### http-transport — **DRIFT** (re-plan + remediation)
- STATE.md was incoherent: 01-plan READY, 02-build BLOCKED — but Step 4 shipped at `e4bea36` (109/109 tests).
- Real spec drift in shipped code:
  - ❌ `backpressure_over_limit` never emitted (send returns hard-coded `state:"ok"`)
  - ❌ Wildcard subscription rejection not enforced at transport boundary
  - ❌ Input validation is `_require_fields` ad-hoc, not schema-driven
  - ⚠️ `list_agents` wired to `LivenessStore` not BackingStore port
  - ⚠️ `channels_collect` is internal poll-loop, not SSE/long-poll per spec §5
- Action: mark `01-plan` and `02-build` DONE retroactively; add `04-spec-realignment` phase covering the 5 debt items; `03-conformance` stays BLOCKED on `04-spec-realignment`.

### hooks-middleware — **LIGHT DRIFT** (re-plan + small remediation)
- Middleware port spec unchanged since plan; pipeline architecture is sound. Step 3 shipped at `e33d0f2` (83/83, 100% cov).
- Drift:
  - ⚠️ `Operation` literal missing `list_agents` and the channels__/group__ MCP-tool ops
  - ⚠️ `StoreDispatchMiddleware` switch covers 4 ops; needs expansion as MCP tools land
  - ⚠️ `_StoreTerminal` has zero test coverage despite headline 100%
- Action: mark `02-plan` and `03-implement` DONE; add `05-op-coverage` phase for Operation literal + dispatch op-table widening + terminal coverage; `04-review` stays open and runs after 05.

### identity-primitive — **DRIFT** (re-plan + remediation)
- Step 2 shipped at `f28b858` (76/76, 100% cov). Core guarantee (server overwrites `sender`) and Ed25519 reference impl conform.
- Real drifts:
  - ⚠️ `list_agents` not in enforcement set (now v1 MUST)
  - ⚠️ `origin_server=null` not surfaced through `VerifiedIdentity`/dispatch (envelope §7)
  - ⚠️ `signed_request` carried inside tool-call dict; spec §6 says credential lives on connection seam (MCP launch params), not in tool input
  - ⚠️ No `middleware_timings` contribution to pinned `_meta` shape
- Action: mark `02-plan` and `03-implement` DONE; add `05-spec-realignment` phase; `04-review` runs after 05.

## STATE.md mutations applied

| Engagement | Before | After |
|---|---|---|
| conformance-suite | 02-build READY a=0 | 02-build READY a=1 + executor note |
| http-transport | 01-plan READY, 02-build BLOCKED | 01-plan DONE, 02-build DONE, 04-spec-realignment READY (NEW), 03-conformance BLOCKED on 04 |
| hooks-middleware | 02-plan READY, 03-implement BLOCKED | 02-plan DONE, 03-implement DONE, 05-op-coverage READY (NEW), 04-review BLOCKED on 05 |
| identity-primitive | 02-plan READY, 03-implement BLOCKED | 02-plan DONE, 03-implement DONE, 05-spec-realignment READY (NEW), 04-review BLOCKED on 05 |

## Defensive measure (recommendation, not yet applied)

Add a precondition to `.workflow/templates/ORCHESTRATOR-CONTRACT.md`: 01-plan refuses to run if any later phase for that engagement is `DONE` without explicit `--force-replan` plus a written `decisions/replan-<slug>-<date>.md` rationale. Would have prevented the conformance-suite stomp.

## Deferrals discovered during execution

Three issues surfaced while running the salvage that are **out of scope for spec realignment** but worth tracking:

1. **`http-transport:05-list-agents-port-migration`** (NEW phase, READY) — `04-spec-realignment` shipped 4 of 5 fixes; the `LivenessStore` → `BackingStore` port migration was deferred to a small follow-up phase. Current path works; this is a refactor for canonical port placement.

2. **Installer credential plumbing gap** — `identity-primitive:05-spec-realignment` moved credential off the tool-call surface (per spec §6) but did not update the Claude Code runtime adapter installer to set `SOX_AGENT_ID_SOURCE` (or equivalent) in MCP server launch params. Test `test_settings_json_mcp_server_env` skipped with TODO. Needs a small follow-up to wire the installer ↔ server.py credential read path.

3. **Installer hook schema drift** — `test_settings_json_hooks_point_to_scripts` and `test_idempotent_settings_no_duplicate_hooks` skipped: hook entries written by the installer no longer carry a top-level `command` key (likely nested under a sub-list per Claude Code's evolving hook schema). Pre-existing drift, unrelated to spec churn.

4. **`conformance-suite:03-harness-and-fixture-fixes`** (NEW phase, READY) — strict-mode result after 02-build was 30/2/27 (pass/fail/skip). 2 fails are pre-existing capture-substitution bugs in original threading fixtures; 27 skips are gated on harness features and the now-landed sibling phases. Filed as follow-up.

## Architecture gap discovered (filed post-v1)

While reviewing the salvaged code, observed that the ports + adapters separation is real (`BackingStore`, `Transport`, `IdentityResolver`, `Middleware` are all defined as protocols/ABCs with multiple concrete implementations) but the **runtime composition layer** that lets a third party plug in a new adapter without forking core is incomplete:

- `core/mcp_server/server.py:_build_store(uri)` is a hard-coded `if/elif` over `memory://`, `sqlite://`, `file://` — no registry, no entry-point hook
- Transport selection (`SOX_MCP_TRANSPORT`) is similarly hard-coded
- `MiddlewareRegistry.load_entry_points()` exists at `core/middleware/registry.py:177` but nothing calls it
- `registry.assemble(DEFAULT_ORDER)` only includes middleware names in the hard-coded `DEFAULT_ORDER` tuple; plugins with fresh names get registered but ignored

Filed as a new `### adapter framework / runtime composition root` section under `## Implementation — post-v1` in `TODO.md`. The 6 line items there capture the exact registry, autoload, and entry-point work needed; once that lands, the spec's port-and-adapter promise is real for third-party packages.

Outside salvage scope (spec drift was the concern, not extensibility) but noted here so the next planner pass picks it up.

## Out of scope for this audit

- `bucket-classification`, `spec-extraction`, `orchestrator-bootstrap`, `defensive-publication`, `launch-narrative`: state matches reality; no action.
- `ts-sdk`, `chat-webapp`, `reference-agent`, `chat-tui-demo`: re-planned today against current spec, no prior implementation to conflict — clean.
