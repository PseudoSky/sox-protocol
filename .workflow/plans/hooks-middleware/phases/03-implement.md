---
phase_id: 03-implement
title: Build pipeline + migrate identity plugin
agent: python-pro
profile: code-with-spec
estimated_effort: 3-5 days
prereqs: [02-plan]
unblocks: [04-review]
parallelizable_with: []
writes: ["packages/python/src/sox_protocol/core/middleware/**", "packages/python/src/sox_protocol/core/identity/**", "packages/python/tests/middleware/**", "packages/python/tests/identity/**"]
reads:  [".workflow/plans/hooks-middleware/implementation-plan.json", "docs/adr/**", "spec/ports/middleware.md", "packages/python/src/sox_protocol/core/**"]
context_size: large
---

# 03 — Implement

## Objective

Build the middleware/hooks pipeline per `implementation-plan.json`. Migrate identity into it as the first plugin. Ship a sample second plugin demonstrating composition.

## Inputs

- `.workflow/plans/hooks-middleware/implementation-plan.json`
- `docs/adr/0003-extensibility-mechanism.md`
- `spec/ports/middleware.md`
- `packages/python/src/sox_protocol/core/identity/` (to migrate)

## Prompt (verbatim)

```text
Implement the SOX Protocol extensibility framework. Follow the structured plan exactly.

READ:
1. .workflow/plans/hooks-middleware/implementation-plan.json (your contract)
2. docs/adr/0003-extensibility-mechanism.md
3. spec/ports/middleware.md
4. packages/python/src/sox_protocol/core/identity/ (existing code to migrate per plan.migration_notes)

DELIVER:
- Every file in plan.files[]
- Identity check migrated; identity-primitive engagement's existing tests must still pass
- One sample plugin from plan (logging or rate-limit)
- Plugin registration documented in module docstring
- Test cases per plan.test_plan[]

HARD CONSTRAINTS:
- 100% line coverage on core/middleware/
- Existing identity tests in tests/identity/ remain green (this is a regression check)
- mypy --strict, lint-imports, ruff clean
- Plugin can be registered from outside core/ — write a test that does this from the test suite, not from core itself

ACCEPTANCE:
- pytest tests/middleware/ -q passes
- pytest tests/identity/ -q still passes (regression)
- pytest --cov=src/sox_protocol/core/middleware --cov-fail-under=100
- mypy --strict src/sox_protocol/core/middleware/
- lint-imports

REPORT: ≤ 250 words. Files written, regression status, coverage percentage.
```

## Exit criteria

Universal (`code-with-spec` / `code-python`):
- [ ] `cd packages/python && pytest tests/middleware/ tests/identity/ --cov=src/sox_protocol/core/middleware --cov-fail-under=100 -q`
- [ ] `cd packages/python && mypy --strict src/sox_protocol/core/middleware/`
- [ ] `cd packages/python && lint-imports`
- [ ] `cd packages/python && ruff check src/sox_protocol/core/middleware/ tests/middleware/`
- [ ] `! grep -rE '(SECRET|PASSWORD|API_KEY)\s*=\s*["\047][^"\047]+' packages/python/src/sox_protocol/core/middleware/`
- [ ] `python3 -c "import json,os; p=json.load(open('.workflow/plans/hooks-middleware/implementation-plan.json')); missing=[f['path'] for f in p['files'] if not os.path.exists(f['path'])]; assert not missing"`

Engagement-specific:
- [ ] Identity regression: `cd packages/python && pytest tests/identity/ -q` — passes after migration

## Outputs

- `packages/python/src/sox_protocol/core/middleware/`
- `packages/python/tests/middleware/`
- (modifications to identity to register as plugin)

## Next state

Promote `04-review` → READY.
