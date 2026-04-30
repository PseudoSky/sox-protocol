---
slug: chat-tui-demo
state: initialized
bucket: pitch+implementation
stream: C
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: critical
unblocks: [launch-narrative]
depends_on: []
---

# Engagement: chat-tui-demo

## Objective
Build the `sox chat` TUI — the 30-second demo that sells the entire pitch. Multi-pane terminal interface showing channels, threads, agents, presence, ACK/NACK status, all updating in real time as agents talk to each other.

## Acceptance criteria
- [ ] `sox chat` CLI subcommand launches the TUI
- [ ] Built with `textual` (Python); ships in the existing Python package
- [ ] Panes: channel list (left), message feed (center, live-tailing), thread view (expandable), agent roster with presence (right)
- [ ] Compose bar with `/reply <id>`, `/dm <agent>`, `/join <channel>`
- [ ] Live updates via `watch()` — no polling
- [ ] Ships with an `examples/two-agents-talking/` script that spawns 2-3 demo agents the user can connect to
- [ ] 30-60 second screen recording of the demo committed to `docs/media/demo.gif` (or hosted) and embedded in README
- [ ] Works against current API surface (does not block on identity-primitive resolution; can be retrofitted with credentials later)

## Inputs
- Current Python client API
- TODO.md §"SOX chat UI (TUI + web app)" — TUI subsection

## Outputs
- `packages/python/src/sox_protocol/tui/`
- `sox chat` CLI subcommand
- `examples/two-agents-talking/`
- Screen recording in `docs/media/`

## Suggested executor
`python-pro` (textual is Python). Optionally `ui-designer` consult for layout.

## State transitions
- 2026-04-29 initialized — workflow-architect
