---
phase_id: 01-plan
title: Port + OpenAPI plan
agent: sox-cto-system:planner
profile: planning
estimated_effort: 2-3 hours
prereqs: []
unblocks: [02-build]
parallelizable_with: []
writes: [".workflow/plans/http-transport/implementation-plan.json"]
reads:  ["spec/**", "packages/python/src/**"]
context_size: medium
---

# 01 — Plan

## Inputs

- `spec/ports/transport.md` (output of spec-extraction — the contract)
- `spec/operations/*.json` (the schemas to expose)
- `packages/python/src/sox_protocol/adapters/transports/stdio/` (the existing transport — model after)

## Prompt (verbatim)

```text
JSON plan for the SOX Protocol HTTP transport adapter.

READ:
- spec/ports/transport.md (the port contract)
- spec/operations/*.json (operation schemas)
- packages/python/src/sox_protocol/adapters/transports/stdio/ (existing model)
- .workflow/plans/http-transport/phases/02-build.md (downstream build phase — read it so your file paths, wire_format choice, OpenAPI generation strategy, and CLI subcommand shape match what the builder expects)

OUTPUT: /Users/nix/dev/ai/sox-protocol/.workflow/plans/http-transport/implementation-plan.json

SHAPE:
{
  "summary": "...",
  "files": [{"path": "...", "spec_ref": "spec/ports/transport.md §...", "purpose": "...", "public_api": [...]}],
  "wire_format": {
    "request_response": "JSON over HTTP POST per operation",
    "live_recv": "SSE | WebSocket — chosen: <pick> with rationale",
    "auth": "Authorization: Bearer <credential> per identity primitive"
  },
  "openapi": {
    "path": "spec/transports/http/openapi.yaml",
    "generation": "from spec/operations/*.json schemas via codegen at tools/openapi_gen.py"
  },
  "cli_subcommand": {
    "name": "sox serve --transport http",
    "env_vars": ["SOX_MCP_TRANSPORT", "SOX_HTTP_HOST", "SOX_HTTP_PORT"]
  },
  "test_plan": [...],
  "risks": [...],
  "dependencies": ["fastapi","uvicorn","sse-starlette"],
  "build_order": [...],
  "exit_signals": [
    "100% coverage on http transport",
    "Conformance suite passes against HTTP target",
    "OpenAPI generated and valid",
    "CORS configurable",
    "Health endpoint at GET /health"
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
- The list MUST equal plan.files[].path. Include CLI subcommand files (modifications to packages/python/src/sox_protocol/cli/), OpenAPI spec, and codegen tool if used.

REPORT: file count, wire-format choice rationale, dependency list. Then the RESERVATIONS block.
```

## Exit criteria

Universal (`planning`):
- [ ] `test -f .workflow/plans/http-transport/implementation-plan.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/http-transport/implementation-plan.json')); assert all(k in p for k in ['summary','files','wire_format','openapi','cli_subcommand','test_plan','exit_signals'])"`
- [ ] `test -f .workflow/plans/http-transport/reservations/02-build.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/http-transport/implementation-plan.json')); r=json.load(open('.workflow/plans/http-transport/reservations/02-build.json')); assert set(f['path'] for f in p['files']) == set(r['files'])"`

## Outputs

- `.workflow/plans/http-transport/implementation-plan.json`

## Next state

Promote `02-build` → READY.
