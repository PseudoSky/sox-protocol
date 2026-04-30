---
phase_id: 03-conformance
title: Run conformance against HTTP target
agent: test-automator
profile: test-harness
estimated_effort: 1 day
prereqs: [02-build]
unblocks: []
parallelizable_with: []
writes: ["tools/conformance_runner.py", ".github/workflows/conformance.yml", "spec/conformance/README.md"]
reads:  ["spec/conformance/**", "packages/python/src/**"]
context_size: medium
---

# 03 — Conformance

## Inputs

- `tools/conformance_runner.py` (output of conformance-suite engagement)
- `spec/conformance/*.yaml`
- HTTP transport from 02-build

## Prompt (verbatim)

```text
Run the SOX Protocol conformance suite against the HTTP transport. Extend the harness if it doesn't already support multiple transport targets.

READ:
- tools/conformance_runner.py (existing harness)
- spec/conformance/ (fixtures)
- packages/python/src/sox_protocol/adapters/transports/http/ (the new target)

DELIVER:
- Extend conformance_runner if needed to accept --transport stdio|http
- Add CI matrix entry: same conformance fixtures, two transport targets
- Document the matrix in spec/conformance/README.md

HARD CONSTRAINTS:
- All fixtures must pass identically against stdio and http. Any divergence is a transport-port-spec violation, not a fixture problem — surface it.
- CI runs both targets on every PR.

ACCEPTANCE:
- python tools/conformance_runner.py --target packages/python --transport http --strict (exit 0)
- python tools/conformance_runner.py --target packages/python --transport stdio --strict (still passes — regression check)
- .github/workflows/conformance.yml has both transports in matrix

REPORT: ≤ 200 words. Pass count for each transport. Any divergence found.
```

## Exit criteria

Universal (`test-harness`):
- [ ] `python3 tools/conformance_runner.py --target packages/python --transport http --strict`
- [ ] `python3 tools/conformance_runner.py --target packages/python --transport stdio --strict` (regression)

Engagement-specific:
- [ ] `grep -q 'http' .github/workflows/conformance.yml`

## Outputs

- Updated `tools/conformance_runner.py`
- Updated CI workflow
- Updated `spec/conformance/README.md`

## Next state

Leaf. Engagement complete on DONE.
