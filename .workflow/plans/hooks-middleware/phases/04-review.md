---
phase_id: 04-review
title: Code review
agent: code-reviewer
profile: review
estimated_effort: 1-2 hours
prereqs: [03-implement]
unblocks: []
parallelizable_with: []
writes: [".workflow/plans/hooks-middleware/reviews/**"]
reads:  [".workflow/plans/hooks-middleware/implementation-plan.json", "docs/adr/**", "spec/ports/middleware.md", "packages/python/src/sox_protocol/core/middleware/**", "packages/python/src/sox_protocol/core/identity/**"]
context_size: medium
---

# 04 — Review

## Objective

Independent review of the framework + plugin migration.

## Inputs

- `.workflow/plans/hooks-middleware/implementation-plan.json`
- `docs/adr/0003-extensibility-mechanism.md`
- `spec/ports/middleware.md`
- `packages/python/src/sox_protocol/core/middleware/`

## Prompt (verbatim)

```text
Review the SOX Protocol middleware/hooks framework just implemented.

READ:
- .workflow/plans/hooks-middleware/implementation-plan.json
- docs/adr/0003-extensibility-mechanism.md
- spec/ports/middleware.md
- packages/python/src/sox_protocol/core/middleware/
- packages/python/src/sox_protocol/core/identity/ (post-migration)

REVIEW:
1. Spec fidelity: does the framework expose the interface spec/ports/middleware.md describes (inspect, mutate, short-circuit)?
2. Pipeline ordering correctness: short-circuit semantics, mutation chaining, error propagation
3. Plugin registration ergonomics: can a third party register a plugin without forking core/?
4. Identity migration: are the original identity invariants preserved? Specifically — unverified callers still rejected before any backing-store access?
5. Architecture: core/ → no adapter imports. Plugin authors can pick their own adapters.
6. Test coverage gaps despite 100% line coverage (concurrency, error paths, plugin-throws-exception path).

OUTPUT: .workflow/plans/hooks-middleware/reviews/03-implement.md (Verdict, Findings, Spec-fidelity matrix, Sign-off)

REPORT: ≤ 200 words.
```

## Exit criteria

Universal (`review`):
- [ ] `test -f .workflow/plans/hooks-middleware/reviews/03-implement.md`
- [ ] `grep -E '^## Verdict' .workflow/plans/hooks-middleware/reviews/03-implement.md`

## Outputs

- `.workflow/plans/hooks-middleware/reviews/03-implement.md`

## Next state

Leaf. Engagement complete on DONE.
