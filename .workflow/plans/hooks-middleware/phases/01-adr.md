---
phase_id: 01-adr
title: Resolve hooks vs middleware (ADR)
agent: architect-reviewer
profile: review
estimated_effort: 2-4 hours
prereqs: []
unblocks: [02-plan]
parallelizable_with: []
writes: ["docs/adr/**"]
reads:  ["TODO.md", "spec/ports/middleware.md", "packages/python/src/sox_protocol/core/identity/**"]
context_size: small
---

# 01 — ADR

## Objective

Decide between hooks (pre/post events), middleware (request/response pipeline), or hybrid. Record decision rationale in `docs/adr/0003-extensibility-mechanism.md`.

## Inputs

- `/Users/nix/dev/ai/sox-protocol/TODO.md` §"middleware / hooks / auth" (in classified backlog)
- `/Users/nix/dev/ai/sox-protocol/spec/ports/middleware.md` (output of spec-extraction)
- `/Users/nix/dev/ai/sox-protocol/packages/python/src/sox_protocol/core/identity/` (output of identity-primitive — the existing identity check that will move into this framework)

## Prompt (verbatim)

```text
Author ADR 0003 — extensibility-mechanism — for SOX Protocol.

QUESTION: hooks (pre/post-tool events with light power) vs middleware (full request/response pipeline) vs hybrid.

CANDIDATES:
1. Hooks — familiar from Claude Code's runtime adapter. Pre/post events fire on tool calls. Cannot mutate the request, can short-circuit by returning a decision. Low overhead, easy to reason about.
2. Middleware — full pipeline. Each middleware can inspect, mutate (request and/or response), short-circuit, or pass through. More power, more complexity, established pattern (Django, Express).
3. Hybrid — hooks for observability/short-circuit (auth, rate limit); middleware for transformation (envelope rewriting, schema validation, tracing).

USE CASES TO COVER:
- Identity verification (must short-circuit before backing-store access)
- Rate limiting (advisory or enforcing)
- Schema validation
- Tracing / observability
- Audit logging
- Future: ACL, idempotency dedup

CONSTRAINTS:
- Spec describes the *interface* (inspect | mutate | short-circuit), not the implementation. Reference impl picks the mechanism.
- Plugin authors should be able to register without forking core.

WRITE: docs/adr/0003-extensibility-mechanism.md (standard ADR template — Status, Context, Decision, Alternatives considered, Consequences, Open questions).

REPORT: one paragraph summary of the decision plus the most consequential trade-off accepted. ≤ 150 words.
```

## Exit criteria

Universal (`review` profile):
- [ ] `test -f docs/adr/0003-extensibility-mechanism.md`
- [ ] `grep -E '^## (Status|Decision|Alternatives considered|Consequences)' docs/adr/0003-extensibility-mechanism.md | wc -l | grep -q '^[[:space:]]*4$'`

## Outputs

- `docs/adr/0003-extensibility-mechanism.md`

## Next state

Promote `02-plan` → READY.
