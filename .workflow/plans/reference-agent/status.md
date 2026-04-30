---
slug: reference-agent
state: initialized
bucket: pitch+implementation
stream: C
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: high
unblocks: []
depends_on: []
soft_depends_on: [spec-extraction]
---

# Engagement: reference-agent

## Objective
Ship a fully-annotated canonical reference agent — the copy-paste artifact most adopters will start from. Demonstrates every protocol primitive end-to-end.

## Acceptance criteria
- [ ] `examples/reference-agent/` directory with a runnable Python agent
- [ ] Demonstrates: subscribe-on-startup, recv loop, threading via `reply_to`, ACK/NACK, graceful stop with unreplied check, heartbeat/presence
- [ ] Includes `bootstrap()` helper showing the prescribed startup sequence (subscribe → list_agents → list_pending → drain unreplied)
- [ ] Demonstrates recovery: shows how to use `list_pending` and replay to reconstruct state after a context reset
- [ ] Runnable both as a standalone script and as a Claude Code agent
- [ ] Heavily commented — every protocol concept is explained inline as a teaching artifact
- [ ] Companion `README.md` walks through the agent's lifecycle in prose
- [ ] Integration test in CI: spins up reference agent + a partner, runs a scripted exchange, verifies expected messages

## Inputs
- Current Python client SDK
- Spec for primitives (soft dep on spec-extraction; can be retrofitted)
- TODO.md §"reference agent"

## Outputs
- `examples/reference-agent/`
- CI integration test

## Suggested executor
`python-pro`.

## State transitions
- 2026-04-29 initialized — workflow-architect
