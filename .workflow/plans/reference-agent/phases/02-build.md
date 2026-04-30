---
phase_id: 02-build
title: Build agent + tests + walkthrough
agent: python-pro
profile: code-with-spec
estimated_effort: 2-3 days
prereqs: [01-plan]
unblocks: []
parallelizable_with: []
writes: ["examples/reference-agent/**", "packages/python/tests/reference_agent/**"]
reads:  [".workflow/plans/reference-agent/implementation-plan.json", "spec/**", "packages/python/src/**"]
context_size: large
---

# 02 — Build

## Objective

Build the reference agent per `implementation-plan.json`. Heavy annotation, runnable both ways, integration-tested.

## Inputs

- `.workflow/plans/reference-agent/implementation-plan.json`
- `spec/protocol.md`, `spec/primitives/`
- `packages/python/src/sox_protocol/`

## Prompt (verbatim)

```text
Build the SOX Protocol canonical reference agent per the structured plan.

READ:
1. .workflow/plans/reference-agent/implementation-plan.json (contract)
2. spec/protocol.md, spec/primitives/
3. packages/python/src/sox_protocol/ (SDK)

DELIVER:
- Every file in plan.files[]
- Every lifecycle step in plan.lifecycle[] is implemented in agent.py with the prescribed annotation density
- README walkthrough mirrors the lifecycle steps in prose
- Standalone run script
- Claude Code agent definition (.claude-agent.md or equivalent)
- Tests per plan.test_plan[]
- CI integration test that spins up the agent + a partner and runs a scripted exchange

HARD CONSTRAINTS:
- 100% coverage on agent.py logic
- mypy --strict
- Annotation density: at minimum 1 comment line per 3 code lines (excluding tests)
- Standalone run completes in ≤ 30s without manual input
- README walkthrough is teaching-grade prose, not just an API reference

ACCEPTANCE:
- pytest packages/python/tests/reference_agent/ --cov=examples.reference_agent.agent --cov-fail-under=100 -q
- mypy --strict examples/reference-agent/agent.py
- bash examples/reference-agent/run_standalone.sh exits 0 within 30s
- Integration test passes: agent + partner exchange happens via SOX backing store

REPORT: ≤ 250 words. Annotation density achieved (lines/comment-lines), test coverage, integration-test summary.
```

## Exit criteria

Universal (`code-with-spec` / `code-python`):
- [ ] `cd packages/python && pytest tests/reference_agent/ --cov-fail-under=100 -q`
- [ ] `mypy --strict examples/reference-agent/agent.py`
- [ ] `cd packages/python && lint-imports`
- [ ] `python3 -c "import json,os; p=json.load(open('.workflow/plans/reference-agent/implementation-plan.json')); missing=[f['path'] for f in p['files'] if not os.path.exists(f['path'])]; assert not missing"`

Engagement-specific:
- [ ] `bash examples/reference-agent/run_standalone.sh` (exits 0, ≤ 30s)
- [ ] `test -f examples/reference-agent/README.md`

## Outputs

- `examples/reference-agent/`
- `packages/python/tests/reference_agent/`

## Next state

Leaf. Engagement complete on DONE.
