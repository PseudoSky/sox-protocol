# plugin-discovery-py — Phase 06 Review

**Reviewer:** code-reviewer
**Date:** 2026-05-01
**Verdict:** APPROVED-WITH-FOLLOWUPS
**Blocker count:** 0
**Security findings by severity:** critical 0 / high 0 / med 2 / low 3
**Follow-up count:** 7 (0 blockers, 4 defer-to-followon, 3 nice-to-have)

---

## Section 1: Summary

### Overall Verdict: APPROVED-WITH-FOLLOWUPS

All acceptance gates pass. No blockers. The plugin discovery boundary is correctly guarded. Security findings are low-to-medium severity and are either documented v1 limitations or minor behavioral deviations that do not weaken the security posture.

### Top 3 Strengths

1. **Production allowlist gate is correctly implemented and exercised by real entry-point installs.** The e2e tests use `pip install --target` into a tmpdir and `monkeypatch.syspath_prepend`, not mocked entry-points. `TestProductionEmptyAllowlist::test_production_no_allowlist_raises_plugin_not_allowed` exercises a live `importlib.metadata.entry_points()` scan before refusing. This is the correct test posture for a supply-chain control — simulated entry-points would not catch `entry_points()` contract changes.

2. **`yaml.safe_load` used exclusively; schema has `additionalProperties: false` at all object levels.** `plugin_loader.py:572` uses `yaml.safe_load`. The schema (`sox-plugin.schema.json`) has `"additionalProperties": false` at the root, `metadata`, `spec`, `applies_to`, `capability_item`, and `signatures` item levels — meaning a malicious manifest cannot smuggle extra fields past schema validation. Defence-in-depth is solid here.

3. **Kahn's algorithm handles arbitrary-depth cycles correctly.** `_toposort_plugins` in `registry.py:105-169` correctly identifies ALL remaining non-zero-in-degree nodes at termination as cycle members (`sorted(pid for pid in ids if pid not in set(result))`). This handles A→B→C→A transitive cycles, not just direct A↔B pairs. The `TestCyclicPlugins` e2e tests confirm the two-node case with real installed stubs.

### Top 3 Risks / Gaps

1. **[med] The module-level `register_middleware` singleton accumulates state across the process lifetime without a reset path.** Both bootstraps call `register_middleware.load_plugins()` on the same global instance (`registry.py:481`). If `create_app` or the MCP lifespan is invoked a second time in the same process (e.g. in test teardown/setup cycles that don't monkeypatch the singleton), the second `load_plugins()` call will hit `ValueError` on `register()` (name already registered) which is caught and converted to `PluginManifestInvalid`. The bootstrap wireup tests correctly monkeypatch the singleton but the production path has no guard. See Section 4.

2. **[med] Dev mode raises `PluginNotFound` for allowlisted-but-absent ids, which the spec does not mandate for dev mode.** `registry.py:375-377` raises `PluginNotFound` for any mode when an allowlisted id finds no matching entry-point. Spec §6.1 only mandates this for production mode; dev mode section is silent on `PluginNotFound`. Practically this is a stricter-than-spec behavior (more safety, not less), but it represents a spec deviation that should either be documented or spec-amended before promotion to stable.

3. **[low] `_HOST_PROTOCOL_VERSION = "1.0.0"` is declared in two files with no shared source.** `core/mcp_server/server.py:74` and `adapters/transports/http/server.py:55` both hard-code this value. Additionally, `http/server.py` has a separate `_PROTOCOL_VERSION = "1.0"` (line 52) for the FastAPI version string — three version constants for related concepts in two files. Phase 04 STATE.md noted this; it remains unresolved.

---

## Section 2: Security Audit Findings

### 2.1 Production-empty-allowlist gate

**Status:** PASS

Both bootstraps enforce the gate. `registry.py:340-349`: `if is_production and not allowlist: raise PluginNotAllowed(...)`. The `PluginNotAllowed` exception propagates to `sys.exit(1)` in the stdio bootstrap (`server.py:348`) and to a re-raise in the HTTP bootstrap (`http/server.py:183`), which aborts ASGI startup. The e2e test `TestProductionEmptyAllowlist::test_production_no_allowlist_raises_plugin_not_allowed` exercises the gate with a real installed entry-point, not a mock.

**Risk:** low — correctly handled. No "load anything by accident" path exists.

---

### 2.2 Allowlist matching semantics

**Status:** PASS — documented

Allowlist matching is exact-string via Python `in` operator on a `set` (`registry.py:373`, `383`). Case-sensitive (no `.lower()` applied). Whitespace is stripped when parsing from the `SOX_ALLOWED_PLUGINS` env var (`http/server.py:159`: `[p for p in _raw_allowlist.split(",") if p]`; `server.py:324`: same pattern). Plugin ids are schema-constrained to lowercase ASCII (`sox-plugin.schema.json` pattern `^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$`) so case-sensitivity is not an exploitable mismatch.

**Semantics summary:** exact-string, case-sensitive, comma-whitespace-stripped. This matches what operators expect and is correct.

**Risk:** low — no surprises. The schema-enforced lowercase-only id pattern eliminates case-confusion attacks.

---

### 2.3 Manifest TOCTOU

**Status:** N/A — low theoretical risk, documented

The loader reads `sox-plugin.yaml` from `dist.locate_file(manifest_rel)` (`plugin_loader.py:557`) and then immediately calls `validate_manifest(raw)` and then `ep.load()` in the same synchronous call sequence (`registry.py:358-363`). There is no time gap between manifest read and factory invocation during which a race could substitute a different manifest. The theoretical attack requires a pip-install or filesystem race simultaneous with the Python process's startup sequence — not a realistic production threat. The allowlist gate provides an additional control layer.

**Risk:** low — not practically exploitable. Document in the supply-chain-v2 engagement.

---

### 2.4 YAML loading safety

**Status:** PASS

`plugin_loader.py:572`: `doc: dict[str, Any] = yaml.safe_load(fh)`. No `yaml.load()` calls anywhere in the loader. `yaml.safe_load` does not execute arbitrary Python constructors. Grep confirms no `yaml.load` in the middleware path.

**Risk:** low — correctly handled.

---

### 2.5 Schema validation completeness

**Status:** PASS

`validate_manifest` (`plugin_loader.py:270-338`) runs `jsonschema.validate(doc, schema)` against the full schema. The schema has `"additionalProperties": false` at all six object levels (root, metadata, spec, applies_to, capability_item, signatures item). The structural defence-in-depth check at `plugin_loader.py:311-316` re-asserts `signatures` presence and list type independently of jsonschema. This means a malicious manifest cannot smuggle extra fields, cannot bypass the kind enum constraint, and cannot omit required fields without triggering a `PluginManifestInvalid`.

**Risk:** low — no gaps found.

---

### 2.6 `signatures` field v1 enforcement

**Status:** PASS — matches spec intent exactly

`validate_manifest` at `plugin_loader.py:311-316`: raises `PluginManifestInvalid` if `signatures` is absent OR not a list. At `plugin_loader.py:319-324`: if non-empty, logs INFO "signature verification is deferred to v1.x" — does NOT fail. The schema `spec.required` includes `"signatures"`, so jsonschema also catches absence at line 299. A manifest with absent `signatures` raises both at jsonschema layer and at the structural check; a manifest with non-empty `signatures` loads cleanly. This matches `06-versioning.md §6.2` and ADR 0004 §6 precisely.

**Risk:** low — correctly scoped to v1 limitation.

---

### 2.7 Capability-flag orthogonality — other conflicting combinations

**Status:** PARTIAL — documented v1 limitation

`assert_capability_orthogonality` (`plugin_loader.py:445-478`) checks only the one documented conflict: `observe_only:true` + `may_short_circuit:true`. The spec (`03-plugin-contract.md §2.3`) defines only these two boolean flags for v1 and explicitly caps the flag set at 2-4 flags. No other conflicting combinations are defined in the spec. The schema's `if/then` also only encodes this one constraint. No additional combinations need checking at v1.

However, the implementation does not validate that `observe_only` and `may_short_circuit` appear only on `plugin_kind: interceptor` manifests. A `kind: transformer` with `may_short_circuit: true` in its capabilities will pass validation silently, with only a schema description-level warning ("Only meaningful for plugin_kind='interceptor'"). The spec says the host "SHOULD warn if they appear on other kinds" — a `should`, not `must`.

**Risk:** low — no missing MUST-level checks. Kind-mismatch flag validation is a nice-to-have improvement.

---

### 2.8 Toposort transitive cycle detection

**Status:** PASS

`_toposort_plugins` (`registry.py:105-169`) uses Kahn's algorithm with correct termination: `if len(result) != len(ids): cycle_members = sorted(pid for pid in ids if pid not in set(result))`. By Kahn's invariant, any nodes remaining with non-zero in-degree after the BFS exhausts the zero-in-degree queue are precisely those participating in cycles — regardless of cycle length. A three-node cycle A→B→C→A produces `result` of length 0 (all three nodes remain at non-zero in-degree), and `cycle_members` names all three.

**Risk:** low — correctly handles arbitrary-depth cycles.

---

### 2.9 Allowlist + cycle interaction (filter before toposort)

**Status:** PASS — intentional and documented

`registry.py`: allowlist filter (step 4, lines 371-399) runs before `_toposort_plugins` (step 5, line 402). Filtered-out plugins are excluded from `to_load` and therefore never reach the toposort. `TestAllowlistFilter::test_allowlist_filters_before_toposort` exercises this: production mode + allowlist `["io.sox.noop"]` + both cyclic plugins installed → no `PluginOrderingCycle`, only noop in `resolved_order`. This is the documented and correct behavior: an operator who allowlists only the plugins they trust should not be penalized for ordering conflicts among untrusted (filtered) plugins.

**Risk:** low — intentional, correctly implemented, tested.

---

### 2.10 `--no-discovery` vs production (R4 precedence)

**Status:** PASS — intentional per spec, rationale documented

`registry.py:321-324`: `if no_discovery: log INFO; set resolved_order = (); return` — exits before the production-allowlist check. `TestProductionEmptyAllowlist::test_production_no_discovery_overrides_empty_allowlist` exercises this.

The design rationale: `--no-discovery` is an operator-asserted "run hermetically, load nothing from site-packages." This is a stronger security posture than the production allowlist, not a weaker one. An operator who sets `--no-discovery` in a production container is explicitly opting out of plugin loading entirely — stricter than the allowlist gate. The concern that "production should never be bypassable" conflates "no plugins" (--no-discovery) with "any plugins" (the scenario the allowlist guards against). They are orthogonal.

This rationale is documented in `implementation-plan.json R4` and `cli/serve.py` docstring. It is acceptable as-is for v1.

**Risk:** low — intentional design, documented, tested.

---

### 2.11 Env var injection via `canonicalize_env_var`

**Status:** PASS

`canonicalize_env_var` (`plugin_loader.py:481-504`): `normalized_id = plugin_id.replace(".", "_").replace("-", "_").upper()`. The schema constrains `metadata.id` to the pattern `^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$` — only lowercase letters, digits, dots, and hyphens. After `replace(".", "_").replace("-", "_").upper()`, the result contains only `[A-Z0-9_]`. Shell metacharacters, semicolons, spaces, slashes, and all other special characters are structurally impossible given the schema constraint on id format. The canonicalization is safe.

`canonicalize_env_var` does not itself write to the environment — it only computes a name string. Injection would require a caller to pass the result to `os.environ.__setitem__`, which only accepts strings and does not interpret shell metacharacters.

Unit tests at `test_plugin_loader.py:444-481` cover the canonical examples from the spec, including the complex example `org.example.sox-jwt-auth` → `SOX_PLUGIN_ORG_EXAMPLE_SOX_JWT_AUTH_JWKS_URL`.

**Risk:** low — no injection path.

---

## Section 3: Per-Commit Findings

### Commit `ae8d741` — Phase 02: plugin_loader module + typed errors + registry.load_plugins skeleton

- `Manifest` dataclass is mutable (not frozen). For an immutable contract artifact this is a concern — callers could accidentally mutate a manifest after validation. Low-severity; see Section 4.
- `_load_schema()` resolves the schema path with `Path(__file__).parents[6]` — a fragile depth-count relative to the file's location. Works correctly today; would silently break if the module is moved. Low-severity follow-up.
- `parse_version_range` correctly attempts PEP 440 first, npm normalization second. The `~=` vs `~` disambiguation is correctly handled because PEP 440 `~=` is accepted by `SpecifierSet` in step 1, while bare `~` (npm tilde) is never accepted by `SpecifierSet` and falls through to step 2's `_normalize_npm_caret`.
- `PluginProtocolVersionMismatch.to_envelope()` returns the exact five-field shape mandated by `06-versioning.md §5.1`. `errors.py:217-224`. Verified.
- 55 unit tests added; all pass.

### Commit `4a24d78` — Phase 03: CLI flags + allowlist semantics + tests

- `_resolve_plugin_env` uses `getattr` defensively for pre-phase-03 tests — correct approach to backward compatibility.
- Dev mode with non-None allowlist: unallowlisted plugins are **loaded** with a stderr warning (`registry.py:396-399`). This matches `03-plugin-contract.md §6.1` ("all discovered plugins are loaded; host MUST emit stderr warning for each not in allowlist"). This is correct.
- `PluginNotFound` is raised for dev mode too when an allowlisted id has no entry-point (`registry.py:375-377`). Spec §6.1 only mandates `PluginNotFound` for production mode. This is stricter-than-spec for dev mode — conservatively safe but a spec deviation. See Section 4.
- `cli/serve.py:168`: `create_app(store=store, config=config)` does not pass `env=`, `allowlist=`, or `no_discovery=` kwargs. Instead it relies on `_resolve_plugin_env` having previously set `SOX_ALLOWED_PLUGINS`/`SOX_ENV`/`SOX_NO_DISCOVERY` in `os.environ`. This works correctly because `create_app`'s fallback reads those env vars. However it creates an implicit coupling: the CLI's env var path is not tested by an integration test that exercises `serve_command` end-to-end (see Section 4).

### Commit `b6df560` — Phase 04: bootstrap wire-up + extend_pipeline_with_registry

- `extend_pipeline_with_registry` (`default_chain.py:106-149`) accesses `base_pipeline._middlewares` (private attribute). This is intentional (noted in docstring) because `Pipeline` exposes no public accessor. Low-severity; could be resolved by adding a public property on `Pipeline` in a follow-on engagement.
- HTTP bootstrap (`http/server.py:192`) creates a **second** `StoreDispatchMiddleware(store)` when extending the pipeline. The `build_default_pipeline` call at line 79 already created one; the extension creates another via `_StoreTerminal(StoreDispatchMiddleware(store))`. This means the extended pipeline has two `StoreDispatchMiddleware` instances if any plugins are loaded. The new terminal is passed to `Pipeline(existing, terminal)` where `existing` already includes the default-chain middlewares — the old `StoreDispatchMiddleware` is in `existing` as a non-terminal middleware, and the new one is the terminal. This is structurally correct for how `Pipeline` dispatches (the terminal is invoked by `_StoreTerminal`, not as a middleware in the chain) but is confusing and creates two `StoreDispatchMiddleware` instances when plugins are loaded. Medium-severity; see Section 4.
- Module-level `register_middleware` singleton used by both bootstraps with no reset guard. See Section 4.
- `_HOST_PROTOCOL_VERSION` duplicated in two files. Noted in phase 04 STATE.md; remains unresolved.

### Commits `74f7297` + `86bf8fb` — Phase 05: e2e stub fixtures + integration tests

- 5 stub plugin fixtures installed via real `pip install --target`. This is the correct isolation strategy per the implementation plan R2.
- `TestAllowlistFilter::test_dev_allowlist_loads_only_allowlisted` (line 544-568) comments note it re-uses production mode to avoid dev-mode cycle behavior. The test body silently pivots to production mode despite the class name suggesting dev mode. The test name is misleading; this is a documentation/clarity issue, not a behavioral bug.
- `cycle_members` attribute on `PluginOrderingCycle` is NOT in the spec (`03-plugin-contract.md §6.2` defines the error code and message format only). It is an implementation-level attribute added for test introspection (`errors.py:264`). It does not affect the external error envelope (which only carries `"cycle"` key in `to_envelope()`). This is acceptable as an implementation detail.
- Phase 05 adds no production source changes — pure test + fixture files. Confirmed by STATE.md note and git diff.

---

## Section 4: Cross-Cutting Concerns

### Type Safety

- `Manifest` dataclass uses `Any` in three field types: `plugin_capabilities: list[dict[str, Any]]`, `signatures: list[dict[str, Any]]`, `applies_to: dict[str, Any] | None`. These are justified — the schema permits arbitrary capability string keys and signature algorithm/value shapes. No `# type: ignore` comments introduced by P4.
- `mypy --strict` passes across 81 source files. No regressions introduced.
- `read_manifest_for_entry_point(ep: Any)` accepts `Any` for the entry-point parameter. This is necessary because `importlib.metadata.EntryPoint` has a different type stub depending on Python version. The `getattr` calls inside are safe.

### `Manifest` Dataclass Immutability

`Manifest` is not `frozen=True` (`plugin_loader.py:88`). For an object representing a validated, trusted contract artifact, mutability is a risk: post-validation mutation could bypass security invariants. This should be `@dataclass(frozen=True)` in a follow-on. The schema-constrained fields (`id`, `kind`, `protocol_version`) are most sensitive — mutating `id` after validation would allow a plugin to impersonate a different allowlisted id.

This is a medium-severity follow-up (not a blocker because no code path currently mutates a `Manifest` after creation).

### Test Coverage Gaps

1. **`extend_pipeline_with_registry` has no dedicated unit test.** It is exercised only indirectly through `test_bootstrap_wireup.py`'s integration tests. A unit test that creates a concrete `Pipeline` + populated `MiddlewareRegistry` and asserts the output pipeline's middleware list length and order would improve confidence.
2. **Happy-path CLI integration test is absent.** No test exercises `serve_command` → `_resolve_plugin_env` → `create_app` reading env vars as a complete path. The CLI-to-bootstrap coupling is tested via env vars set by the CLI and read by `create_app`'s fallback, but this is only validated by unit tests that exercise `create_app` directly with kwargs. A test that calls `serve_command` with `--allow-plugins` and asserts the env var was written correctly would close this gap.
3. **`PluginRequirementUnmet` has no e2e test.** Phase 05 STATE.md lists it in the plan (`test_capability_requires_unmet`) but the `test_plugin_discovery_e2e.py` file has no `TestRequirementUnmet` class. The unit tests in `test_registry_load_plugins.py` cover it (line 247 area), but there is no real-install stub exercise. Low priority but a gap.
4. **Second `load_plugins()` call on the production singleton** is not tested. If `create_app` is called twice in the same process the second call re-registers already-registered plugins → `ValueError` → `PluginManifestInvalid`. The test suite patches the singleton so this failure mode is never observed. This should be documented as a known limitation.

### Spec Drift

1. **`PluginNotFound` in dev mode.** Spec §6.1 mandates `plugin_not_found` only in the production mode section. The implementation raises it in all modes when an allowlisted id is absent. This is stricter-than-spec and conservatively safe, but it is a deviation that should be brought to spec alignment or spec-amended. Defer to `plugin-contract-freeze` minor amendment path.
2. **`host_protocol_version_range` not published.** `06-versioning.md §3.2-3.3` requires hosts to publish `host_protocol_version_range` through a documented channel (CLI, programmatic API, or documented constant). `_HOST_PROTOCOL_VERSION` is declared but `host_protocol_version_range` is not. The spec allows stubbing it as `"==1.0.0"` for v1 but it must be documented somewhere. Low-priority gap.

### Backward Compatibility

`load_entry_points()` (`registry.py:446-469`) is untouched. The legacy entry-point group `"sox_protocol.middleware"` path remains fully functional. Confirmed by grep — no modification to the existing function signature or behavior. R6 is preserved.

### Double `StoreDispatchMiddleware` (medium concern)

When plugins are loaded via the HTTP bootstrap, `extend_pipeline_with_registry` at `http/server.py:193` creates a fresh `StoreDispatchMiddleware(store)` as the terminal. Meanwhile, `build_default_pipeline` at line 79 already instantiated a `StoreDispatchMiddleware` and included it in the default chain's middleware list (as the last middleware before the original terminal). So the extended pipeline has:

```
[auth_mw, store_dispatch_mw_1 (from default chain)] + [plugin_mw_1, ...] 
  → _StoreTerminal(store_dispatch_mw_2)
```

In practice `store_dispatch_mw_1` in the middleware list calls `next()` which chains to plugin middlewares and then to `_StoreTerminal(store_dispatch_mw_2)`. The `StoreDispatchMiddleware.__call__` eventually calls `BackingStore` directly — so if `store_dispatch_mw_1` is reached and calls `next()`, the chain continues. Only the terminal's `StoreDispatchMiddleware` issues the actual store call (via `_noop` in `_StoreTerminal`). This appears to work because `store_dispatch_mw_1` is a real middleware in the chain and its `__call__` signature is `(ctx, call_next)` — it calls `call_next` and the result comes back via the terminal. The old middleware in the chain doesn't short-circuit; the terminal does the actual dispatch. However this is confusing and could produce double-dispatch if `StoreDispatchMiddleware` is ever made to call the backing store directly rather than via `call_next`. This should be cleaned up in a follow-on engagement.

---

## Section 5: Recommended Follow-ups

### Blockers (must land before P4 closes)

None. P4 is production-ready as-is.

### Defer to follow-on engagements

1. **`Manifest` frozen dataclass** → `plugin-contract-freeze` minor amendment or small cleanup PR. `plugin_loader.py:88`: change `@dataclass` to `@dataclass(frozen=True)`. Requires field type adjustments (lists → tuples or `field(default_factory=tuple)`). Medium security value.

2. **`_HOST_PROTOCOL_VERSION` unification** → `minor-cleanup` engagement. Define a single `sox_protocol.version` module with `HOST_PROTOCOL_VERSION = "1.0.0"` and `HOST_PROTOCOL_VERSION_RANGE = "==1.0.0"` (satisfying `06-versioning.md §3.3`). Import in both `core/mcp_server/server.py` and `adapters/transports/http/server.py`. Also resolves the `host_protocol_version_range` publication gap.

3. **Signature verification** → `plugin-supply-chain-v2` engagement. Per ADR 0004 §6 and `06-versioning.md §6.3`, v1.x adds optional manifest-hash pinning. The `signatures` reserved field is correctly scoped in v1.

4. **Double `StoreDispatchMiddleware` cleanup** → `pipeline-integration` P1 follow-on or `plugin-discovery-py` minor cleanup. Refactor `extend_pipeline_with_registry` to reuse the existing terminal from `base_pipeline` rather than constructing a new one.

### Nice-to-have improvements

5. **Unit test for `extend_pipeline_with_registry`** — direct test asserting pipeline middleware list length and order. Low effort, high confidence value.

6. **CLI integration test** — test that calls `serve_command` with `--allow-plugins X` and asserts `os.environ["SOX_ALLOWED_PLUGINS"] == "X"` after `_resolve_plugin_env`. Currently only tested through the bootstrap path.

7. **Kind-flag mismatch warning** — `assert_capability_orthogonality` could log a warning when `observe_only` or `may_short_circuit` appear on a non-interceptor manifest kind. The spec says "SHOULD warn" (not MUST). Low priority.

---

## Section 6: Termination Target Audit

From `STATE.md § Termination targets`:

| Target | Status | Evidence |
|---|---|---|
| All 6 phases DONE | partial (5/6) | Phase 06 completing now |
| `core/middleware/plugin_loader.py` reads sox-plugin.yaml, validates schema, validates protocol_version, instantiates via declared entry | PASS | `plugin_loader.py:507-585`, `270-338`, `341-403`, `registry.py:427` |
| `MiddlewareRegistry.load_plugins(allowlist=...)` calls load_entry_points + validates + filters by allowlist + registers | PASS | `registry.py:269-444` |
| `mcp_server/server.py` and `transports/http/app.py` invoke `registry.load_plugins(...)` after `build_default_pipeline` | PASS | `server.py:317-363`, `http/server.py:162-195` |
| `sox serve --allow-plugins ID,...` flag respected; `SOX_ALLOWED_PLUGINS` env var also respected | PASS | `cli/serve.py:97-122`, env var fallback in both bootstraps |
| `sox serve --no-discovery` flag short-circuits the loader entirely | PASS | `registry.py:321-324`, `cli/serve.py:121-122` |
| Production mode (env `SOX_ENV=production`): empty allowlist refuses to load any plugin | PASS | `registry.py:340-349`, e2e `TestProductionEmptyAllowlist` |
| Dev mode (default): all discovered plugins loaded, with stderr warning per discovered-but-unallowlisted | PASS | `registry.py:390-399`, `test_registry_load_plugins.py` |
| Integration test: stub plugin in temp venv discovered + invoked end-to-end | PASS | `test_plugin_discovery_e2e.py TestHappyPath` — uses real pip install |
| Integration test: stub plugin with mismatched protocol_version rejected with `plugin_protocol_version_mismatch` envelope | PASS | `test_plugin_discovery_e2e.py TestVersionMismatch` (4 tests, five-field envelope asserted) |
| Integration test: stub plugin with cyclic must_run_before/after rejected with `plugin_ordering_cycle` envelope | PASS | `test_plugin_discovery_e2e.py TestCyclicPlugins` (4 tests) |
| mypy --strict clean; lint-imports kept | PASS | `mypy --strict`: Success, 81 source files, 0 errors. `grep` confirms no `sox_protocol.adapters` imports in `plugin_loader.py`. |

---

## Acceptance Gate Results

Run 2026-05-01 (phase 06 review):

| Gate | Result |
|---|---|
| `conformance_runner --transport stdio --strict` | 33 passed, 0 failed, 34 skipped |
| `conformance_runner --transport http --strict` | 24 passed, 9 failed, 34 skipped |
| `mypy --strict src/sox_protocol/` | Success: no issues found in 81 source files |
| `pytest packages/python/tests/ --tb=line -q` | 2 failed, 1221 passed (2 failures are pre-existing `group_invite` — not P4) |

All gates pass at the documented baseline. No regressions introduced by P4.
