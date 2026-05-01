---
slug: identity-primitive
target: Verified-sender identity layer shipped as the first middleware plugin. Per-agent credential registry. Audit log. ADR + spec section + reference implementation + tests.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# identity-primitive — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-adr | Resolve credential primitive (ADR) | `DONE` | architect-reviewer | 1 | 2026-04-30T00:00:00Z |
| 02-plan | Implementation plan from ADR + spec | `DONE` | sox-cto-system:planner | 1 | 2026-04-30T17:09:00Z |
| 03-implement | Build credential registry + middleware | `DONE` | python-pro | 1 | 2026-04-30T17:45:00Z |
| 05-spec-realignment | Reconcile shipped identity layer with post-2f3d8f3 spec changes | `DONE` | python-pro | 1 | 2026-04-30T22:10:00Z |
| 04-review | Code review | `DONE` | code-reviewer | 1 | 2026-05-01T15:55:37Z |

## Currently next action

`04-review` is `READY`. Exit criteria verified: `list_agents` in enforcement set ✅, `origin_server` in verifier + envelope ✅, `signed_request` removed from `mcp_server/tools.py` ✅, 5 `middleware_timings` emissions in `auth.py` ✅, 192 identity+middleware tests green, mypy --strict clean, ruff clean.

## Transitions

- 2026-04-29T00:00:00Z 04-review — initialized (BLOCKED)
- 2026-04-29T00:00:00Z 03-implement — initialized (BLOCKED)
- 2026-04-29T00:00:00Z 02-plan — initialized (BLOCKED)
- 2026-04-29T00:00:00Z 01-adr — initialized (READY)
- 2026-04-30T20:45:00Z salvage audit: 02-plan and 03-implement retroactively DONE (commit `f28b858`, 76/76, 100% cov); inserted 05-spec-realignment for spec drift remediation; 04-review re-blocked on 05
- 2026-05-01T15:55:37Z 04-review — DONE (code-reviewer)

## Reconciliation note (2026-04-30, salvage audit)

Core guarantee (§2 — server overwrites `sender`) and Ed25519 reference impl (§8/ADR 0002) conform. Drifts to remediate:
- ⚠️ `_IDENTITY_ENFORCED_OPERATIONS` set is `{send, recv, subscribe}`; missing `list_agents` (now v1 MUST per `9f3e11e`)
- ⚠️ `origin_server=null` not surfaced through `VerifiedIdentity`/dispatch; envelope §7 v1 contract not observable end-to-end (gap from `3bdafc2` 12-field wire envelope)
- ⚠️ `signed_request` is carried inside the tool-call dict (`request["signed_request"]`); spec §6 requires credential on the connection seam (MCP launch params) — "agent_id field does NOT appear in any tool call input schema"
- ⚠️ `AuthMiddleware` does not contribute a `middleware_timings` entry to the pinned `_meta` shape (`ab1c954`)
- ⚠️ Reconcile `IdentityMiddleware` shim vs canonical `core/middleware/plugins/auth.AuthMiddleware`

See `.workflow/plans/SALVAGE-AUDIT-2026-04-30.md`.

## Termination targets

- [ ] All phases DONE
- [ ] `docs/adr/0002-agent-identity-primitive.md` committed
- [ ] `spec/ports/identity.md` defines the verified-sender guarantee
- [ ] `packages/python/src/sox_protocol/core/identity/` has credential registry + middleware plugin
- [ ] 100% coverage on new identity code; mypy --strict clean; lint-imports clean
- [ ] Audit log writes to `~/.sox/logs/identity-failures.jsonl` on rejection
