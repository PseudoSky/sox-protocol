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
| 02-build | Build TUI + demo script + recording | `DONE` | python-pro | 1 | 2026-05-01T12:13:00Z |

## Currently next action

`02-build` is `DONE`. Engagement complete.

## Transitions

- 2026-05-01T12:13:00Z 02-build — DONE (python-pro + inline cleanup): TUI shipped, 131 tests / 100% cov, mypy --strict clean, ruff clean, lint-imports kept. Real recordings: `docs/media/demo.gif` (62 KB, vhs) + `docs/media/demo.cast` (asciinema). Build agent truncated mid-cleanup; remaining 16 mypy + 5 ruff issues fixed inline (state.py JSON deserialization casts, widgets `**kwargs: Any` w/ ANN401 noqa, `_heartbeat_loop` contextlib.suppress refactor, mcp_client `process: ServerProcess | None` typed via TYPE_CHECKING, return-shape narrowing in `_call`).

## Termination targets

- [x] Both phases DONE
- [x] `sox chat` CLI subcommand works (`python -m sox_protocol.cli chat --help`)
- [x] `examples/two-agents-talking/` runnable (demo.py completes ≤ 60s)
- [x] `docs/media/demo.gif` (real, 62 KB, 120×40, generated via `vhs examples/two-agents-talking/demo.tape`) embedded in README
- [x] `docs/media/demo.cast` (real asciinema recording, 2.4 KB)
- [x] 100% coverage on TUI logic (393/393 statements); mypy --strict clean (78 source files); lint-imports kept
