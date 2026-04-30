---
slug: ts-sdk
state: initialized
bucket: implementation
stream: E
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: medium
unblocks: [chat-webapp]
depends_on: [spec-extraction, http-transport]
---

# Engagement: ts-sdk

## Objective
TypeScript client SDK — `@sox-protocol/client` on npm. Mirrors the Python SDK shape with typed request/response objects generated from the spec's JSON schemas. Required for any browser-based or Node-based agent (and for the webapp).

## Acceptance criteria
- [ ] `packages/typescript/` workspace set up (npm or pnpm), TS strict mode
- [ ] Low-level client: `send()`, `recv()`, `subscribe()`, `listChannels()`, `listAgents()`, `listPending()`, `listGroups()`
- [ ] Typed request/response shapes generated from `spec/operations/*.json` (codegen step in `tools/`)
- [ ] Higher-level helpers: `askAndWait(channel, body, timeout)`, `reply(messageId, body)`, `drain()`, `bootstrap()`
- [ ] Browser + Node compatible (ESM build, CJS build, type definitions)
- [ ] Connects to HTTP transport; SSE/WebSocket for live `watch()`
- [ ] Auth integration: agent credential set at construction; injected into transport headers
- [ ] Test coverage: unit tests + integration tests against running Python server (HTTP transport)
- [ ] Conformance suite passes when `tools/conformance_runner` is pointed at a TS-implemented test harness (proves the spec is portable beyond Python)
- [ ] Published to npm as `@sox-protocol/client` (or chosen scope) with semver alignment to Python package
- [ ] README with quickstart, type examples, contrast vs. Python SDK

## Inputs
- Operation JSON Schemas + envelope schemas (output of spec-extraction)
- HTTP transport (output of http-transport)
- Conformance fixtures (for cross-impl validation)

## Outputs
- `packages/typescript/`
- npm package
- Codegen tool in `tools/`

## Suggested executor
`typescript-pro`.

## State transitions
- 2026-04-29 initialized — workflow-architect
