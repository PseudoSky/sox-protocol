---
phase_id: 01-plan
title: Test plan from spec
agent: sox-cto-system:planner
profile: planning
estimated_effort: 2-3 hours
prereqs: []
unblocks: [02-build]
parallelizable_with: []
writes: [".workflow/plans/conformance-suite/implementation-plan.json"]
reads:  ["spec/**", "packages/python/src/**"]
context_size: medium
---

# 01 — Plan

## Objective

Produce a JSON test plan: every spec section gets fixtures; fixture format + harness shape are designed; CI integration sketched.

## Inputs

- `spec/` (entire tree, from spec-extraction)
- `spec/conformance/` (existing fixtures, if any — audit)
- `packages/python/src/sox_protocol/` (reference impl the fixtures will run against)

## Prompt (verbatim)

```text
Produce a JSON conformance-suite plan for SOX Protocol.

READ:
- spec/ entire tree
- spec/conformance/ (existing fixtures — audit, integrate, do not duplicate)
- packages/python/src/sox_protocol/
- .workflow/plans/conformance-suite/phases/02-build.md (downstream build phase — read its prompt and exit criteria so your fixture paths, harness API shape, and CI workflow match what the builder expects)

OUTPUT: /Users/nix/dev/ai/sox-protocol/.workflow/plans/conformance-suite/implementation-plan.json

SHAPE:
{
  "summary": "...",
  "fixture_format": {
    "language": "yaml",
    "schema": {<inline schema for fixture files>}
  },
  "fixtures": [
    {
      "path": "spec/conformance/<category>/<name>.yaml",
      "spec_ref": "spec/<file>.md §<section>",
      "purpose": "<what behaviour this validates>",
      "operations": ["send","recv","subscribe","list_channels","ack","nack"]
    },
    ...
  ],
  "harness": {
    "path": "tools/conformance_runner.py",
    "public_api": ["run(target, fixtures) -> {pass: int, fail: int, details: [...]}"],
    "spec_ref": "spec/conformance/README.md"
  },
  "ci_workflow": {
    "path": ".github/workflows/conformance.yml",
    "matrix": ["python-reference"],
    "future_matrix_entries": ["typescript-reference", "rust-reference"]
  },
  "files": [<every file the build phase will create>],
  "test_plan": [<harness's own unit tests>],
  "risks": [...],
  "dependencies": ["pyyaml", "pytest"],
  "build_order": [...],
  "exit_signals": [
    "All fixtures parse",
    "Python reference impl passes 100% of fixtures",
    "Harness has 100% coverage on its own runner code",
    "CI workflow runs on PR"
  ]
}

CATEGORIES TO COVER (minimum):
- send-recv-basic
- subscription-patterns
- threading
- groups
- dms
- ack-nack
- identity-verification
- sequence-monotonicity
- presence

For each category, include enough fixtures to cover the happy path AND at least one failure-mode (e.g. unauthorized send, malformed envelope).

END YOUR REPORT WITH A RESERVATIONS BLOCK.

The orchestrator extracts this block to gate parallel dispatch of the downstream 02-build phase. After your prose REPORT, output (no other text after):

RESERVATIONS:
- <path>
- <path>
END_RESERVATIONS

Rules:
- One path per line, prefixed with `- `
- Include every fixture path AND the harness path AND every test file AND the CI workflow file — i.e. plan.fixtures[].path ∪ plan.harness.path ∪ plan.test_plan files ∪ plan.ci_workflow.path
- Plain string paths, no globs, no quotes
- The set must be byte-identical to plan.files[].path

REPORT: fixture count by category, total file count, harness API summary. Then the RESERVATIONS block.
```

## Exit criteria

Universal (`planning`):
- [ ] `test -f .workflow/plans/conformance-suite/implementation-plan.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/conformance-suite/implementation-plan.json')); assert all(k in p for k in ['summary','fixture_format','fixtures','harness','ci_workflow','files','test_plan','exit_signals'])"`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/conformance-suite/implementation-plan.json')); assert all('spec_ref' in f for f in p['fixtures'])"`
- [ ] `test -f .workflow/plans/conformance-suite/reservations/02-build.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/conformance-suite/implementation-plan.json')); r=json.load(open('.workflow/plans/conformance-suite/reservations/02-build.json')); assert set(f['path'] for f in p['files']) == set(r['files'])"`

## Outputs

- `.workflow/plans/conformance-suite/implementation-plan.json`

## Next state

Promote `02-build` → READY.
