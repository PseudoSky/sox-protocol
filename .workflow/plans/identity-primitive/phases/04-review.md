---
phase_id: 04-review
title: Code review
agent: code-reviewer
profile: review
estimated_effort: 1-2 hours
prereqs: [03-implement]
unblocks: []
parallelizable_with: []
writes: [".workflow/plans/identity-primitive/reviews/**"]
reads:  [".workflow/plans/identity-primitive/implementation-plan.json", "docs/adr/**", "spec/ports/**", "packages/python/src/sox_protocol/core/identity/**", "packages/python/tests/identity/**"]
context_size: medium
---

# 04 — Review

## Objective

Independent code review of the identity layer against the spec and the planner's implementation plan. Catch what tests don't.

## Inputs

- `/Users/nix/dev/ai/sox-protocol/.workflow/plans/identity-primitive/implementation-plan.json`
- `/Users/nix/dev/ai/sox-protocol/docs/adr/0002-agent-identity-primitive.md`
- `/Users/nix/dev/ai/sox-protocol/spec/ports/identity.md`
- `/Users/nix/dev/ai/sox-protocol/packages/python/src/sox_protocol/core/identity/` (the new code)
- `/Users/nix/dev/ai/sox-protocol/packages/python/tests/identity/`

## Prompt (verbatim)

```text
Review the SOX Protocol identity layer just implemented in packages/python/src/sox_protocol/core/identity/.

READ:
- .workflow/plans/identity-primitive/implementation-plan.json (the contract)
- docs/adr/0002-agent-identity-primitive.md (the decision)
- spec/ports/identity.md (the guarantee)
- packages/python/src/sox_protocol/core/identity/ (the implementation)
- packages/python/tests/identity/ (the tests)

REVIEW DIMENSIONS:

1. Spec fidelity. Does the implementation honor every behaviour specified in spec/ports/identity.md? Specifically: are there any code paths where a claimed agent_id is accepted without credential check?
2. Plan fidelity. Did the implementer build what the plan said? Any deviations should be deliberate, not accidental.
3. Architecture. Does core/identity/ import only from core/ (no adapter imports)? Does the middleware registration happen in core, with the actual registry able to be backed by an adapter?
4. Test coverage gaps. Tests run at 100% line coverage but coverage isn't completeness. Specifically check: rejection paths, expired credentials (if applicable per ADR), audit-log write failures, concurrent-send races on the registry.
5. Security review of the credential primitive itself. Constant-time comparisons where applicable? Secrets logged anywhere?
6. Audit log shape. Does it match spec / does it capture enough to detect attacks?

OUTPUT: .workflow/plans/identity-primitive/reviews/03-implement.md

# identity-primitive 03-implement review

## Verdict
PASS | PASS-WITH-NOTES | FAIL

## Findings
- Severity (blocking | warning | nit) | file:line | issue | suggested fix

## Spec-fidelity matrix
| Behaviour from spec/ports/identity.md | Implemented? | Test coverage? |

## Sign-off

REPORT: verdict + count of findings by severity + the most concerning finding. ≤ 200 words.
```

## Exit criteria

Universal (`review` profile):
- [ ] `test -f .workflow/plans/identity-primitive/reviews/03-implement.md`
- [ ] `grep -E '^## Verdict' .workflow/plans/identity-primitive/reviews/03-implement.md`

## Outputs

- `.workflow/plans/identity-primitive/reviews/03-implement.md`

## Next state

Leaf phase. Engagement complete on DONE.
