---
slug: core-cleanup
target: Resolve the architectural follow-ups documented in P1-08 + P4-06 + P5-04 REVIEW.md files. None are v1-blocking; all are debt that will compound. Single small engagement to clear them.
created: 2026-05-04
last_event: 2026-05-04T00:00:00Z
orchestrator_protocol: v1
parent_plan: plugin-architecture (post-v1-program follow-on)
prereqs: []  # all P1–P6 closed
priority: MEDIUM — non-blocking; defer if fixture-spec-realignment + live-install-e2e need bandwidth
---

# core-cleanup — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-fix-batch-1 | Cosmetic + dead-code: delete `Pipeline._UNFINISHED` sentinel (never assigned at runtime per P1-08 review); fix `auth.py` docstring referencing old `middleware_timings` (now `pipeline_trace`); freeze `Manifest` dataclass (`@dataclass(frozen=True)`) per P4-06 review. | `READY` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 02-fix-host-protocol-version | Unify `_HOST_PROTOCOL_VERSION = "1.0.0"` (currently duplicated in `mcp_server/server.py` and `transports/http/server.py`) into a single module — likely `core/version.py` or extending an existing constants module. Publish `host_protocol_version_range` per `06-versioning.md §3.3`. | `READY` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 03-fix-register-middleware-singleton | `register_middleware` module-level singleton has no reset path — second `create_app` call in same process raises `ValueError` → `PluginManifestInvalid` (P4-06 medium finding). Add a reset hook OR refactor to a per-app instance. Tests currently monkeypatch around it; production guard needed. | `READY` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 04-fix-typed-group-membership-error | Replace the `ValueError` raise in `MemoryStore.group_invite` (and other `MemoryStore.group_*` paths) with a typed `GroupMembershipError` that `StoreDispatchMiddleware` catches and converts to a `ShortCircuitResponse` with `error_code: "group_membership_error"`. Per P1-08 review: the route-level 403 re-map was unreachable because the underlying error type was generic. Symptom resolved by P5-03 field canonicalization but design issue remains. | `READY` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 05-fix-double-store-dispatch | When plugins load via HTTP bootstrap, two `StoreDispatchMiddleware` instances exist (one in default chain, one as terminal). Per P4-06 review: structurally correct but confusing. Refactor so the terminal IS the chain entry, or drop one. | `READY` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 06-relax-PluginNotFound-in-dev | `PluginNotFound` is raised in dev mode when an allowlisted ID has no matching entry-point. Per P4-06: spec §6.1 only mandates this for production. Dev mode should warn + skip. | `READY` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 07-review | Cumulative code review. Confirm no regression. | `BLOCKED` | code-reviewer | 0 | 2026-05-04T00:00:00Z |

## Currently next action

Dispatch **phase 01-fix-batch-1** (the cheapest items) — likely a 1-shot python-pro can do all 3 cosmetic items in <100 lines of changes. Phases 02–06 are independent of each other and of phase 01; can run sequentially or batched depending on agent budget.

## Termination targets

- [ ] All 7 phases DONE
- [ ] `Pipeline._UNFINISHED` removed
- [ ] `auth.py` docstring corrected (refers to `pipeline_trace`, not `middleware_timings`)
- [ ] `Manifest` is `@dataclass(frozen=True)`
- [ ] `_HOST_PROTOCOL_VERSION` sourced from a single module; both bootstraps import it
- [ ] `host_protocol_version_range` published per `06-versioning.md §3.3`
- [ ] `register_middleware` singleton has explicit reset path; double-`create_app` no longer fails
- [ ] `MemoryStore.group_*` raises typed `GroupMembershipError`; `StoreDispatchMiddleware` catches it; route-level 403 mapping reachable
- [ ] Single `StoreDispatchMiddleware` instance per HTTP bootstrap (no double-registration)
- [ ] Dev-mode `PluginNotFound` for unmatched allowlisted IDs becomes a warning, not a raise
- [ ] All conformance + pytest invariants preserved

## Reference

- P1-08 REVIEW.md: `Pipeline._UNFINISHED` dead code, `auth.py` docstring, `MemoryStore.group_invite ValueError` design
- P4-06 REVIEW.md: 5 medium + low findings (Manifest frozen, `_HOST_PROTOCOL_VERSION` duplication, `register_middleware` reset, `PluginNotFound` strictness, double `StoreDispatchMiddleware`)
- P5-04 REVIEW.md: `_HOST_PROTOCOL_VERSION` unification reiterated
