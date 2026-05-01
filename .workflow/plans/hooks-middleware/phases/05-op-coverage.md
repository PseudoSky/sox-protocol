---
phase_id: 05-op-coverage
title: Widen Operation literal + StoreDispatch op-table; cover terminal
agent: python-pro
profile: code-with-spec
estimated_effort: 0.5-1 day
prereqs: [03-implement]
unblocks: [04-review]
parallelizable_with: [identity-primitive:05-spec-realignment]
writes: ["packages/python/src/sox_protocol/core/middleware/**", "packages/python/tests/middleware/**"]
reads:  ["spec/ports/middleware.md", "spec/operations/*.input.schema.json", ".workflow/plans/SALVAGE-AUDIT-2026-04-30.md"]
context_size: small
---

# 05 — Op coverage (salvage)

## Inputs

- `spec/ports/middleware.md` (unchanged since plan — architecture is sound)
- `spec/operations/list_agents.input.schema.json` + the channels__/group__ op schemas
- Current `packages/python/src/sox_protocol/core/middleware/{context,default_chain,plugins/store_dispatch}.py`
- `.workflow/plans/SALVAGE-AUDIT-2026-04-30.md`

## Background

Step 3 shipped at commit `e33d0f2` (83/83, 100% cov). Middleware port spec is stable; this is **light remediation only** — do not change the pipeline architecture, mutability rules, or default chain ordering.

## Prompt (verbatim)

```text
Apply three small remediations to the shipped middleware framework. Read SALVAGE-AUDIT-2026-04-30.md for context.

DELIVER:

1. Widen Operation literal in core/middleware/context.py
   - Current literal lists 8 ops; extend to include every v1 MUST op per current spec:
     send, recv, subscribe, unsubscribe, list_channels, list_agents,
     channels_ack, channels_heartbeat, channels_collect, replay,
     group_create, group_invite, group_join, group_leave, group_list_members
   - Source of truth: enumerate spec/operations/*.input.schema.json filenames.
   - Update any switch-on-Operation type-narrowing sites; mypy must remain --strict clean.

2. Extend StoreDispatchMiddleware op-table
   - core/middleware/plugins/store_dispatch.py currently dispatches send/recv/subscribe/list_channels.
   - Add dispatch entries for: unsubscribe, list_agents, channels_ack, channels_heartbeat, channels_collect, replay, group_create, group_invite, group_join, group_leave, group_list_members.
   - Each entry: validate input is dict-shaped, call store.<op>(**input), return store result OR map domain exceptions to sox-error envelopes (validation_error, channel_not_found, etc.).
   - Working-tree diff already adapts to the 3-tuple store.send signature — preserve that adaptation.

3. Cover _StoreTerminal
   - default_chain.py:44-60 has `# pragma: no cover` on _StoreTerminal.
   - Remove the pragma. Add direct unit tests in tests/middleware/test_default_chain.py that exercise the terminal adapter for each op the dispatch covers.
   - Aim for genuine 100% coverage (no pragma escape).

HARD CONSTRAINTS:
- All existing 83 middleware tests still pass.
- 100% coverage on core/middleware/ — no pragmas added.
- mypy --strict clean (Operation literal change must propagate cleanly).
- lint-imports clean.
- ruff clean.

DO NOT:
- Touch pipeline.py reentrancy or context mutability rules.
- Change default chain ordering (auth → store_dispatch terminal).
- Implement schema_validator middleware here — that's a separate engagement.
- Implement rate_limit, idempotency, audit_log middlewares — those are separate engagements.

EXIT CRITERIA:
- pytest packages/python/tests/middleware/ → all green
- coverage report shows 100% on core/middleware/ with no pragmas
- mypy --strict packages/python/src/sox_protocol/core/middleware/ → 0 errors
- grep -c "list_agents" packages/python/src/sox_protocol/core/middleware/context.py → ≥1
- grep -c "channels_ack" packages/python/src/sox_protocol/core/middleware/plugins/store_dispatch.py → ≥1

ON COMPLETION:
- Mark 05-op-coverage DONE in STATE.md
- Promote 04-review to READY
- Commit with trailer: feat(hooks-middleware:05-op-coverage)
```

## Acceptance criteria (machine-checkable)

- [ ] `Operation` literal in `context.py` enumerates all 15 v1 ops
- [ ] `StoreDispatchMiddleware` switch covers all 15 ops
- [ ] No `# pragma: no cover` lines in `core/middleware/`
- [ ] `pytest packages/python/tests/middleware/ -v` green
- [ ] `coverage run -m pytest packages/python/tests/middleware/ && coverage report` shows 100% on `core/middleware/`
