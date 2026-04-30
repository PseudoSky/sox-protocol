---
slug: http-transport
target: HTTP transport adapter shipped, satisfying the Transport port. SSE/WebSocket for live recv. OpenAPI spec generated. Conformance suite passes against HTTP transport identically to stdio.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# http-transport — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Port + OpenAPI plan | `READY` | sox-cto-system:planner | 0 | 2026-04-29T00:00:00Z |
| 02-build | Build adapter + serve subcommand | `BLOCKED` | python-pro | 0 | 2026-04-29T00:00:00Z |
| 03-conformance | Run conformance against HTTP | `BLOCKED` | test-automator | 0 | 2026-04-29T00:00:00Z |

## Currently next action

`01-plan` is `READY`.

## Termination targets

- [ ] All phases DONE
- [ ] `packages/python/src/sox_protocol/adapters/transports/http/` shipping
- [ ] `sox serve --transport http` works
- [ ] `spec/transports/http/openapi.yaml` generated
- [ ] Conformance suite passes against HTTP target identically to stdio
