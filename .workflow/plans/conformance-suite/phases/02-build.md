---
phase_id: 02-build
title: Build fixtures + harness + CI
agent: test-automator
profile: test-harness
estimated_effort: 3-5 days
prereqs: [01-plan]
unblocks: []
parallelizable_with: []
writes: ["spec/conformance/**", "tools/conformance_runner.py", "tools/conformance_runner_tests/**", ".github/workflows/conformance.yml"]
reads:  [".workflow/plans/conformance-suite/implementation-plan.json", "spec/**", "packages/python/**"]
context_size: large
---

# 02 — Build

## Objective

Implement the conformance suite per `implementation-plan.json`: fixtures, harness, CI workflow.

## Inputs

- `.workflow/plans/conformance-suite/implementation-plan.json`
- `spec/` (the spec to validate against)
- `packages/python/` (the reference impl that will be the first conformant target)

## Prompt (verbatim)

```text
Build the SOX Protocol conformance suite per the structured plan.

READ:
- .workflow/plans/conformance-suite/implementation-plan.json (your contract)
- spec/ (the spec authority)
- packages/python/ (the first conformant target)

DELIVER:
- Every fixture in plan.fixtures[] at the exact path
- tools/conformance_runner.py per plan.harness
- .github/workflows/conformance.yml per plan.ci_workflow
- spec/conformance/README.md explaining the fixture format and how third-party impls register
- Harness has unit tests at tools/conformance_runner_tests/ with 100% line coverage
- All fixtures parse cleanly
- Python reference impl passes 100% of fixtures

HARD CONSTRAINTS:
- Fixture format: declarative YAML — setup, sequence of operations, expected responses, expected store state. Documented in plan.fixture_format.schema.
- Harness loads fixtures from spec/conformance/ recursively, runs each against the target, reports per-fixture pass/fail with diffs.
- CI runs the harness on every PR; fails the build on any fixture failure.
- Harness must work against the Python impl via stdio (use the existing MCP server entry point).

ACCEPTANCE:
- pytest tools/conformance_runner_tests/ --cov=tools.conformance_runner --cov-fail-under=100 -q
- python3 tools/conformance_runner.py --target packages/python --strict (exits 0)
- yamllint spec/conformance/ passes
- CI workflow file is valid yaml: python3 -c "import yaml; yaml.safe_load(open('.github/workflows/conformance.yml'))"

REPORT: ≤ 250 words. Fixture count, harness LOC, CI workflow summary, the one fixture that revealed the most about the reference impl during integration.
```

## Exit criteria

Universal (`test-harness`):
- [ ] `python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('spec/conformance/**/*.yaml', recursive=True)]"`
- [ ] `python3 tools/conformance_runner.py --target packages/python --strict` (exit 0)
- [ ] `test -f .github/workflows/conformance.yml`
- [ ] `cd tools && pytest conformance_runner_tests/ --cov=conformance_runner --cov-fail-under=100 -q`

Engagement-specific:
- [ ] `test -f spec/conformance/README.md`
- [ ] `python3 -c "import json,os; p=json.load(open('.workflow/plans/conformance-suite/implementation-plan.json')); missing=[f['path'] for f in p['fixtures'] if not os.path.exists(f['path'])]; assert not missing"`

## Outputs

- `spec/conformance/*.yaml` (fixtures)
- `tools/conformance_runner.py`
- `tools/conformance_runner_tests/`
- `.github/workflows/conformance.yml`
- `spec/conformance/README.md`

## Next state

Leaf. Engagement complete on DONE.
