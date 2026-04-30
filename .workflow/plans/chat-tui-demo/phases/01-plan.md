---
phase_id: 01-plan
title: UI flow + textual component plan
agent: sox-cto-system:planner
profile: planning
estimated_effort: 2-3 hours
prereqs: []
unblocks: [02-build]
parallelizable_with: []
writes: [".workflow/plans/chat-tui-demo/implementation-plan.json"]
reads:  ["spec/**", "packages/python/src/**", "TODO.md"]
context_size: medium
---

# 01 — Plan

## Objective

JSON plan for the `sox chat` TUI: pane structure, components, event handlers, demo-script choreography, recording strategy.

## Inputs

- `spec/protocol.md`, `spec/primitives/` (the primitives the TUI will demonstrate)
- `packages/python/src/sox_protocol/` (existing client API the TUI will wrap)
- TODO.md §"SOX chat UI (TUI + web app)" — the TUI subsection

## Prompt (verbatim)

```text
Produce a JSON plan for the SOX Protocol `sox chat` TUI — a textual-based terminal UI that demonstrates the protocol's primitives in a 30-60s recording suitable for the README.

READ:
- spec/protocol.md, spec/primitives/ (what to demo)
- packages/python/src/sox_protocol/ (the client API)
- .workflow/plans/chat-tui-demo/phases/02-build.md (downstream build phase — read it so your component file paths, demo-script choreography, and recording-asset paths match what the builder will produce)

OUTPUT: /Users/nix/dev/ai/sox-protocol/.workflow/plans/chat-tui-demo/implementation-plan.json

SHAPE:
{
  "summary": "...",
  "ui_layout": {
    "panes": [
      {"name": "channel_list", "position": "left", "purpose": "..."},
      {"name": "message_feed", "position": "center", "purpose": "..."},
      {"name": "agent_roster", "position": "right", "purpose": "..."},
      {"name": "compose_bar", "position": "bottom", "purpose": "..."}
    ],
    "interactions": ["arrow keys to navigate", "enter to expand thread", "/reply <id>", "/dm <agent>", "/join <channel>"]
  },
  "files": [
    {"path": "packages/python/src/sox_protocol/tui/app.py", "spec_ref": "spec/primitives/channels.md", "purpose": "...", "public_api": [...]},
    ...
  ],
  "demo_script": {
    "path": "examples/two-agents-talking/demo.py",
    "choreography": [
      {"t": 0, "action": "agent A sends to #general"},
      {"t": 2, "action": "agent B replies in thread"},
      {"t": 5, "action": "agent A acks"},
      ...
    ],
    "duration_seconds": 45
  },
  "recording_strategy": {
    "tool": "asciinema | vhs | ttyrec",
    "output": "docs/media/demo.cast",
    "post_process": "vhs render to .gif for README embed",
    "rationale": "..."
  },
  "test_plan": [<TUI logic tests; rendering tests via textual.pilot>],
  "risks": [...],
  "dependencies": ["textual>=0.40", ...],
  "build_order": [...],
  "exit_signals": [
    "100% coverage on TUI logic (excluding pure-rendering glue)",
    "Demo script runs end-to-end without manual input",
    "Recording asset committed and embedded in README"
  ]
}

CONSTRAINTS:
- Use textual (Python). Ships in the existing Python package.
- Live updates via watch() — no polling.
- TUI works against current API; does not block on identity-primitive (can register credentials when available).
- The demo script must be reproducible — anyone running `examples/two-agents-talking/demo.py` should produce the same conversation.

END YOUR REPORT WITH A RESERVATIONS BLOCK.

The orchestrator extracts this block to gate parallel dispatch of the downstream 02-build phase. After your prose REPORT, output (no other text after):

RESERVATIONS:
- <path>
- <path>
END_RESERVATIONS

Rules:
- One path per line, prefixed with `- `
- Plain string paths, no globs, no quotes
- The list MUST be byte-identical to the set of paths in plan.files[].path PLUS the demo-script and recording-asset paths
- Include the README.md if you anticipate the build phase will edit it (you should — to embed the demo asset)

REPORT: pane count, component file count, demo duration, recording tool choice + rationale. Then the RESERVATIONS block.
```

## Exit criteria

Universal (`planning`):
- [ ] `test -f .workflow/plans/chat-tui-demo/implementation-plan.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/chat-tui-demo/implementation-plan.json')); assert all(k in p for k in ['summary','ui_layout','files','demo_script','recording_strategy','test_plan','exit_signals'])"`
- [ ] `test -f .workflow/plans/chat-tui-demo/reservations/02-build.json`

## Outputs

- `.workflow/plans/chat-tui-demo/implementation-plan.json`

## Next state

Promote `02-build` → READY.
