---
slug: http-transport
state: initialized
bucket: implementation
stream: E
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: medium
unblocks: [ts-sdk, chat-webapp]
depends_on: [spec-extraction]
soft_depends_on: [identity-primitive]
---

# Engagement: http-transport

## Objective
Ship the HTTP transport adapter satisfying the Transport port. Required for any non-stdio client (browsers, remote agents, the webapp). Validates that the transport-port abstraction actually works for a second binding.

## Acceptance criteria
- [ ] `packages/python/src/sox_protocol/adapters/transports/http/` implements the Transport port
- [ ] Selectable via `SOX_MCP_TRANSPORT=http` env var; standardized `SOX_HTTP_HOST`, `SOX_HTTP_PORT`
- [ ] Wire format: JSON over HTTP for request/response operations; Server-Sent Events or WebSocket for `watch()` / live `recv()`
- [ ] CORS configurable for browser clients
- [ ] Identity middleware integrated (auth header → credential check)
- [ ] Health endpoint (`GET /health`)
- [ ] OpenAPI spec generated from operation schemas (reuses spec-extraction JSON Schemas)
- [ ] Conformance suite passes against HTTP transport identically to stdio
- [ ] Local-dev launch story: `sox serve --transport http --port 8765` documented
- [ ] CI runs the conformance suite against both stdio and http

## Inputs
- Transport port spec (output of spec-extraction)
- Operation JSON schemas (output of spec-extraction)
- Identity middleware (output of identity-primitive; soft-dep — can ship without and add later)

## Outputs
- HTTP adapter code
- OpenAPI spec at `spec/transports/http/openapi.yaml`
- `sox serve --transport http` CLI subcommand
- CI matrix update

## Suggested executor
`backend-developer` or `python-pro`.

## State transitions
- 2026-04-29 initialized — workflow-architect
