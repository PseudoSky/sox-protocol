---
phase_id: 01-narrative
title: All launch-day content
agent: content-marketer
profile: docs
estimated_effort: 2-3 days
prereqs: []
unblocks: []
parallelizable_with: []
writes: ["README.md", "docs/why-sox.md", "docs/example.md", "docs/roadmap.md", "docs/launch/**"]
reads:  ["TODO.md", ".workflow/plans/bucket-classification/classified.json", "docs/media/**", "spec/**", "docs/vision-discussion-2026-04-29.md"]
context_size: large
---

# 01 — Narrative

## Objective

Produce every user-facing narrative artifact in one specialist's pass. README rewrite, why-sox, worked example, roadmap, launch posts.

## Inputs

- `TODO.md` (rewritten by bucket-classification — the v1 items become the public roadmap)
- `.workflow/plans/bucket-classification/classified.json`
- `docs/media/demo.gif` (output of chat-tui-demo)
- `spec/` (technical accuracy)
- `docs/vision-discussion-2026-04-29.md`
- `~/.claude/plugins/workflow/memory/research/patent-landscape/agent-communication-protocols.md` (for Why-SOX competitor framing)

## Prompt (verbatim)

```text
Write all SOX Protocol launch-day narrative content. One specialist, one pass.

READ:
- TODO.md (classified backlog)
- .workflow/plans/bucket-classification/classified.json (counts, ambiguities, architect questions)
- docs/media/demo.gif (the demo asset to embed)
- spec/protocol.md and spec/primitives/ (for technical accuracy)
- docs/vision-discussion-2026-04-29.md (the project's articulated vision)
- ~/.claude/plugins/workflow/memory/research/patent-landscape/agent-communication-protocols.md (related-work framing)

ONE-LINE PITCH (use this everywhere — README, posts, Twitter):
"Group chat for AI agents — channels, threads, presence, DMs, but the participants are LLMs."

DELIVER:

1. Rewritten README.md — replace existing content. Structure:

   - Title + one-line pitch
   - <embed docs/media/demo.gif>
   - "What is SOX?" — 3 paragraphs answering: what / why now / who's it for
   - Quickstart — 5 minutes from `pip install` to running the two-agent demo
   - Links section: Spec, Why SOX, Example, Roadmap, License (Apache 2.0), arXiv preprint
   - Badges: license, CI status, conformance suite, PyPI version
   - Contributing section (link to CONTRIBUTING.md)
   - License section

2. docs/why-sox.md — names competitors directly. One screen. Format:

   ## Why SOX?

   Use SOX when: <three bullets>

   ### vs. orchestration frameworks (LangGraph, CrewAI, AutoGen)
   <one paragraph: they're DAG/supervisor patterns; SOX is peer-to-peer chat>

   ### vs. message queues (Redis pub/sub, NATS, Kafka)
   <one paragraph: those are dumb pipes; SOX is agent-aware>

   ### vs. MCP
   <one paragraph: MCP is agent→tool; SOX is agent→agent. Orthogonal — use both>

   ### vs. A2A (Google) / ACP (IBM)
   <one paragraph: those are RPC/task protocols; SOX is chat substrate. Different shape, complementary>

3. docs/example.md — two agents collaborating end-to-end, ≤ 40 lines of code. Heavy commentary. Mirrors the reference-agent's lifecycle but compact.

4. docs/roadmap.md — public roadmap derived from classified.json. Sections:
   - Shipping in v1 (every protocol-v1 + pitch-v1 + implementation-v1 item, grouped by stream)
   - Coming after v1 (post-v1 items, by quarter if possible)
   - Open questions (the architect-questions list — invite community input)

5. docs/launch/hn-post.md — Hacker News post draft. Title (≤ 60 chars), body (~ 200 words), top-comment hook for the OP follow-up (200 words explaining technical depth without rehashing the post).

6. docs/launch/discord-drop.md — Anthropic Discord post (~150 words). Different tone than HN — more technical, more excited, links to demo first.

7. docs/launch/twitter-thread.md — 8-12 tweet thread. First tweet hooks (the demo gif + one line). Last tweet links to repo + arXiv + invites contributors.

TONE RULES:
- "Protocol", "substrate", "primitive" — not "library", "framework", "tool"
- Concrete > abstract. Show the demo gif before any theory.
- No hype words ("revolutionary", "game-changing"). Confidence comes from specificity.
- Every claim about competitors must be accurate; check Why-SOX against the patent-landscape memo's competitor descriptions.

ACCEPTANCE:
- All seven deliverables exist
- markdownlint passes on touched files
- markdown-link-check passes on README + why-sox + example
- The README's first 200 words mention: the one-line pitch, the demo, the spec link, the install command. In that order.
- The roadmap has at least 5 items per stream-bucket (otherwise it looks empty).

REPORT: ≤ 250 words. Word count of README. Top three concerns flagged about the public roadmap shape. The HN post's title.
```

## Exit criteria

Universal (`docs`):
- [ ] `npx markdownlint README.md docs/why-sox.md docs/example.md docs/roadmap.md 'docs/launch/*.md'`
- [ ] `npx markdown-link-check README.md docs/why-sox.md docs/example.md`
- [ ] `cspell README.md 'docs/**/*.md'`

Engagement-specific:
- [ ] `test -f docs/why-sox.md && test -f docs/example.md && test -f docs/roadmap.md`
- [ ] `test -f docs/launch/hn-post.md && test -f docs/launch/discord-drop.md && test -f docs/launch/twitter-thread.md`
- [ ] `grep -q 'demo.gif\|demo.cast' README.md`
- [ ] `head -20 README.md | grep -qi 'group chat\|agents'` (one-line pitch in the first 20 lines)
- [ ] `grep -q 'spec/' README.md` (links to spec/)
- [ ] `grep -qE 'LangGraph|CrewAI|AutoGen' docs/why-sox.md && grep -qE 'MCP|A2A|ACP' docs/why-sox.md`

## Outputs

- `README.md` (rewritten)
- `docs/why-sox.md`, `docs/example.md`, `docs/roadmap.md`
- `docs/launch/hn-post.md`, `docs/launch/discord-drop.md`, `docs/launch/twitter-thread.md`

## Next state

Leaf. Engagement complete on DONE.
