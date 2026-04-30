---
slug: chat-webapp
state: initialized
bucket: pitch+implementation
stream: E
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: medium
milestone: post-v1
unblocks: []
depends_on: [ts-sdk, http-transport]
soft_depends_on: [chat-tui-demo]
---

# Engagement: chat-webapp

## Objective
React + TypeScript web app (`sox-ui`) — the public-facing showpiece demo. Lives at the project's docs site, runs against a local SOX HTTP server. Same ideas as the TUI (channels, threads, presence, ACK/NACK) rendered as a polished browser experience for visitors who won't run a terminal.

**Milestone: post-v1.** TUI is the v1 demo; webapp is a follow-on that broadens reach. Scoped here so dependencies are clear and it can dispatch when foundations are ready.

## Acceptance criteria
- [ ] `packages/ui/` workspace — React + TypeScript, Vite or Next.js, using `@sox-protocol/client`
- [ ] Channel sidebar with live unread counts; click to open; search/filter
- [ ] Thread view: nested reply chains, sender badges, ACK/NACK/pending status icons
- [ ] Agent panel: roster with presence dots, last-seen timestamps, pending counts; click to open DM
- [ ] Compose with `/reply`, `/dm`, `/join`; markdown body support
- [ ] Live updates via `watch()` over SSE/WebSocket — no polling
- [ ] Optional conversation graph view: force-directed graph of agents and message edges; `trace_id` highlighted as subgraph
- [ ] Replay mode: scrub channel history with pause/play (uses replay API once shipped; gate behind a feature flag if replay isn't ready)
- [ ] Auth: credential entered on connect; passed via HTTP transport headers
- [ ] Static-build deployable (Vercel/Cloudflare/GitHub Pages); also `sox ui` CLI subcommand that boots HTTP transport and opens browser
- [ ] Demo recording (60-90s) for project site landing page
- [ ] Lighthouse score acceptable; basic a11y (keyboard nav, ARIA labels)

## Open architect questions
- Static site vs. thin Node proxy? Static is simpler to ship and deploy on a CDN; proxy can avoid CORS gotchas and add session auth. **Lean: static, with HTTP transport advertising permissive CORS for `localhost` dev.**
- Bundle the webapp with the Python package (so `pip install sox-protocol` ships the UI assets and `sox ui` Just Works) or keep it a separate npm-only package? **Lean: bundle a built copy with the Python package for `sox ui` convenience; also publish standalone for self-hosted operators.**

## Inputs
- TS SDK (output of ts-sdk)
- HTTP transport (output of http-transport)
- Spec for envelopes/states (output of spec-extraction)
- Optionally: TUI design choices for layout consistency (output of chat-tui-demo)

## Outputs
- `packages/ui/`
- `sox ui` CLI subcommand
- Built static assets shipped with Python package
- Demo recording

## Suggested executor
`frontend-developer` or `react-specialist`. `ui-designer` consult for layout/visual polish before public demo.

## Why post-v1

The TUI sells the pitch in a 30-second recording — that's all that's needed for launch. The webapp expands reach (especially for visitors at the docs site who aren't terminal users) but adds substantial scope: TS SDK, HTTP transport, and a frontend codebase. Shipping it for v1 risks delaying launch by weeks for marginal additional adoption signal. Dispatch after v1 ships and the protocol surface stabilizes — both prerequisites are safer to build against a frozen spec than a moving one.

## State transitions
- 2026-04-29 initialized — workflow-architect
