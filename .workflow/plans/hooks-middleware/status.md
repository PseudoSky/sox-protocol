---
slug: hooks-middleware
state: initialized
bucket: protocol+implementation
stream: B
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: high
unblocks: []
depends_on: [identity-primitive]
---

# Engagement: hooks-middleware

## Objective
Resolve the hooks-vs-middleware question, implement the chosen extensibility framework, and refactor the existing identity check to be the first plugin running on it. Validates that auth, rate limiting, schema validation, and tracing are all expressible as plugins.

## Acceptance criteria
- [ ] ADR at `docs/adr/0003-extensibility-mechanism.md` deciding hooks vs. middleware vs. hybrid
- [ ] Spec section `spec/ports/middleware.md` defining the minimal interface (inspect | mutate | short-circuit)
- [ ] Reference implementation of the middleware/hooks pipeline in `packages/python/src/sox_protocol/core/middleware/`
- [ ] Identity check refactored as the first middleware plugin (proof that auth-as-plugin works)
- [ ] At least one additional sample plugin (logging or rate-limiting) demonstrating composition
- [ ] Plugin registration documented; users can register their own without forking core
- [ ] Test coverage: pipeline ordering, short-circuit behavior, mutation chaining, error handling

## Inputs
- ADR from identity-primitive
- TODO.md §"middleware / hooks / auth"

## Outputs
- ADR
- Spec section
- Code in `core/middleware/`
- Migration of identity into the new framework
- Sample plugin

## Suggested executor
`backend-developer` or `python-pro`. ADR portion benefits from `architect-reviewer` review.

## State transitions
- 2026-04-29 initialized — workflow-architect
