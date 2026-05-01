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
      "fixture_type": "happy | failure | boundary",
      "error_code": "<sox error code if fixture_type=failure and expects a sox-error response, else omit>",
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
- backpressure
- idempotency
- subscribe-enforcement
- error-envelopes
- version-negotiation

EXISTING FIXTURES: 27 files already committed under spec/conformance/. Audit each one, keep it if correct, flag it if it needs updating. Do NOT duplicate — only add what is missing.

MANDATORY FAILURE COVERAGE — the plan MUST include at least one fixture for each item below. "At least one failure-mode per category" is NOT sufficient. Plan each of the following explicitly:

Error codes (spec/envelopes/sox-error.schema.json — all 9 codes must be triggered and the response envelope validated):
- identity_failure — unknown or invalid credential
- channel_not_found — recv or send to non-existent channel
- subscription_not_found — recv without prior subscribe
- validation_error — body not a JSON object, required field missing
- rate_limited — if rate limiting is implemented; else mark as future
- store_unavailable — backing store error path
- version_mismatch — _sox_protocol supported_versions does not intersect client range
- backpressure_over_limit — enforced backpressure mode, queue at limit
- internal_error — unexpected server error path

Reserved-prefix enforcement (from subscribe-enforcement and dms and groups categories):
- subscribe with pattern "dm/*" rejected (not/anyOf constraint)
- subscribe with pattern "group/*" rejected (not/anyOf constraint)
- send to "sox/any-channel" rejected (agents cannot write sox/ channels)
- send to dm/<pair> by a non-member agent rejected
- send to group/<id> by a non-member agent rejected

Backpressure:
- advisory mode: send response contains backpressure.state=warn when queue depth approaches threshold
- advisory mode: send response contains backpressure.state=over but send still succeeds
- enforced mode: send returns backpressure_over_limit error when queue at limit

Idempotency:
- duplicate send with same idempotency_key within TTL returns original message_id without creating new message
- send with same key after TTL expiry creates a new message (idempotency window closed)

Threading (thread_depth parameter):
- recv with thread_depth=0 returns reply_to IDs only, no ancestors field populated
- recv with thread_depth=1 returns immediate parent inlined in ancestors
- recv with thread_depth=-1 returns full ancestor chain
- ancestor envelopes contain all required fields: channel, sender, body, sent_at, message_id, seq

Observability:
- include_meta=true: _meta present with correct shape {trace_id: string, middleware_timings: string[], server_node_id: string}
- include_meta=false: _meta absent from all returned messages
- middleware_timings items are strings in "name:duration" format

Delivered-to tracking:
- delivered_to populated (non-null array) after at least one agent has recv'd the message
- delivered_to null (or empty) before any agent has recv'd

Version negotiation:
- list_channels response contains _sox_protocol block with server_version, supported_versions, min_client_version
- client whose supported version range does not intersect server range receives version_mismatch error

Collect:
- collect returns partial result with timed_out=true when fewer than requested replies arrive within timeout
- collect returns received[] and missing[] arrays correctly on partial completion

Sequence monotonicity (cross-channel):
- seq is per-channel, not global: two channels each start at seq=1 independently

Schema validation:
- send to a typed channel (channel with a registered JSON Schema) with non-conforming body returns validation_error
- send to a typed channel with conforming body succeeds

FOR EACH FIXTURE: assign "fixture_type": "happy" | "failure" | "boundary" in the plan JSON so coverage is machine-auditable.

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
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/conformance-suite/implementation-plan.json')); assert all('spec_ref' in f for f in p['fixtures']), 'fixture missing spec_ref'"`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/conformance-suite/implementation-plan.json')); assert all('fixture_type' in f for f in p['fixtures']), 'fixture missing fixture_type'"`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/conformance-suite/implementation-plan.json')); failures=[f for f in p['fixtures'] if f['fixture_type']=='failure']; assert len(failures)>=20, f'only {len(failures)} failure fixtures — mandatory coverage requires ≥20'"`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/conformance-suite/implementation-plan.json')); codes={f.get('error_code') for f in p['fixtures'] if f.get('fixture_type')=='failure' and f.get('error_code')}; required={'identity_failure','channel_not_found','subscription_not_found','validation_error','version_mismatch','backpressure_over_limit'}; missing=required-codes; assert not missing, f'missing error_code fixtures: {missing}'"`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/conformance-suite/implementation-plan.json')); cats={f['path'].split('/')[2] for f in p['fixtures']}; required={'backpressure','idempotency','subscribe-enforcement','error-envelopes','version-negotiation'}; missing=required-cats; assert not missing, f'missing categories: {missing}'"`
- [ ] `test -f .workflow/plans/conformance-suite/reservations/02-build.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/conformance-suite/implementation-plan.json')); r=json.load(open('.workflow/plans/conformance-suite/reservations/02-build.json')); assert set(f['path'] for f in p['files']) == set(r['files'])"`

## Outputs

- `.workflow/plans/conformance-suite/implementation-plan.json`

## Next state

Promote `02-build` → READY.
