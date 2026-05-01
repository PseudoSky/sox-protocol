---
phase_id: 01-plan
title: Component tree + state plan
agent: sox-cto-system:planner
profile: planning
estimated_effort: 2-3 hours
prereqs: []
unblocks: [02-build]
parallelizable_with: []
writes: [".workflow/plans/chat-webapp/implementation-plan.json"]
reads:  ["spec/**", "docs/decisions/webapp-deployment-model.md"]
context_size: medium
---

# 01 — Plan

## Inputs

- `spec/protocol.md`, `spec/primitives/`
- `spec/transports/http/openapi.yaml` (the wire)
- `docs/decisions/webapp-deployment-model.md` (stack + deployment already decided)

## Prompt (verbatim)

```text
JSON plan for the SOX Protocol web app.

READ:
- spec/protocol.md, spec/primitives/
- spec/transports/http/openapi.yaml
- docs/decisions/webapp-deployment-model.md (AUTHORITATIVE — stack and deployment model are already decided; do not re-open these choices)
- .workflow/plans/chat-webapp/phases/02-build.md (downstream build phase — read it so your component tree paths, CLI subcommand integration, and feature-flag scoping match what the builder expects)

OUTPUT: /Users/nix/dev/ai/sox-protocol/.workflow/plans/chat-webapp/implementation-plan.json

SHAPE:
{
  "summary": "...",
  "stack": {"framework": "React 18 + Vite (decided — docs/decisions/webapp-deployment-model.md)", "state": "<Zustand|Jotai|TanStack Query — choose one>", "styling": "<Tailwind|CSS Modules — choose one>"},
  "deployment": {
    "model": "Static SPA bundled into Python wheel; served by sox HTTP transport at /ui/ (decided — docs/decisions/webapp-deployment-model.md)",
    "distribution": ["npm package @sox-protocol/ui for standalone/CDN use", "packages/python/src/sox_protocol/ui/static/ bundled into wheel"],
    "rationale": "See docs/decisions/webapp-deployment-model.md"
  },
  "component_tree": [
    {"component": "App", "children": ["ChannelSidebar","MessageThread","AgentPanel","ComposeBar"]},
    {"component": "ChannelSidebar", "props": [...], "state": [...], "spec_ref": "spec/primitives/channels.md"},
    ...
  ],
  "files": [{"path": "packages/ui/src/...", "spec_ref": "...", "purpose": "...", "public_api": [...]}],
  "feature_flags": {
    "graph_view": "force-directed agent/message graph; gate behind flag",
    "replay_mode": "history scrubber; gate until replay API is shipped"
  },
  "cli_subcommand": {
    "name": "sox ui",
    "behavior": "start HTTP transport on free port, open browser, serve built static assets bundled with python package"
  },
  "test_plan": [...],
  "risks": [
    {"risk": "static + CORS", "mitigation": "HTTP transport advertises permissive CORS for localhost dev"},
    {"risk": "auth in browser", "mitigation": "credential entered on connect, stored in sessionStorage only"}
  ],
  "dependencies": [...],
  "build_order": [...],
  "exit_signals": [
    "tsc --strict clean",
    "100% coverage on logic (excluding pure rendering)",
    "Lighthouse performance ≥ 80, a11y ≥ 95",
    "Static bundle deployable",
    "sox ui CLI works end-to-end"
  ]
}

END YOUR REPORT WITH A RESERVATIONS BLOCK.

The orchestrator extracts this block to gate parallel dispatch of the downstream 02-build phase. After your prose REPORT, output (no other text after):

RESERVATIONS:
- <path>
- <path>
END_RESERVATIONS

Rules:
- One path per line, prefixed with `- `
- Plain string paths, no globs, no quotes
- The list MUST equal plan.files[].path. Include CLI subcommand modifications (packages/python/src/sox_protocol/cli/) and bundled-asset directory (packages/python/src/sox_protocol/ui/static/).

REPORT: stack choice + rationale, component count, deployment target. Then the RESERVATIONS block.
```

## Exit criteria

Universal (`planning`):
- [ ] `test -f .workflow/plans/chat-webapp/implementation-plan.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/chat-webapp/implementation-plan.json')); assert all(k in p for k in ['summary','stack','deployment','component_tree','files','test_plan','exit_signals'])"`
- [ ] `test -f .workflow/plans/chat-webapp/reservations/02-build.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/chat-webapp/implementation-plan.json')); r=json.load(open('.workflow/plans/chat-webapp/reservations/02-build.json')); assert set(f['path'] for f in p['files']) == set(r['files']), 'reservations do not match files'"`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/chat-webapp/implementation-plan.json')); assert p['stack']['framework'].startswith('React 18'), 'stack framework must be React 18 + Vite (decided)'"` 

## Outputs

- `.workflow/plans/chat-webapp/implementation-plan.json`

## Next state

Promote `02-build` → READY.
