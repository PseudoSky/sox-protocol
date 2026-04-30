---
phase_id: 01-adr
title: Resolve credential primitive (ADR)
agent: architect-reviewer
profile: review
estimated_effort: 2-4 hours
prereqs: []
unblocks: [02-plan]
parallelizable_with: []
writes: ["docs/adr/**"]
reads:  ["TODO.md", "docs/vision-discussion-2026-04-29.md"]
context_size: small
---

# 01 — ADR

## Objective

Resolve the open architect question: shared secret vs. asymmetric keypair vs. server-issued JWT for per-agent credentials. Produce an ADR with explicit decision, alternatives considered, and consequences.

## Inputs

- `/Users/nix/dev/ai/sox-protocol/TODO.md` §Protocol-v1 (after bucket-classification ran) — the identity question is the top-priority callout
- `/Users/nix/dev/ai/sox-protocol/docs/vision-discussion-2026-04-29.md` — context on Claude-Code-runtime-first audience
- `/Users/nix/.claude/plugins/workflow/memory/research/patent-landscape/agent-communication-protocols.md` — IP constraints on identity tech

## Prompt (verbatim)

```text
You are authoring ADR 0002 — agent-identity-primitive — for SOX Protocol. The blocker: agent_id is currently a self-asserted env var. Need a credential primitive that lets the server reject impersonation.

CANDIDATES:
1. Shared secret per agent — minimum viable, no PKI, secret in .mcp.json env. Rotation possible. Vulnerable to env-leak.
2. Asymmetric keypair per agent — strong, server stores public key only, agent signs requests. Enables recipient-side verification (signed messages). Higher key-mgmt overhead.
3. Server-issued JWT — short-lived tokens, revocable, flexible. Requires the server to be a trusted issuer; rotation flow more complex.

CONSTRAINTS:
- Primary runtime is Claude Code subprocess (agents launched via Agent tool, .mcp.json env). Subprocess startup must obtain credential cheaply.
- Spec must remain language-neutral. ADR records the *reference impl's* choice; the spec describes the *guarantee* (verified sender).
- Apache 2.0 patent grant in scope; avoid choosing tech that someone has narrow-claim patented in this space (see patent landscape memo).

WRITE: docs/adr/0002-agent-identity-primitive.md following the standard ADR template:

# ADR 0002 — Agent identity primitive

## Status: Accepted (2026-04-29)

## Context
(2-3 paragraphs: the impersonation problem; the runtime constraints; why this blocks every other security feature)

## Decision
(Pick ONE candidate. Explicit. Justify in 2-3 sentences.)

## Alternatives considered
(Each candidate with pros/cons table; explicit rejection rationale)

## Consequences
- Positive: ...
- Negative: ...
- Operational: rotation flow, bootstrapping flow, recovery from credential loss
- Spec impact: spec/ports/identity.md describes the guarantee, not this choice. The choice is reference-impl-only.

## Open questions for follow-up
(Things deliberately deferred. e.g. "rotation grace period default" — left to implementation phase.)

REPORT: one paragraph summarizing the decision plus the top 2 consequences. ≤ 150 words.
```

## Exit criteria

Universal (`review` profile):
- [ ] `test -f docs/adr/0002-agent-identity-primitive.md`
- [ ] `grep -E '^## Status: Accepted' docs/adr/0002-agent-identity-primitive.md`

Engagement-specific:
- [ ] `grep -E '^## Decision' docs/adr/0002-agent-identity-primitive.md && grep -E '^## Alternatives considered' docs/adr/0002-agent-identity-primitive.md && grep -E '^## Consequences' docs/adr/0002-agent-identity-primitive.md`

## Outputs

- `docs/adr/0002-agent-identity-primitive.md`

## Next state

Promote `02-plan` → READY.
