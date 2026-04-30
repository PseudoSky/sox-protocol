---
phase_id: 02-plan
title: Implementation plan from ADR + spec
agent: sox-cto-system:planner
profile: planning
estimated_effort: 1-2 hours
prereqs: [01-adr]
unblocks: [03-implement]
parallelizable_with: []
writes: [".workflow/plans/hooks-middleware/implementation-plan.json"]
reads:  ["docs/adr/**", "spec/ports/middleware.md", "packages/python/src/sox_protocol/core/identity/**"]
context_size: medium
---

# 02 — Plan

## Objective

Structured JSON implementation plan for the middleware/hooks framework, including identity-plugin migration and a sample second plugin.

## Inputs

- `docs/adr/0003-extensibility-mechanism.md`
- `spec/ports/middleware.md`
- `packages/python/src/sox_protocol/core/identity/` (current identity code to migrate)

## Prompt (verbatim)

```text
Produce a JSON implementation plan for SOX Protocol's extensibility framework.

READ:
- docs/adr/0003-extensibility-mechanism.md (the decision)
- spec/ports/middleware.md (the contract)
- packages/python/src/sox_protocol/core/identity/ (existing identity plugin to migrate)
- .workflow/plans/hooks-middleware/phases/03-implement.md (downstream implementer that consumes your plan — read it so your file list, migration_notes, and test_plan match what the implementer expects)

OUTPUT: /Users/nix/dev/ai/sox-protocol/.workflow/plans/hooks-middleware/implementation-plan.json

JSON SHAPE:
{
  "summary": "...",
  "files": [{"path": "...", "spec_ref": "spec/ports/middleware.md §...", "purpose": "...", "public_api": [...]}],
  "test_plan": [{"spec_section": "...", "test_cases": [...]}],
  "risks": [...],
  "dependencies": [...],
  "build_order": [...],
  "exit_signals": [
    "100% coverage on core/middleware/",
    "Identity tests still pass after migration",
    "Sample plugin (logging or rate-limit) registered and exercised by tests",
    "lint-imports clean"
  ],
  "migration_notes": "<how identity moves from core/identity standalone to plugin in core/middleware>"
}

HARD CONSTRAINTS:
- Identity migration must keep existing identity-primitive tests green (or update them to use the new registration API).
- Plugin registration is an extension point — show in plan.public_api how a third party registers their own plugin.
- One sample plugin must be included (suggest: logging plugin that writes to ~/.sox/logs/middleware.jsonl).

END YOUR REPORT WITH A RESERVATIONS BLOCK.

The orchestrator extracts this block to gate parallel dispatch of the downstream 03-implement phase. After your prose REPORT, output (no other text after):

RESERVATIONS:
- <path>
- <path>
END_RESERVATIONS

Rules:
- One path per line, prefixed with `- `
- Plain string paths, no globs, no quotes
- The list MUST be byte-identical to the set of paths in plan.files[].path
- Include both new files AND any files modified during identity-migration

REPORT: file count, test_plan count, confirmation of migration plan included. Then the RESERVATIONS block.
```

## Exit criteria

Universal (`planning` profile):
- [ ] `test -f .workflow/plans/hooks-middleware/implementation-plan.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/hooks-middleware/implementation-plan.json')); assert all(k in p for k in ['summary','files','test_plan','risks','dependencies','build_order','exit_signals','migration_notes'])"`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/hooks-middleware/implementation-plan.json')); assert all('spec_ref' in f for f in p['files'])"`
- [ ] `test -f .workflow/plans/hooks-middleware/reservations/03-implement.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/hooks-middleware/implementation-plan.json')); r=json.load(open('.workflow/plans/hooks-middleware/reservations/03-implement.json')); assert set(f['path'] for f in p['files']) == set(r['files'])"`

## Outputs

- `.workflow/plans/hooks-middleware/implementation-plan.json`

## Next state

Promote `03-implement` → READY.
