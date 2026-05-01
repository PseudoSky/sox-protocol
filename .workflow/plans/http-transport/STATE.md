---
slug: http-transport
target: HTTP transport adapter shipped, satisfying the Transport port. SSE/WebSocket for live recv. OpenAPI spec generated. Conformance suite passes against HTTP transport identically to stdio.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# http-transport — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Port + OpenAPI plan | `DONE` | sox-cto-system:planner | 1 | 2026-04-30T17:09:00Z |
| 02-build | Build adapter + serve subcommand | `DONE` | python-pro | 1 | 2026-04-30T19:00:00Z |
| 04-spec-realignment | Reconcile shipped HTTP transport with post-2f3d8f3 spec changes (4/5 fixes) | `DONE` | python-pro | 1 | 2026-04-30T22:55:00Z |
| 05-list-agents-port-migration | Migrate `list_agents` from `LivenessStore` to `BackingStore` port | `DONE` | python-pro | 1 | 2026-04-30T23:25:00Z |
| 03-conformance | Run conformance against HTTP | `BLOCKED` | test-automator | 1 | 2026-05-01T00:00:00Z |

## Currently next action

`03-conformance` is `BLOCKED` on a follow-on engagement (HTTP/middleware bridge). Sub-task progress:
- ✅ Harness extended: `tools/conformance_runner.py` accepts `--transport stdio|http` (185 added lines, commit-pending). `--transport http` spawns a fresh `sox serve --transport http` subprocess per fixture on an ephemeral port.
- ✅ stdio regression check: `python3 tools/conformance_runner.py --target packages/python --transport stdio --strict` → 32 passed, 0 failed, 27 skipped (matches baseline).
- ❌ HTTP target acceptance: `python3 tools/conformance_runner.py --target packages/python --transport http --strict` → 22 passed, **10 failed**, 27 skipped. Divergence is real, not a fixture problem.
- ❌ CI matrix not enabled: `.github/workflows/conformance.yml` still has `# - python-reference-http` commented; will enable after the bridge engagement closes.
- ✅ `spec/conformance/README.md` documents the matrix (Method 2 — HTTP target).

### Divergence — root cause (2026-05-01)

The HTTP transport bypasses the core middleware pipeline entirely. `routes.py` calls `_auth_and_body()` (uses `PassthroughIdentityResolver` from `auth.py:47-68` which accepts any non-empty bearer token as agent_id verbatim), then dispatches directly to `BackingStore` methods. This means:

- `AuthMiddleware._IDENTITY_ENFORCED_OPERATIONS` is **never consulted** on the HTTP path
- No `middleware_timings` in `_meta` for HTTP responses (silently violates `ab1c954` envelope contract)
- No `IdentityVerifier` cryptographic check on credentials (`PassthroughIdentityResolver` is documented "for development")

10 failing fixtures (8 unique, listed twice for stderr+stdout of conformance harness):
- `identity-verification/02-unknown-credential-rejected` — HTTP accepts unknown creds (security regression)
- `groups/01-create-invite-join`, `presence/01-heartbeat-updates-presence-channel`, `replay/01-replay-since-seq`, `replay/02-replay-empty-future-cursor`, `subscription-patterns/02-unsubscribe-discards-queue`, `threading/01-reply-to-link`, `namespace-isolation/02-version-block` — likely cascading from same bridge gap (need per-fixture triage).

### Required follow-on

New engagement (suggested slug: `http-middleware-bridge`) should:
1. Replace `routes._auth_and_body` direct-store dispatch with a call into `Pipeline.dispatch(operation, input, connection_id, metadata={"_connection_credential": token})` so the same middleware chain (auth, store_dispatch, etc.) runs for both transports.
2. Wire a real `IdentityVerifier` (not `PassthroughIdentityResolver`) for the HTTP transport.
3. Re-run conformance — expect 32/0/27 parity with stdio.
4. Enable the CI matrix entry.

## Reconciliation note (2026-04-30, 04 partial completion)

`04-spec-realignment` shipped 4 of the 5 audit fixes:
- ✅ Schema-driven input validation (22 validator references in `routes.py`)
- ✅ Wildcard subscription rejection (`_wildcard_forbidden` per `spec/operations/subscribe.input.schema.json`)
- ✅ `backpressure_over_limit` emission in `op_send` (3 references)
- ✅ `channels_collect` degraded-mode documented (`x-degraded-mode` in `openapi.yaml`, docstring note in `routes.py`)
- ⏭ `list_agents` → BackingStore migration **deferred to 05** (8 LivenessStore refs + 1 import remain in `routes.py`; this was rated ⚠️ drift in the audit, not a spec violation — current path works)

Side effect: `04-spec-realignment` widened `BackingStore.send()` from 3-tuple to 4-tuple `(message_id, sent_at, seq, BackpressureInfo)` per spec realignment. Two src/ call-site arity mismatches were patched in-flight (`store_dispatch.py`, `mcp_server/tools.py`). Test-side harmonization is in progress (separate fixup agent).

184 HTTP transport tests pass; openapi.yaml validates clean.

## Reconciliation note (2026-04-30, salvage audit)

01-plan and 02-build retroactively marked DONE: code shipped in commit `e4bea36` ("Step 4 — HTTP transport adapter + serve subcommand, 109/109, 90.97% cov") satisfies the original plan, but the spec moved under it (commits `9f3e11e`, `3bdafc2`, `14eb403`, `623ea90`, `ab1c954`). See `.workflow/plans/SALVAGE-AUDIT-2026-04-30.md`.

## Termination targets

- [ ] All phases DONE
- [ ] `packages/python/src/sox_protocol/adapters/transports/http/` shipping
- [ ] `sox serve --transport http` works
- [ ] `spec/transports/http/openapi.yaml` generated
- [ ] Conformance suite passes against HTTP target identically to stdio
