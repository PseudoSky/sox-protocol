---
phase_id: 05-list-agents-port-migration
title: Migrate list_agents from LivenessStore to BackingStore port
agent: python-pro
profile: code-with-spec
estimated_effort: 0.5-1 day
prereqs: [04-spec-realignment]
unblocks: [03-conformance]
parallelizable_with: []
writes: ["packages/python/src/sox_protocol/adapters/transports/http/**", "packages/python/src/sox_protocol/core/ports/backing_store.py", "packages/python/src/sox_protocol/adapters/backing_stores/**", "packages/python/tests/**"]
reads:  ["spec/ports/backing-store.md", "spec/operations/list_agents.*.schema.json", ".workflow/plans/SALVAGE-AUDIT-2026-04-30.md"]
context_size: small
---

# 05 — list_agents port migration (salvage follow-up)

## Inputs

- `spec/ports/backing-store.md` (ground truth — presence/liveness lives here per `3bdafc2` realignment)
- `spec/operations/list_agents.input.schema.json` + `list_agents.output.schema.json`
- Current `LivenessStore` at `packages/python/src/sox_protocol/adapters/transports/http/liveness.py`
- HTTP `op_list_agents` handler at `routes.py` (currently calls `liveness.list_agents(...)`)

## Background

`04-spec-realignment` completed 4 of 5 audit fixes; `list_agents` migration was deferred. Currently:
- `routes.py` has 8 references to `LivenessStore` and 1 import
- Heartbeat already dual-writes to BackingStore
- `list_agents` reads only from `LivenessStore` (in-memory, per-process)

This phase finishes the migration so liveness data is durable + shared across processes via the canonical port.

## Prompt (verbatim)

```text
Migrate list_agents from LivenessStore to the BackingStore port.

DELIVER:

1. Extend BackingStore port (if needed):
   - Confirm spec/ports/backing-store.md defines list_agents() returning the liveness table.
   - If the port doesn't have list_agents() yet, add it: `async def list_agents(self) -> list[AgentLivenessRecord]` per spec.
   - Add to all three adapters: memory, sqlite, filesystem. Use the heartbeat dual-write data already being persisted; if heartbeat doesn't yet write to backing-store, fix that first.

2. Rewire HTTP op_list_agents:
   - In packages/python/src/sox_protocol/adapters/transports/http/routes.py, replace `liveness.list_agents(...)` with `store.list_agents()`.
   - Remove the LivenessStore import line.
   - Remove all 8 LivenessStore references (heartbeat dual-write logic that no longer needs a second store, etc.).

3. Decide LivenessStore fate:
   - If no other module imports it: delete `liveness.py` and its tests.
   - If other modules still import it: deprecate with a docstring note pointing at BackingStore.list_agents.

4. Tests:
   - Update HTTP tests that mock LivenessStore to mock BackingStore.list_agents instead.
   - Add a backing-store port-contract test for list_agents (each adapter must satisfy it).

HARD CONSTRAINTS:
- All 184 HTTP transport tests still pass.
- Backing-store port-contract tests pass for all three adapters.
- mypy --strict, lint-imports, ruff clean.
- list_agents output shape conforms to spec/operations/list_agents.output.schema.json.

EXIT CRITERIA:
- `grep -c LivenessStore packages/python/src/sox_protocol/adapters/transports/http/routes.py` → 0
- `grep -c "store.list_agents\|store\.list_agents" packages/python/src/sox_protocol/adapters/transports/http/routes.py` → ≥1
- `python3 -m pytest packages/python/tests/transports/http/ packages/python/tests/adapters/backing_stores/` → green
- For each adapter: list_agents() returns shape conforming to spec output schema

ON COMPLETION:
- Mark 05-list-agents-port-migration DONE in STATE.md
- Promote 03-conformance to READY
- Stage all changes; do NOT commit
- Return terse report (≤300 words)
```

## Acceptance criteria (machine-checkable)

- [ ] No `LivenessStore` references in `routes.py`
- [ ] All three adapters implement `BackingStore.list_agents()`
- [ ] Output conforms to `spec/operations/list_agents.output.schema.json`
- [ ] HTTP + backing-store tests green
