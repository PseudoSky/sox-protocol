# hooks-middleware 03-implement review

Reviewer: code-reviewer (independent)
Date: 2026-05-01
Scope: `packages/python/src/sox_protocol/core/middleware/`, `packages/python/src/sox_protocol/core/identity/middleware.py`, post-salvage state per commit `64e4535`.

## Verdict
PASS-WITH-NOTES

The framework satisfies the normative behaviours of `spec/ports/middleware.md` (inspect / mutate / short-circuit; reentrancy; internal-error conversion; default-chain order; declarative out-of-tree registration). Identity invariants are preserved: unverified callers on enforced operations are rejected before any backing-store call is reachable, and the identity adapter is isolated from `core/adapters`. The salvage claims (15 ops in `Operation`, full `StoreDispatchMiddleware` op-table, default-chain order, no `# pragma` directives in `core/middleware/`) check out on inspection of the source files. Findings below are correctness, ergonomics, and test-coverage gaps — none are spec-violating blockers.

## Findings

- **warning** | `core/middleware/default_chain.py:89-101` | `StoreDispatchMiddleware` is registered into the registry under name `"store_dispatch"` AND wrapped a second time by `_StoreTerminal` and passed as the `Pipeline` terminal. Because `DEFAULT_ORDER` contains `"store_dispatch"`, `assemble()` will include `store_mw` in the middleware list, and the pipeline will then call it AGAIN as the terminal. The middleware version receives a `call_next` that points at `_StoreTerminal`, which calls `store_mw` a second time with a no-op `call_next`. Net effect: `store.send(...)` (or any other op) is invoked twice per dispatch, causing duplicate writes / duplicate `message_id` allocation / spurious backpressure increments. This is the most concerning finding; it is a correctness bug that the current test suite does not catch because integration tests likely use stub stores whose double-call is idempotent at the dict level. | **Fix:** either (a) drop `"store_dispatch"` from the `DEFAULT_ORDER` and pass `_StoreTerminal` as terminal only, or (b) keep it in `DEFAULT_ORDER` and pass a no-op terminal. Add a regression test that asserts `store.send` is called exactly once per `Pipeline.dispatch("send", ...)`.

- **warning** | `core/middleware/plugins/store_dispatch.py:50-67` | Docstring claims "calls `call_next` after its own logic" but the implementation never calls `call_next`. This is consistent with terminal-middleware semantics and matches how the rest of the framework uses it, but the docstring is misleading and could lead a plugin author to insert another middleware after `store_dispatch` expecting it to run. | **Fix:** rewrite the docstring to "this middleware is terminal: `call_next` is accepted for protocol conformance but is never invoked. Inserting middleware after `store_dispatch` in the chain has no effect."

- **warning** | `core/identity/verifier.py:198-223` | TOCTOU on `_seen_nonces`: between the registry-lookup `await` and the replay-cache check, another coroutine may insert the same nonce. Two concurrent `verify()` calls with the identical signed envelope can both pass the replay check, then both proceed to signature verification, then both insert. The original identity invariant ("a nonce is consumed at most once within the window") is violated under contention. The `verify()` body has multiple `await` points before the check-and-insert, so this is not a theoretical race — it is reachable. | **Fix:** wrap the prune+check+insert region in an `asyncio.Lock` held by the verifier instance, or move the insert immediately before the first awaitable boundary. Add a concurrency regression test that fires N concurrent `verify()` calls with the same nonce and asserts exactly one succeeds.

- **warning** | `core/middleware/plugins/auth.py:226-233` | On `send`, `bind_for_send` returns a new dict containing `origin_server: None`; the auth plugin then `ctx.input.update(updated_input)`, leaking `origin_server: None` into the input passed to `store_dispatch`. `StoreDispatchMiddleware.send` does not consume `origin_server`, so it is silently dropped — but `spec/ports/identity.md §7` calls out the 12-field envelope; surfacing a null `origin_server` into tool-call surfaces violates the spec §6 rule that the credential seam fields MUST NOT appear in tool-call inputs. | **Fix:** strip `origin_server` from `updated_input` before `ctx.input.update(...)`, or have `bind_for_send` not return it at all in v1.

- **warning** | `core/middleware/default_chain.py:93-97` | `contextlib.suppress(ValueError)` silently swallows duplicate-registration errors. If a caller pre-registers a different `auth` factory and then calls `build_default_pipeline`, the pre-registered one wins silently, with no warning. This is the same class of bug as `MiddlewareRegistry.register` raising `ValueError` on duplicates: callers expect that, but `build_default_pipeline` swallows it. | **Fix:** check `name in registry._factories` explicitly and emit a `warnings.warn` indicating which factory is in effect, or document that pre-registered names always take precedence.

- **warning** | `core/middleware/hooks.py:157` | Hook denial error message uses `getattr(hook, "__name__", "unknown")`. Class-based hooks (the recommended Protocol style) do not have `__name__` on the *instance*; only the class has. Result: every class-based hook denial reports `"hook: unknown"` instead of e.g. `"hook: RateLimitHook"`. | **Fix:** use `getattr(hook, "__name__", None) or type(hook).__name__`.

- **warning** | `core/middleware/context.py:23-39 + 73-78` | `Operation` Literal is exported but `MiddlewareContext.__init__` accepts `operation: str` (not `Operation`), so the Literal narrows nothing at runtime and only has effect on callers that explicitly type-annotate. There is no runtime check that `operation` is one of the 15 v1 ops; an invalid op silently flows through to `StoreDispatchMiddleware` which returns an `internal_error`. A spec-drift test that verifies "`Operation` enum tracks `spec/operations/*.input.schema.json`" — promised in `implementation-plan.json risks[1].mitigation` — does not appear to exist in `tests/middleware/`. | **Fix:** narrow the constructor signature to `operation: Operation`, and add the promised drift test.

- **warning** | `core/middleware/hooks.py:154-156` | A buggy or third-party pre-hook that raises an arbitrary `Exception` is not caught inside `HookDispatcher` — the exception propagates to `Pipeline.dispatch` and is converted to `internal_error`. That is acceptable at the envelope level, but it means a misbehaving observer-only plugin can deny the request entirely (DoS-by-bug). The corresponding test (`test_pre_hook_exception_does_not_block_other_hooks` or similar) is absent. | **Fix:** wrap each hook invocation in `try/except`; on exception, log with `correlation_id` and either fail-open (continue) or fail-closed (deny with `error_code='hook_denied'`) per a documented policy. Pin the policy in the spec / ADR 0003 open questions.

- **warning** | `core/middleware/registry.py:114-126 + 212` | The module-level `register_middleware` singleton is global mutable state. Test files that register against it without cleanup will leak across test runs in the same interpreter. `tests/middleware/test_registry.py:182 test_out_of_core_registration_via_module_api` exists but I did not see a `monkeypatch` / fixture that resets it. | **Fix:** ship a `pytest` fixture in `tests/middleware/conftest.py` that snapshots and restores `register_middleware._factories`; document the discipline.

- **nit** | `core/middleware/plugins/auth.py:177-186` | `_record_timing` mutates `ctx._meta`, but `_meta` is a parallel/private channel with the same shape concern as `ctx.metadata`. Two surfaces is one surface too many for the same purpose. | **Fix:** consolidate to `ctx.metadata.setdefault("middleware_timings", [])`, or document why `_meta` is private and `metadata` is public.

- **nit** | `core/middleware/context.py:127-137` | `agent_id` setter accepts an empty string and treats it as "set"; subsequent setters then raise. A caller (or `bind_for_send` returning empty `sender`) could lock the context into an unauthenticated-but-set state. | **Fix:** raise on empty/whitespace `agent_id`.

- **nit** | `core/middleware/errors.py:27-32` | `make_internal_error` returns `retry_after: None`. The sox-error schema (per `spec/envelopes/sox-error.schema.json`) may require `retry_after` to be omitted when not applicable rather than present-with-null. Did not validate against the schema in this review. | **Fix:** verify against the schema; omit if not applicable.

- **nit** | `core/middleware/default_chain.py:86-101` | `build_default_pipeline` uses lambdas that close over the same `auth_mw` / `store_mw` instances — the "factory" returns a singleton. This is intentional (one verifier, one store per server) but breaks the implied contract of `MiddlewareRegistry.register(name, factory)` where `factory` should produce a fresh instance per `assemble()`. | **Fix:** document the singleton-as-factory pattern, or split the registry API into `register_factory` vs `register_instance`.

- **nit** | `core/middleware/plugins/auth.py:122-159` | `must_run_before` lists `"rate_limit", "schema_validator", "idempotency", "store_dispatch"` — but the topological sort sorts edges deterministically. If a plugin registers a name colliding with one of these, the constraint is silently satisfied without surfacing intent. | **Fix:** add a registry warning when a plugin name collides with a name in any registered middleware's `must_run_before` / `must_run_after` list.

## Spec-fidelity matrix

| Behaviour from spec/ports/middleware.md | Implemented? | Test coverage? |
|---|---|---|
| §2 left-to-right request flow, right-to-left response | yes (`Pipeline._build_call_chain`) | yes (`test_pipeline.py:test_request_flows_left_to_right`, `test_response_flows_right_to_left`) |
| §2 short-circuit skips downstream | yes (`ShortCircuitResponse` + try in dispatch) | yes (`test_short_circuit_skips_subsequent_middlewares`) |
| §3 per-call context (no sharing) | yes (`Pipeline.dispatch` builds fresh `MiddlewareContext`) | yes (`test_pipeline_is_reentrant` — 50 concurrent dispatches) |
| §3 metadata is mutable for inter-MW comms | yes (plain dict) | yes (`test_metadata_is_mutable_for_inter_mw_communication`) |
| §4 default order matches spec | yes (`DEFAULT_ORDER` tuple) | yes (`test_default_order_constant_matches_spec`) |
| §4 auth runs after namespace_resolver, before persistence | yes (`AuthMiddleware.must_run_after/before`) | yes (`test_assemble_rejects_auth_before_namespace_resolver`) |
| §4 store_dispatch is the only persistence link | partial — see store-dispatch double-invocation finding | gap — no test asserts `store.send` invoked exactly once |
| §5 short-circuit response shape | yes (envelope dicts) | partial — no explicit jsonschema validation in tests |
| §6 correlation_id read-only | yes (`freeze_correlation_id`) | yes (`test_correlation_id_cannot_be_overwritten`) |
| §6 connection_id read-only | yes (setter raises) | yes (`test_connection_id_read_only`) |
| §6 agent_id settable once | yes (setter checks `is not None`) | yes (`test_only_auth_may_set_agent_id`) |
| §6 credential seam (no `signed_request` in tool-call input) | yes; deprecated fallback warns and strips | partial — fallback path tested, but `origin_server` leak not caught |
| §7 internal_error envelope on uncaught exceptions | yes (`Pipeline.dispatch` converts) | yes (`test_uncaught_exception_becomes_internal_error`) |
| §7 no traceback leakage to caller | yes (only "Internal server error" message) | yes (`test_internal_error_does_not_leak_traceback`) |
| §9 conformance: default chain refuses unauthenticated send | yes | yes (`test_default_chain_refuses_unauthenticated_send`) |
| ADR 0003 §3 hooks observation-only via `_ImmutableContextView` | yes | yes (`test_hook_cannot_mutate_ctx`) |
| ADR 0003 §4 declarative out-of-tree registration | yes (`register_middleware` singleton + `load_entry_points`) | yes (`test_out_of_core_registration_via_module_api`, `test_external_plugin.py`) |
| identity invariant: unverified caller rejected before backing store | yes (auth raises `ShortCircuitResponse` before forwarding) | yes (`test_default_chain_refuses_unauthenticated_send`); migration regression in `tests/identity/test_migration_regression.py` |
| `core/middleware/` has no adapter imports | yes (verified by inspection: imports only `core.identity.*`, `core.middleware.*`, `core.ports.backing_store`) | enforced by `lint-imports` per plan |

## Test coverage gaps despite headline 100% line cov

1. **Concurrency on identity replay cache** — no test fires concurrent `verify()` with the same nonce. The dict-based `_seen_nonces` is reachable from multiple coroutines and lacks a lock.
2. **`store.<op>` invocation count** — no test asserts the backing-store method is called exactly once per dispatch; the double-invocation bug above is invisible to current tests.
3. **Buggy hook robustness** — no test for "pre-hook raises arbitrary `Exception`" or "post-hook raises after a successful response" — the latter would currently fail the request despite the response being persisted.
4. **`Operation` literal drift test** — promised in `implementation-plan.json risks[1].mitigation` but not present in `tests/middleware/`. CI cannot detect a new spec op going unmodelled.
5. **`origin_server` leak into ctx.input on send** — no assertion that `ctx.input` after auth contains exactly the expected keys.
6. **Module-level `register_middleware` test isolation** — no fixture resets the singleton between tests; cross-test contamination is a latent flake source.
7. **Schema-conformance of short-circuit envelopes** — `test_short_circuit_response_conforms_to_send_output_schema` was promised in the plan; I see assertion-by-key in the tests but not jsonschema validation.

## Sign-off

PASS-WITH-NOTES. The framework is shippable. The store-dispatch double-invocation (the one blocking-class issue) is the single highest-priority follow-up because it silently corrupts the production write path; the verifier replay-race is the second. Both should be fixed before this engagement closes — they are not spec-fidelity issues but they invalidate the very invariants this engagement was set up to protect (auth-before-persistence, replay-protection). Other findings are warnings/nits and can be batched into a follow-up cleanup engagement.

Reviewer: code-reviewer
Date: 2026-05-01
