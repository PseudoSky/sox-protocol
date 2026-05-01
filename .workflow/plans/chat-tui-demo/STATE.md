---
slug: chat-tui-demo
target: `sox chat` TUI shipped. 30-60 second demo recording embedded in README. Two-agent demo script bundled. The pitch artifact for v1 launch.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# chat-tui-demo — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | UI flow + textual component plan | `DONE` | sox-cto-system:planner | 1 | 2026-04-30T00:00:00Z |
| 02-build | Build TUI + demo script + recording | `READY` | python-pro | 0 | 2026-04-30T00:00:00Z |

## Currently next action

`02-build` is `READY`. Spawn `python-pro`.

## Termination targets

- [ ] Both phases DONE
- [ ] `sox chat` CLI subcommand works
- [ ] `examples/two-agents-talking/` runnable
- [ ] `docs/media/demo.gif` (or .cast / .mp4) embedded in README
- [ ] 100% coverage on TUI logic; mypy --strict; lint-imports clean
