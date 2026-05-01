---
slug: conformance-suite
target: Language-agnostic conformance test fixtures + harness. Python reference impl passes the suite in CI. Suite is the artifact future Rust/TS implementations register against.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# conformance-suite — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Test plan from spec | `IN_PROGRESS` | sox-cto-system:planner | 1 | 2026-04-30T00:00:00Z |
| 02-build | Build fixtures + harness + CI | `BLOCKED` | test-automator | 0 | 2026-04-29T00:00:00Z |

## Currently next action

`01-plan` is `IN_PROGRESS` (parallel batch 2026-04-30T00:00:00Z).

## Termination targets

- [ ] Both phases DONE
- [ ] `spec/conformance/` has fixtures covering: send/recv, subscriptions, threading, groups, DMs, ACK/NACK, identity verification, sequence numbers
- [ ] `tools/conformance_runner.py` runs against Python reference impl with all fixtures green
- [ ] CI workflow runs the harness on every PR
- [ ] README in `spec/conformance/` explains how a third-party impl registers
