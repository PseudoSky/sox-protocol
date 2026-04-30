---
slug: orchestrator-bootstrap
target: workflow-lint tool, orchestrator system prompt, and SOX hook opt-out for orchestrator sessions all shipped.
created: 2026-04-30
last_event: 2026-04-30T00:00:00Z
orchestrator_protocol: v1
---

# orchestrator-bootstrap — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-bootstrap | Build lint tool, system prompt, hook opt-out | `READY` | python-pro | 0 | 2026-04-30T00:00:00Z |

## Currently next action

`01-bootstrap` is `READY`. **Run this engagement FIRST** before advancing any other engagement. It produces tools the orchestrator needs.

## Transitions

- 2026-04-30T00:00:00Z 01-bootstrap — initialized (READY)

## Termination targets

- [ ] Phase DONE
- [ ] `tools/workflow_lint.py` exists and runs cleanly against current `.workflow/`
- [ ] `tools/orchestrator_prompt.md` exists
- [ ] SOX hooks honor `SOX_ORCHESTRATOR_MODE=1`
- [ ] CI gate added for `workflow_lint`
