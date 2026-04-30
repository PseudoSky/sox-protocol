---
slug: orchestrator-bootstrap
state: initialized
bucket: meta
stream: 0
created: 2026-04-30
last_event: 2026-04-30T00:00:00Z
priority: critical
milestone: v1
unblocks: []
soft_unblocks: [bucket-classification, spec-extraction, identity-primitive, hooks-middleware, conformance-suite, chat-tui-demo, reference-agent, defensive-publication, launch-narrative, http-transport, ts-sdk, chat-webapp]
depends_on: []
note: "Run first. Provides workflow-lint, orchestrator system prompt, and SOX hook opt-out for orchestrator sessions."
---

# Engagement: orchestrator-bootstrap

## Objective

Ship the orchestrator's tooling: a workflow-lint validator, an orchestrator-mode system prompt that enforces the contracts, and a SOX hook opt-out so orchestrator sessions aren't drowned in `mcp__sox__channels__recv` reminders during exit-criterion bash invocations.

## Acceptance criteria

- [ ] `tools/workflow_lint.py` runs against `.workflow/` and validates cross-references
- [ ] `tools/orchestrator_prompt.md` exists, loads templates as system context for orchestrator sessions
- [ ] `tools/sox-hooks/post_tool_use.sh` and `stop.sh` honor `SOX_ORCHESTRATOR_MODE=1` env (exit 0 immediately)
- [ ] CI runs `workflow_lint` on every PR that touches `.workflow/`
- [ ] 100% coverage on `workflow_lint` Python code

## Suggested executor

`python-pro` (single phase — code, prose, shell tweaks all fit one specialist)

## State transitions
- 2026-04-30 initialized — workflow-architect
