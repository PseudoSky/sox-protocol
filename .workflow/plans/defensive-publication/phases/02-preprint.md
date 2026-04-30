---
phase_id: 02-preprint
title: arXiv preprint draft
agent: content-marketer
profile: docs
estimated_effort: 2-3 days
prereqs: [01-housekeeping]
unblocks: []
parallelizable_with: []
writes: ["docs/ip/preprint/**"]
reads:  ["spec/**", "docs/DESIGN.md"]
context_size: large
---

# 02 — Preprint

## Objective

Draft a 6-10 page arXiv preprint (cs.MA category) describing SOX Protocol: primitives, semantics, related work, worked example. Defensive-publication artifact + adoption signal.

## Inputs

- `spec/` (canonical surface to cite)
- `~/.claude/plugins/workflow/memory/research/patent-landscape/agent-communication-protocols.md` (related-work and prior-art context — KQML, FIPA, JADE, CAMEL/ChatDev/MetaGPT, MCP, A2A, ACP)
- `docs/DESIGN.md` (architecture context)

## Prompt (verbatim)

```text
Draft an arXiv preprint for SOX Protocol — a real-time many-to-many messaging protocol where LLM agents are first-class peers (channels, groups, threads, presence, ACK/NACK, DMs).

TARGET: cs.MA (Multi-Agent Systems) primary, cs.DC secondary.
LENGTH: 6-10 pages.
FORMAT: Markdown at docs/ip/preprint/sox-protocol.md AND ALSO LaTeX-ready at docs/ip/preprint/sox-protocol.tex (use pandoc or write directly).

READ:
- spec/ entire tree (cite specifically)
- ~/.claude/plugins/workflow/memory/research/patent-landscape/agent-communication-protocols.md (related work and prior art)
- docs/DESIGN.md

STRUCTURE:

1. Abstract (200 words). The novelty claim, the key primitives, the conformance approach, the result.

2. Introduction (1 page). Why agent-to-agent communication is its own layer separate from MCP (tool-calling), separate from orchestration frameworks (LangGraph, CrewAI, AutoGen — supervisor patterns), separate from raw pub/sub (Redis, NATS — dumb pipes). The gap SOX fills.

3. Related work (1 page). KQML (1993), FIPA-ACL (2000), JADE (1999-) as the agent-communication forerunners. CAMEL (NeurIPS 2023), ChatDev (ACL 2024), MetaGPT (ICLR 2024) as LLM-era prior art. Anthropic MCP (2024), Google A2A (2025), IBM ACP (2025) as adjacent specs. SOX's distinguishing claim: first-class chat substrate, not RPC, not orchestration.

4. Protocol primitives (2-3 pages). Each subsection one primitive: channels, groups, dms, threads, presence, ack/nack. State diagrams. Semantics. Cite spec/primitives/<name>.md.

5. Operations and envelopes (1 page). The four core operations (send, recv, subscribe, list_channels). Reserved envelopes (sox/ack, sox/nack, sox/error, sox/invite). Cite spec/operations/.

6. Architecture (1 page). Spec-vs-implementation split. Ports: transport, backing store, identity, middleware. Reference Python implementation as one of N possible.

7. Conformance (0.5 page). Language-neutral conformance suite. How third-party impls register.

8. Worked example (0.5 page). Two agents collaborating end-to-end — minimal code in 30 lines.

9. Conclusion + future work (0.5 page).

CITATIONS: at least 15 references across KQML/FIPA/JADE, LLM-era multi-agent papers, MCP, A2A, ACP. Use BibTeX entries.

CONSTRAINTS:
- Tone: academic, sober. No marketing language.
- Cite spec/ sections specifically — every primitive description has at least one `\cite{spec:<file>:<section>}` (define a custom bib entry that points to the github URL with anchor).
- The point of this artifact is timestamped, citable, indexed prior art. Be specific.
- Submit-readiness: provide a brief checklist at end of docs/ip/preprint/SUBMISSION.md noting what the user needs to do (arXiv account, endorsement, category selection).

ACCEPTANCE:
- docs/ip/preprint/sox-protocol.md exists, ≥ 6 and ≤ 12 page-equivalents (~3000-6000 words)
- docs/ip/preprint/sox-protocol.tex exists (or pandoc command in SUBMISSION.md to generate it)
- docs/ip/preprint/refs.bib exists with ≥ 15 entries
- docs/ip/preprint/SUBMISSION.md exists with submission checklist
- markdownlint passes
- markdown-link-check passes (no broken cross-refs to spec/)

REPORT: word count, citation count, the most important claim the preprint makes about novelty. ≤ 200 words.
```

## Exit criteria

Universal (`docs`):
- [ ] `npx markdownlint 'docs/ip/preprint/**/*.md'`
- [ ] `npx markdown-link-check docs/ip/preprint/sox-protocol.md`
- [ ] `cspell 'docs/ip/preprint/**/*.md'` (or equivalent)

Engagement-specific:
- [ ] `test -f docs/ip/preprint/sox-protocol.md`
- [ ] `test -f docs/ip/preprint/sox-protocol.tex || grep -q 'pandoc' docs/ip/preprint/SUBMISSION.md`
- [ ] `test -f docs/ip/preprint/refs.bib`
- [ ] `grep -c '^@' docs/ip/preprint/refs.bib | awk '{exit ($1 < 15)}'`
- [ ] `test -f docs/ip/preprint/SUBMISSION.md`
- [ ] `wc -w docs/ip/preprint/sox-protocol.md | awk '{exit !($1 >= 3000 && $1 <= 6000)}'`

## Outputs

- `docs/ip/preprint/sox-protocol.md`
- `docs/ip/preprint/sox-protocol.tex`
- `docs/ip/preprint/refs.bib`
- `docs/ip/preprint/SUBMISSION.md`

## Next state

Leaf. Engagement complete on DONE.
