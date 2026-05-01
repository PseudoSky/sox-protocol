---
phase_id: 01-plan
title: Lifecycle plan from spec primitives
agent: sox-cto-system:planner
profile: planning
estimated_effort: 2 hours
prereqs: []
unblocks: [02-build]
parallelizable_with: []
writes: [".workflow/plans/reference-agent/implementation-plan.json"]
reads:  ["spec/**", "packages/python/src/**"]
context_size: medium
---

# 01 — Plan

## Objective

JSON plan for a canonical reference agent that demonstrates every protocol primitive end-to-end in a heavily-annotated form.

## Inputs

- `spec/primitives/` (every primitive should appear in the agent's lifecycle)
- `spec/protocol.md`
- `packages/python/src/sox_protocol/` (the SDK the agent uses)

## Prompt (verbatim)

```text
Produce a JSON plan for the SOX Protocol canonical reference agent.

READ:
- spec/protocol.md, spec/primitives/
- packages/python/src/sox_protocol/ (the SDK)
- .workflow/plans/reference-agent/phases/02-build.md (downstream build phase — read its prompt so your lifecycle steps, file paths, and test_plan match what the builder expects to receive)

OUTPUT: /Users/nix/dev/ai/sox-protocol/.workflow/plans/reference-agent/implementation-plan.json

SHAPE:
{
  "summary": "...",
  "lifecycle": [
    {"step": "bootstrap", "spec_ref": "spec/protocol.md §bootstrap-sequence", "operations": ["subscribe","list_channels","list_agents","recv"], "annotation": "<what the agent author should learn here>"},
    {"step": "main_loop", "spec_ref": "...", "operations": ["recv","process","reply","ack"], "annotation": "..."},
    {"step": "thread_handling", ...},
    {"step": "ack_nack", ...},
    {"step": "presence_heartbeat", ...},
    {"step": "graceful_stop", ...},
    {"step": "recovery", "spec_ref": "spec/protocol.md §replay", "operations": ["replay"], "annotation": "how the agent reconstructs missed messages after a context reset using the per-channel seq cursor"}
  ],
  "files": [
    {"path": "examples/reference-agent/agent.py", "spec_ref": "...", "purpose": "fully-annotated reference impl", "public_api": [...]},
    {"path": "examples/reference-agent/README.md", "purpose": "prose walkthrough"},
    {"path": "examples/reference-agent/run_standalone.sh", "purpose": "quick-start"},
    {"path": "examples/reference-agent/.claude-agent.md", "purpose": "Claude Code agent definition"},
    {"path": "examples/reference-agent/tests/test_agent.py", "purpose": "pytest integration tests for each lifecycle step"}
  ],
  "test_plan": [
    {"spec_section": "...", "test_cases": ["agent recovers after kill -9", "agent refuses stop with unreplied", "agent threads correctly"]}
  ],
  "annotation_density": "every protocol concept gets an inline comment block; aim for 1 comment line per 3 code lines",
  "risks": [...],
  "dependencies": [...],
  "build_order": ["agent.py skeleton","each lifecycle step","tests","README walkthrough","run scripts"],
  "exit_signals": [
    "100% coverage on agent.py logic",
    "Integration test: agent + partner exchange a thread successfully",
    "Standalone run completes in <30s",
    "README walkthrough mirrors lifecycle[]"
  ]
}

CONSTRAINTS:
- Agent must be runnable both as standalone Python script (no Claude Code) and as a Claude Code agent.
- Annotation density is high — this is a teaching artifact.
- Every primitive in spec/primitives/ should appear at least once in the lifecycle.

END YOUR REPORT WITH A RESERVATIONS BLOCK.

The orchestrator extracts this block to gate parallel dispatch of the downstream 02-build phase. After your prose REPORT, output (no other text after):

RESERVATIONS:
- <path>
- <path>
END_RESERVATIONS

Rules:
- One path per line, prefixed with `- `
- Plain string paths, no globs, no quotes
- The list MUST be byte-identical to the set of paths in plan.files[].path

REPORT: lifecycle step count, file count, annotation density target. Then the RESERVATIONS block.
```

## Exit criteria

Universal (`planning`):
- [ ] `test -f .workflow/plans/reference-agent/implementation-plan.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/reference-agent/implementation-plan.json')); assert all(k in p for k in ['summary','lifecycle','files','test_plan','exit_signals'])"`
- [ ] `test -f .workflow/plans/reference-agent/reservations/02-build.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/reference-agent/implementation-plan.json')); r=json.load(open('.workflow/plans/reference-agent/reservations/02-build.json')); assert set(f['path'] for f in p['files']) == set(r['files']), 'reservations do not match files'"`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/reference-agent/implementation-plan.json')); ops=set(op for step in p['lifecycle'] for op in step.get('operations',[])); required={'send','recv','subscribe','unsubscribe','list_channels','channels__ack','channels__heartbeat','replay','group_create','group_invite','group_join','group_leave','group_list_members','list_agents'}; missing=required-ops; assert not missing, f'lifecycle missing v1 operations: {missing}'"`

## Outputs

- `.workflow/plans/reference-agent/implementation-plan.json`

## Next state

Promote `02-build` → READY.
