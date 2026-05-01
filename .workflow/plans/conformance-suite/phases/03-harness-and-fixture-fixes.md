---
phase_id: 03-harness-and-fixture-fixes
title: Fix threading capture-substitution + un-skip 27 fixtures gated on harness/impl features
agent: test-automator
profile: code-with-spec
estimated_effort: 1-2 days
prereqs: [02-build, http-transport:04-spec-realignment, identity-primitive:05-spec-realignment, hooks-middleware:05-op-coverage]
unblocks: []
parallelizable_with: []
writes: ["spec/conformance/**", "tools/conformance_runner.py", "packages/python/src/sox_protocol/**", "packages/python/tests/conformance/**"]
reads:  ["spec/**", "tools/conformance_runner.py", ".workflow/plans/conformance-suite/implementation-plan.json"]
context_size: medium
---

# 03 — Harness and fixture fixes (salvage follow-up)

## Inputs

- `tools/conformance_runner.py` — shipped harness (1512 LOC)
- 59 fixtures under `spec/conformance/` (27 originally-shipped + 32 added in 02-build)
- `.workflow/plans/conformance-suite/implementation-plan.json`
- The just-landed sibling fixes:
  - `http-transport:04-spec-realignment` (emits `backpressure_over_limit`, `validation_error`, wildcard rejection, schema-validated inputs)
  - `identity-primitive:05-spec-realignment` (`origin_server` in envelope, `signed_request` off tool surface)
  - `hooks-middleware:05-op-coverage` (15-op `Operation` literal, full `StoreDispatchMiddleware` coverage)

## Background

Result of `python3 tools/conformance_runner.py --target packages/python --strict` after 02-build: **30 pass / 2 fail / 27 skip / 59 total**.

This phase closes the gap to fully green.

## Prompt (verbatim)

```text
Bring the conformance suite to all-green strict mode.

DELIVER:

1. Fix the 2 failing originally-shipped fixtures:
   - spec/conformance/threading/01-thread-depth-tracked.yaml
   - spec/conformance/threading/02-thread-deep-reply.yaml
   Failure: assertion uses `reply_to: "{{capture:send-level-N.message_id}}"` but the harness does not substitute capture references in expected values; the actual output has `reply_to: "2"` (the literal captured value).
   Fix path A: extend tools/conformance_runner.py to resolve `{{capture:<step-id>.<field>}}` references in expected assertion values during diff (preferred — also unblocks future fixtures). Add unit tests for the resolver in tests/conformance/.
   Fix path B (fallback): rewrite the two fixture assertions to use literal values once the harness ordering is deterministic. Only choose this if path A introduces unacceptable harness complexity.

2. Un-skip the 27 SKIPPED new fixtures from 02-build:
   - List them: `python3 tools/conformance_runner.py --target packages/python --strict 2>&1 | grep '\[SKIP\]'`
   - For each SKIP, identify the gating reason (likely one of):
     a) Missing fault-injection hook → wire `SOX_TEST_FAULTS=1` hooks into the python reference impl per implementation-plan.json risks R1/R4/R5
     b) Missing error code emission → confirm http-transport:04 landed `backpressure_over_limit` and `validation_error`; if reference impl is stdio-only for the fixture, ensure stdio path emits them too
     c) Missing op coverage in StoreDispatchMiddleware → confirm hooks-middleware:05 landed all 15 ops; if a fixture targets one of those new ops, the path is now real
     d) Missing harness feature (e.g. version-negotiation hook, idempotency replay support) → extend harness minimally
   - Either fix the gating cause or, if a fixture is genuinely premature (e.g. depends on post-v1 federation), mark it `tags: [post-v1]` in the YAML and configure the runner to exclude post-v1 tags by default.

3. Add fault-injection hooks if not yet present:
   - `SOX_TEST_FAULTS=1` env-gated. Locations: backing-store (force store_unavailable), middleware (force internal_error), transport (force backpressure_over_limit), identity (force identity_failure).
   - Each hook is minimal, gated, and never affects production code paths.

4. Wire into CI:
   - Confirm .github/workflows runs `python3 tools/conformance_runner.py --target packages/python --strict` on every PR.
   - Confirm `spec/conformance/README.md` exists and explains how a third-party impl registers (this is a phase 02-build termination target that may not have shipped).

HARD CONSTRAINTS:
- All 109 HTTP tests + 76 identity tests + 99 middleware tests still pass.
- After fixes: `python3 tools/conformance_runner.py --target packages/python --strict` exits 0 with all 59 fixtures PASS (or 59 minus any post-v1 tagged-out).
- Harness changes covered by unit tests in tests/conformance/.

EXIT CRITERIA:
- `python3 tools/conformance_runner.py --target packages/python --strict` → exit 0
- All non-post-v1 fixtures PASS
- `grep -r "SOX_TEST_FAULTS" packages/python/src/sox_protocol/ | wc -l` → ≥4 (one hook per layer)
- `ls spec/conformance/README.md` exists

ON COMPLETION:
- Mark 03-harness-and-fixture-fixes DONE in STATE.md
- Stage all changes; do NOT commit
- Return terse report (≤300 words)
```

## Acceptance criteria (machine-checkable)

- [ ] `python3 tools/conformance_runner.py --target packages/python --strict` exits 0
- [ ] `grep -c '\[FAIL\]\|\[SKIP\]'` of the runner output → 0 (excluding post-v1 tagged fixtures)
- [ ] At least 4 `SOX_TEST_FAULTS` hook sites across the python reference impl
- [ ] `spec/conformance/README.md` documents third-party impl registration
