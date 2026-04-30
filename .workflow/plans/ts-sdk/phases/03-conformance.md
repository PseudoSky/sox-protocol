---
phase_id: 03-conformance
title: TS conformance harness
agent: test-automator
profile: test-harness
estimated_effort: 1-2 days
prereqs: [02-build]
unblocks: []
parallelizable_with: []
writes: ["tools/conformance_runner_ts/**", ".github/workflows/conformance.yml"]
reads:  ["spec/conformance/**", "packages/typescript/**"]
context_size: medium
---

# 03 — Conformance

## Objective

Implement a TS-side conformance harness that consumes `spec/conformance/*.yaml` and validates them via `@sox-protocol/client`. Proves the spec is portable beyond Python — strongest single signal that SOX is a real protocol.

## Inputs

- `spec/conformance/*.yaml`
- `tools/conformance_runner.py` (Python harness — model after)
- `packages/typescript/` (the TS SDK)

## Prompt (verbatim)

```text
Build a TypeScript conformance harness that consumes the language-neutral fixtures at spec/conformance/ and validates them via @sox-protocol/client.

READ:
- tools/conformance_runner.py (Python model)
- spec/conformance/*.yaml (fixtures)
- packages/typescript/src/ (the SDK to test)

DELIVER:
- tools/conformance_runner_ts/ — TS harness, vitest-based
- Fixture loader (YAML → typed scenarios)
- Runner that exercises @sox-protocol/client against a running Python HTTP server target
- Per-fixture pass/fail report identical in shape to Python harness
- CI matrix entry: TS harness against Python HTTP server

HARD CONSTRAINTS:
- Same fixture format. Any divergence in interpretation is a spec ambiguity — surface it.
- All fixtures must pass identically across Python (stdio + http) and TS (http) targets.
- TS harness has its own unit tests; 100% coverage.

ACCEPTANCE:
- cd tools/conformance_runner_ts && pnpm test --coverage --coverage.thresholds.100=true
- pnpm conformance --target python-http --strict (against running server) exits 0
- .github/workflows/conformance.yml has the TS matrix entry

REPORT: ≤ 200 words. Per-target pass counts. Any spec ambiguity surfaced.
```

## Exit criteria

Universal (`test-harness`):
- [ ] `cd tools/conformance_runner_ts && pnpm test --coverage --coverage.thresholds.100=true`
- [ ] `cd tools/conformance_runner_ts && pnpm conformance --target python-http --strict`
- [ ] `grep -q 'conformance_runner_ts\|@sox-protocol/client' .github/workflows/conformance.yml`

## Outputs

- `tools/conformance_runner_ts/`
- Updated CI workflow

## Next state

Leaf. Engagement complete on DONE.
