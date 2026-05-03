---
slug: reference-plugins
target: One reference plugin shipped outside core/ to prove the contract — sox-plugin-schema-strict (kind: transformer). Migrates `routes._validate_body` duplication out of core. Demonstrates manifest-driven discovery + transformer kind end-to-end. Audit-jsonl and rate-limit-redis deferred to reference-plugins-extended (post-v1).
created: 2026-05-01
last_event: 2026-05-04T00:00:00Z
orchestrator_protocol: v1
parent_plan: plugin-architecture
prereqs: [plugin-contract-freeze, plugin-discovery-py]
narrowed_from: 3 plugins → 1 (per analysis §7.6 / optimizer suggestion #2)
---

# reference-plugins — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Plan one plugin: API surface, manifest, lifecycle, tests, package layout | `DONE` | python-pro (combined) | 1 | 2026-05-04T00:00:00Z |
| 02-build-schema-strict | `plugins/sox-plugin-schema-strict/` — kind: transformer; pyproject.toml; sox-plugin.yaml; src/; tests/; integration with sox-plugin spec from B1 | `DONE` | python-pro | 1 | 2026-05-04T00:00:00Z |
| 03-migrate-routes | Delete `routes.py:_validate_body` (and the 22 inline validation calls); replace with the plugin in the chain | `READY` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 04-review | Review for contract conformance — does the plugin demonstrate the manifest-driven discovery path end-to-end without core/ modifications? | `BLOCKED` | code-reviewer | 0 | 2026-05-01T15:00:00Z |

## Currently next action

Dispatch **phase 03-migrate-routes**: replace `routes._validate_body` and its
22 inline call-sites in `packages/python/src/sox_protocol/adapters/transports/http/routes.py`
with the schema-strict plugin via the production discovery mechanism. Verify
HTTP conformance still passes (≥ 24 passed) after the swap. The plugin is
already proven end-to-end in tests (29 unit + 7 e2e); phase 03 swaps the
production code to depend on it instead of the inline validator.

## Transition log

### 2026-05-04 — phase 01-plan + 02-build-schema-strict: combined DONE

**Agent:** python-pro (combined dispatch; planner overhead skipped per orchestrator
judgment — plan was well-spec'd in engagement target)

**Plan summary (phase 01):**
- Single plugin `io.sox.schema-strict` (kind: `transformer`) shipped at repo root
  `plugins/sox-plugin-schema-strict/` — outside `packages/python/` to prove the
  plugin is genuinely external to core.
- `must_run_before: (store_dispatch,)` — runs early in the chain, before
  store_dispatch. No `must_run_after` constraint.
- Schemas loaded lazily per-operation from a `schemas_dir` resolved by:
  explicit `__init__` arg → `SOX_PLUGIN_SCHEMA_STRICT_SCHEMAS_DIR` env var
  → CWD search for `spec/schemas/tools/`. Cache compiled validators per op.
- Validation failure → `ShortCircuitResponse(envelope)` with
  `error_code="validation_error"`, matching the existing `routes._validate_body`
  envelope shape so phase 03 can delete the inline validator without changing
  client-visible payloads.
- Test strategy: 29 unit tests against the middleware in isolation +
  7 e2e tests installing the plugin into a tmpdir via `pip install --target`
  + sys.path manipulation (mirroring P4 phase 05's isolation pattern).

**Files landed:**

- `plugins/sox-plugin-schema-strict/pyproject.toml` (NEW) — setuptools build,
  `[project.entry-points."sox_protocol.plugins"]` declares `io.sox.schema-strict`
  → `sox_plugin_schema_strict:factory`. Package data includes `sox-plugin.yaml`.
- `plugins/sox-plugin-schema-strict/src/sox_plugin_schema_strict/sox-plugin.yaml`
  (NEW) — manifest with `protocol_version: ">=1.0,<2.0"`, `kind: transformer`,
  `signatures: []` per ADR 0004 §6 (v1 limitation).
- `plugins/sox-plugin-schema-strict/src/sox_plugin_schema_strict/__init__.py` (NEW)
  — exports `factory()` and `SchemaStrictMiddleware`.
- `plugins/sox-plugin-schema-strict/src/sox_plugin_schema_strict/middleware.py` (NEW)
  — 318 lines; `SchemaStrictMiddleware` class with `kind`, `name`,
  `must_run_before` ClassVars; `_resolve_schemas_dir`, `_get_validator`,
  `_build_violations`, `_make_validation_error_envelope` helpers.
- `plugins/sox-plugin-schema-strict/tests/test_schema_strict.py` (NEW) — 29 unit
  tests (29 pass).
- `plugins/sox-plugin-schema-strict/.gitignore` — excludes `build/`,
  `*.egg-info/`, `__pycache__/`.
- `packages/python/tests/integration/test_schema_strict_e2e.py` (NEW) — 7 e2e
  tests using `pip install --target <tmpdir>` + `monkeypatch.syspath_prepend`
  + `_activate()` helper that evicts cached imports + `asyncio.run()` for
  per-test event-loop isolation.

**Inline fixes applied during this session (4):**

1. `__init__.py` imported `ValidationError` from `middleware.py` that did not
   exist (agent intended to define it but used `ShortCircuitResponse` directly).
   Removed dead import.
2. Test fixtures used `{"channel": ..., "text": ...}` for send but spec requires
   `{"channel": ..., "body": <object>}`. Fixed 4 send fixtures + 1 e2e fixture
   to use the real schema shape.
3. Test fixtures used `{"channel": ...}` for recv but recv schema accepts only
   `channels` (plural array) and rejects `additionalProperties`. Fixed 1 valid
   recv + 3 invalid recv fixtures (switched to `{"max_messages": 0}` which
   violates `minimum:1`).
4. Wrong import path `sox_protocol.core.middleware.store_dispatch` →
   `sox_protocol.core.middleware.plugins.store_dispatch`. Fixed.
5. `build_default_pipeline()` requires `verifier` kwarg; e2e test was passing
   only `store=`. Added `IdentityVerifier(registry=InMemoryCredentialRegistry(),
   audit=AuditLogWriter())` construction.
6. `sox-plugin.yaml` was at package root, outside the python package dir, so
   it wasn't bundled in the install distribution. Moved inside
   `src/sox_plugin_schema_strict/` so `read_manifest_for_entry_point` finds it
   via `distribution.files`.
7. Test pollution from `enforcer/` tests caused 4 e2e tests to fail in full
   suite but pass in isolation — `asyncio.get_event_loop()` is deprecated in
   Python 3.13+ and doesn't auto-create a new loop after another test closed
   it. Replaced 4 `asyncio.get_event_loop().run_until_complete(...)` calls
   with `asyncio.run(...)` for per-call event-loop isolation.

**Acceptance gates at commit:**
- `mypy --strict`: Success, 81 source files (no source code in core changed)
- `pytest`: 1228 passed, 2 failed (pre-existing group_invite — unchanged)
- stdio conformance: 33 passed, 0 failed, 34 skipped (no regression)
- HTTP conformance: 24 passed, 9 failed, 34 skipped (no regression — plugin
  not yet wired into production)

**Notes:**
- Phase 02 does NOT modify production code under `packages/python/src/sox_protocol/`.
  The plugin is built and proven via tests; phase 03 will swap routes.py to
  depend on it.
- Schemas dir is loaded from `spec/schemas/tools/` (CWD search fallback). The
  middleware does not bundle copies — keeps the schemas as a single source of
  truth in the spec tree.

## Termination targets

- [ ] All 4 phases DONE
- [x] `plugins/sox-plugin-schema-strict/` exists as standalone package — own pyproject.toml, sox-plugin.yaml manifest, src/, tests/
- [ ] 100% line coverage on the plugin
- [x] mypy --strict clean
- [x] Plugin loads via plugin-discovery mechanism (not just programmatic registration in tests)
- [ ] `routes.py:_validate_body` deleted; the 22 inline validation call sites removed
- [ ] schema validation now runs as the `transformer` kind in the chain on both transports
- [ ] Conformance suite still 32/0/27 against both transports with the plugin enabled
- [x] **Demonstrates that contract works end-to-end with zero `core/` modifications** (proven in phase 02 via 7 e2e tests; phase 03 will swap the production code to depend on the plugin)

## Why one plugin, not three

Optimizer suggestion #2 + §7.6: schema-strict migrates *real existing code*
(measurable LOC reduction in `routes.py`), exercises only the
least-controversial kind (transformer), and does not depend on the
`Provider` contract — which §7.5 risk #2/#6 reveals still needs failure-mode
specification. Three plugins built simultaneously against an unfrozen
contract risks three divergent interpretations and costly re-alignment.
One canonical migration is sufficient contract proof; breadth comes after
the contract has been pressure-tested.

## Out-of-scope — handled by sibling engagement

- `sox-plugin-audit-jsonl` (kind: interceptor) → `reference-plugins-extended` (post-v1)
- `sox-plugin-rate-limit-redis` (kind: interceptor + requires provider) → `reference-plugins-extended` (post-v1, after Provider failure semantics finalized)

## Reference

See parent analysis at [`../plugin-architecture/analysis.md`](../plugin-architecture/analysis.md) §7.6 for the narrowing rationale.
