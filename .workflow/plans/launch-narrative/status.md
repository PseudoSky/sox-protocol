---
slug: launch-narrative
state: initialized
bucket: pitch
stream: D
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: high
unblocks: []
depends_on: [bucket-classification]
soft_depends_on: [chat-tui-demo, spec-extraction]
---

# Engagement: launch-narrative

## Objective
Produce the user-facing narrative artifacts for launch: rewritten README, "Why SOX?" page, worked example, public roadmap. The materials that turn a visitor into a user.

## Acceptance criteria
- [ ] `README.md` rewritten:
  - Opens with one-line pitch ("Group chat for AI agents — channels, threads, presence, DMs, but the participants are LLMs")
  - 30-second demo recording embedded near top (from chat-tui-demo)
  - Quick-start: 5-minute install + run-the-demo path
  - Links to spec, why-sox, example, roadmap
  - License + defensive-publication badges
- [ ] `docs/why-sox.md` — names competitors directly (LangGraph, AutoGen, MCP, A2A, NATS), one screen, one paragraph each
- [ ] `docs/example.md` — worked example, two agents collaborating end-to-end in 40 lines
- [ ] `docs/roadmap.md` — public roadmap derived from bucket-classification output, milestone-tagged
- [ ] Tone audit: protocol/spec/substrate/primitive vocabulary throughout, not library/framework/tool
- [ ] Launch-day collateral drafted: HN post title + body, Anthropic Discord drop, Twitter thread

## Inputs
- Bucket-classification output (drives roadmap shape)
- Chat TUI demo recording (for README)
- Spec (for technical accuracy)
- Vision discussion document (`docs/vision-discussion-2026-04-29.md`)

## Outputs
- Rewritten `README.md`
- `docs/why-sox.md`, `docs/example.md`, `docs/roadmap.md`
- `docs/launch/` with draft posts

## Suggested executor
`content-marketer`.

## State transitions
- 2026-04-29 initialized — workflow-architect
