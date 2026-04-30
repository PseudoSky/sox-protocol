---
phase_id: 02-plan
title: Implementation plan from ADR + spec
agent: sox-cto-system:planner
profile: planning
estimated_effort: 1-2 hours
prereqs: [01-adr]
unblocks: [03-implement]
parallelizable_with: []
writes: [".workflow/plans/identity-primitive/implementation-plan.json"]
reads:  ["docs/adr/**", "spec/ports/**", "packages/python/src/**"]
context_size: medium
---

# 02 — Plan

## Objective

Produce a structured implementation plan as JSON for the credential registry + identity middleware. Driven by `sox-cto-system:planner` reading the ADR + spec/ports/identity.md. The implementer phase consumes the JSON.

## Inputs

- `/Users/nix/dev/ai/sox-protocol/docs/adr/0002-agent-identity-primitive.md` (output of 01-adr)
- `/Users/nix/dev/ai/sox-protocol/spec/ports/identity.md` (output of `spec-extraction` engagement)
- `/Users/nix/dev/ai/sox-protocol/spec/ports/middleware.md`
- `/Users/nix/dev/ai/sox-protocol/packages/python/src/sox_protocol/core/` — existing core; the new module slots into core/identity/

## Prompt (verbatim)

```text
You are producing a structured implementation plan for the SOX Protocol identity layer. Native output: JSON.

READ:
- docs/adr/0002-agent-identity-primitive.md (the credential decision)
- spec/ports/identity.md (the verified-sender guarantee)
- spec/ports/middleware.md (the pipeline this plugs into)
- packages/python/src/sox_protocol/core/ (the codebase shape; place new code at core/identity/)
- .workflow/plans/identity-primitive/phases/03-implement.md (the downstream implementer phase that consumes your plan — read its prompt and exit criteria so your file list, public_api shapes, and test_plan match what the implementer expects)

PRODUCE: /Users/nix/dev/ai/sox-protocol/.workflow/plans/identity-primitive/implementation-plan.json

JSON SCHEMA (output exactly this shape):
{
  "summary": "<one paragraph: what gets built, in what order>",
  "files": [
    {
      "path": "packages/python/src/sox_protocol/core/identity/registry.py",
      "spec_ref": "spec/ports/identity.md §<section>",
      "purpose": "<one sentence>",
      "public_api": ["fn1(...) -> ...", "fn2(...) -> ..."]
    },
    ...
  ],
  "test_plan": [
    {
      "spec_section": "spec/ports/identity.md §<section>",
      "test_cases": [
        "test_<name> — <what it validates>",
        ...
      ]
    },
    ...
  ],
  "risks": [
    {"risk": "<...>", "mitigation": "<...>"}
  ],
  "dependencies": ["cryptography>=41", ...],
  "build_order": ["registry.py", "middleware.py", "audit.py", "tests"],
  "exit_signals": [
    "100% coverage on core/identity/",
    "mypy --strict clean",
    "lint-imports clean (no core→adapters)",
    "audit log writes to ~/.sox/logs/identity-failures.jsonl on rejection"
  ]
}

HARD CONSTRAINTS:
- Every files[] entry has spec_ref. No file without a contract reference.
- test_plan covers every spec_section that imposes runtime behaviour (rejection on mismatch, audit on rejection, etc.).
- build_order respects: registry before middleware (middleware depends on registry); tests after both.
- Plan must be implementable by a single python-pro agent in one phase.

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
- Empty block permitted only if the file list is genuinely dynamic (not the case here — list every file)

REPORT: confirm the plan was written, list files[] count and test_plan[] count. Then the RESERVATIONS block.
```

## Exit criteria

Universal (`planning` profile):
- [ ] `test -f .workflow/plans/identity-primitive/implementation-plan.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/identity-primitive/implementation-plan.json')); assert all(k in p for k in ['summary','files','test_plan','risks','dependencies','build_order','exit_signals'])"`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/identity-primitive/implementation-plan.json')); assert all('spec_ref' in f for f in p['files'])"`
- [ ] `test -f .workflow/plans/identity-primitive/reservations/03-implement.json` (orchestrator-persisted)
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/identity-primitive/implementation-plan.json')); r=json.load(open('.workflow/plans/identity-primitive/reservations/03-implement.json')); assert set(f['path'] for f in p['files']) == set(r['files']), 'reservations diverge from plan.files'"`

## Outputs

- `.workflow/plans/identity-primitive/implementation-plan.json`

## Next state

Promote `03-implement` → READY.
