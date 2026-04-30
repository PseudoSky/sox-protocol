---
slug: reference-agent
target: Canonical reference agent shipped at examples/reference-agent/. Demonstrates every protocol primitive end-to-end. Heavily commented as a teaching artifact. The copy-paste starting point for adopters.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# reference-agent — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Lifecycle plan from spec primitives | `READY` | sox-cto-system:planner | 0 | 2026-04-29T00:00:00Z |
| 02-build | Build agent + tests + walkthrough | `BLOCKED` | python-pro | 0 | 2026-04-29T00:00:00Z |

## Currently next action

`01-plan` is `READY`.

## Termination targets

- [ ] Both phases DONE
- [ ] `examples/reference-agent/` runnable as standalone script and as Claude Code agent
- [ ] Demonstrates: subscribe-on-startup, recv loop, threading, ACK/NACK, graceful stop with unreplied check, heartbeat
- [ ] Includes `bootstrap()` helper showing the prescribed startup sequence
- [ ] Companion README walks through the lifecycle in prose
- [ ] CI integration test exercises the agent against a partner
