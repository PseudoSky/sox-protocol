---
phase_id: 04-spec-realignment
title: Reconcile shipped HTTP transport with post-2f3d8f3 spec changes
agent: python-pro
profile: code-with-spec
estimated_effort: 1-2 days
prereqs: [02-build]
unblocks: [03-conformance]
parallelizable_with: []
writes: ["packages/python/src/sox_protocol/adapters/transports/http/**", "packages/python/tests/transports/http/**", "spec/transports/http/openapi.yaml"]
reads:  ["spec/**", "packages/python/src/sox_protocol/adapters/transports/http/**", ".workflow/plans/SALVAGE-AUDIT-2026-04-30.md"]
context_size: medium
---

# 04 — Spec realignment (salvage)

## Inputs

- `spec/ports/transport.md`
- `spec/operations/*.input.schema.json` and `*.output.schema.json`
- `spec/envelopes/sox-error.schema.json` (must include `backpressure_over_limit`)
- `spec/operations/list_agents.input.schema.json` + `list_agents.output.schema.json`
- `.workflow/plans/SALVAGE-AUDIT-2026-04-30.md` (drift evidence)

## Background

Step 4 shipped at commit `e4bea36` against an older spec. The spec then absorbed 5 changes (`9f3e11e`, `3bdafc2`, `14eb403`, `623ea90`, `ab1c954`) creating drift. This phase is **strictly remediation** — do not redesign the transport.

## Prompt (verbatim)

```text
Reconcile the shipped HTTP transport with current spec/. Read .workflow/plans/SALVAGE-AUDIT-2026-04-30.md for evidence.

DELIVER (5 fixes, in order):

1. Schema-driven input validation
   - Replace _require_fields ad-hoc checks in routes.py with JSON Schema validation against spec/operations/<op>.input.schema.json for every op endpoint.
   - On validation failure: return sox-error envelope with error_code="validation_error" and detail.violations[] per ab1c954 _meta shape.
   - Cache compiled validators at module load time.

2. Wildcard subscription rejection at transport boundary
   - In op_subscribe, reject patterns that match the not/anyOf clause of spec/operations/subscribe.input.schema.json (sox/*, group/*, dm/* root wildcards).
   - Return validation_error before forwarding to store.subscribe.

3. backpressure_over_limit emission in op_send
   - Detect store-side backpressure signal (extend BackingStore.send return type if needed; coordinate with hooks-middleware 05-op-coverage which is widening op coverage).
   - When backpressure threshold crossed, emit sox-error envelope with error_code="backpressure_over_limit" + detail.{queue_depth, threshold, mode}.
   - Replace the hard-coded `{"queue_depth":0,"threshold":1000,"state":"ok"}` block.

4. list_agents → BackingStore migration
   - Migrate op_list_agents from LivenessStore to BackingStore.list_agents() per spec realignment in 3bdafc2.
   - Heartbeat already dual-writes; complete the migration and remove the LivenessStore dependency from list_agents path.

5. channels_collect mode declaration
   - Either implement SSE/long-poll per spec/ports/transport.md §5, OR explicitly mark the current poll-loop as a documented degraded mode in spec/transports/http/openapi.yaml with a x-degraded-mode extension and a note in the route docstring.

REGENERATE:
- spec/transports/http/openapi.yaml from current spec/operations/*.json — verify parity.

HARD CONSTRAINTS:
- 100% coverage on changed paths in adapters/transports/http/
- mypy --strict
- lint-imports clean
- ruff clean
- All existing 109 tests still pass
- New tests: validation_error path per op, wildcard rejection, backpressure emission, list_agents from BackingStore
- openapi-spec-validator spec/transports/http/openapi.yaml passes

EXIT CRITERIA:
- pytest packages/python/tests/transports/http/ → all green
- grep -c backpressure_over_limit packages/python/src/sox_protocol/adapters/transports/http/*.py → ≥1
- Schema validation enforced for every op (test fixtures present)
- list_agents path no longer references LivenessStore

ON COMPLETION:
- Mark 04-spec-realignment DONE in STATE.md
- Promote 03-conformance to READY
- Commit with trailer: feat(http-transport:04-spec-realignment) per orchestrator contract
```

## Acceptance criteria (machine-checkable)

- [ ] `grep -c backpressure_over_limit packages/python/src/sox_protocol/adapters/transports/http/*.py` ≥ 1
- [ ] `grep -c "from sox_protocol.adapters.liveness" packages/python/src/sox_protocol/adapters/transports/http/routes.py` == 0
- [ ] All `op_*` handlers in `routes.py` invoke a schema validator before calling the store
- [ ] `pytest packages/python/tests/transports/http/ -v` green
- [ ] `openapi-spec-validator spec/transports/http/openapi.yaml` exits 0
- [ ] At least one test exercises wildcard subscription rejection
