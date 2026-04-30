---
phase_id: 03-implement
title: Build credential registry + middleware
agent: python-pro
profile: code-with-spec
estimated_effort: 2-3 days
prereqs: [02-plan]
unblocks: [04-review]
parallelizable_with: []
writes: ["packages/python/src/sox_protocol/core/identity/**", "packages/python/tests/identity/**"]
reads:  [".workflow/plans/identity-primitive/implementation-plan.json", "docs/adr/**", "spec/ports/**", "packages/python/src/**"]
context_size: large
---

# 03 — Implement

## Objective

Implement the identity layer per `implementation-plan.json`. Per-agent credential registry, identity middleware as the first plugin in the middleware pipeline, audit log on rejection, full test coverage.

## Inputs

- `/Users/nix/dev/ai/sox-protocol/.workflow/plans/identity-primitive/implementation-plan.json` (planner output — follow it)
- `/Users/nix/dev/ai/sox-protocol/docs/adr/0002-agent-identity-primitive.md`
- `/Users/nix/dev/ai/sox-protocol/spec/ports/identity.md`
- `/Users/nix/dev/ai/sox-protocol/spec/ports/middleware.md`
- `/Users/nix/dev/ai/sox-protocol/packages/python/src/sox_protocol/` (codebase)

## Prompt (verbatim)

```text
Implement the SOX Protocol identity layer. Follow the structured plan exactly.

READ FIRST:
1. .workflow/plans/identity-primitive/implementation-plan.json — your contract; build every files[] entry, satisfy every test_plan[] case
2. docs/adr/0002-agent-identity-primitive.md — the decision rationale
3. spec/ports/identity.md — the guarantee
4. spec/ports/middleware.md — the pipeline you plug into
5. packages/python/src/sox_protocol/core/ — existing structure

DELIVER:
- Every file in plan.files[] at the exact path specified
- Tests for every plan.test_plan[].test_cases[] entry
- ~/.sox/logs/identity-failures.jsonl gets one line per rejected request, format {ts, claimed_agent_id, reason, operation}
- Identity middleware is registered as first in the middleware chain; unverified callers rejected before any backing-store access

HARD CONSTRAINTS:
- 100% line coverage on every file under packages/python/src/sox_protocol/core/identity/
- mypy --strict passes on the new module
- lint-imports passes (core/ MUST NOT import from adapters/)
- ruff check clean
- No secrets in source code
- Spec-version trailer goes on the commit (orchestrator's job; you just ensure clean state)

ACCEPTANCE (self-check):
- [ ] All files[] in plan exist
- [ ] pytest packages/python/tests/identity/ -q passes
- [ ] pytest --cov=src/sox_protocol/core/identity --cov-fail-under=100 passes
- [ ] mypy --strict src/sox_protocol/core/identity/ passes
- [ ] lint-imports passes
- [ ] Audit log entry appears when running the rejection-path integration test

REPORT: one paragraph summary plus list of files written plus test count plus coverage percentage. ≤ 250 words.
```

## Exit criteria

Universal (`code-with-spec` profile, inherits `code-python`):
- [ ] `cd packages/python && pytest tests/identity/ --cov=src/sox_protocol/core/identity --cov-fail-under=100 -q`
- [ ] `cd packages/python && mypy --strict src/sox_protocol/core/identity/`
- [ ] `cd packages/python && lint-imports`
- [ ] `cd packages/python && ruff check src/sox_protocol/core/identity/ tests/identity/`
- [ ] `! grep -rE '(SECRET|PASSWORD|API_KEY)\s*=\s*["\047][^"\047]+' packages/python/src/sox_protocol/core/identity/`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/identity-primitive/implementation-plan.json')); import os; missing=[f['path'] for f in p['files'] if not os.path.exists(f['path'])]; assert not missing, f'planner-predicted files missing: {missing}'"`

Engagement-specific:
- [ ] Integration test demonstrating audit log on rejection: `cd packages/python && pytest tests/identity/test_audit_log.py -q`

## Outputs

- `packages/python/src/sox_protocol/core/identity/` (per plan.files[])
- `packages/python/tests/identity/` (per plan.test_plan[])

## Next state

Promote `04-review` → READY.
