---
phase_id: 02-review
title: Architectural review of spec/
agent: architect-reviewer
profile: review
estimated_effort: 2-3 hours
prereqs: [01-extract]
unblocks: []
parallelizable_with: []
writes: [".workflow/plans/spec-extraction/reviews/**"]
reads:  ["spec/**", "docs/adr/**", "docs/CONTRACTS.md", ".workflow/plans/bucket-classification/classified.json"]
context_size: medium
---

# 02 — Review

## Objective

Independent architectural review of the spec produced by 01-extract. Verify spec-vs-impl split is clean, no language bias, no ambiguities that will block downstream conformance work.

## Inputs

- `/Users/nix/dev/ai/sox-protocol/spec/` — the freshly-extracted spec
- `/Users/nix/dev/ai/sox-protocol/docs/adr/0001-protocol-vs-implementation-split.md`
- `/Users/nix/dev/ai/sox-protocol/docs/CONTRACTS.md`, `docs/DESIGN.md` — original design docs to compare against
- `/Users/nix/dev/ai/sox-protocol/.workflow/plans/bucket-classification/classified.json` — protocol-tagged items (the spec must cover all of them)
- `/Users/nix/dev/ai/sox-protocol/docs/decisions/` — architect-question decisions resolved before/during this engagement (if exists). Cross-reference: every decision should manifest somewhere in spec/.

## Prompt (verbatim)

```text
You are reviewing SOX Protocol's freshly-extracted spec for architectural soundness before downstream engagements (conformance-suite, http-transport, ts-sdk) start consuming it.

READ:
- spec/ entire tree
- docs/adr/0001-protocol-vs-implementation-split.md
- docs/CONTRACTS.md (the source the spec was derived from)
- .workflow/plans/bucket-classification/classified.json (every protocol-tagged item must be covered by the spec)

REVIEW DIMENSIONS:

1. Language neutrality. Does spec/ contain any Python idioms, ABCs, type hints in Pythonic syntax? Any Rust trait language? Anything that presumes a specific runtime?

2. Spec/impl split. Is every concept in spec/ a contract (what conformant impls must do), not a recipe (how to do it)? Flag anything that prescribes implementation choice.

3. Coverage. Does every protocol-tagged item from classified.json have a corresponding section / schema in spec/? Produce a coverage matrix.

4. Internal consistency. Do the JSON Schemas in spec/operations/ align with the prose in spec/protocol.md and spec/primitives/? Specifically: every field referenced in prose has a schema entry; every required schema field is described in prose.

5. Ambiguities. Any TODO markers in schemas (deliberately filed by 01)? Any contracts that are "implementation-defined" but vague enough that two impls could disagree?

6. Cross-impl portability test. Mentally pick one item — say "groups" — and ask: could a Rust developer implement it correctly from spec/ alone, without reading packages/python? Repeat for "ack/nack" and "presence". Any "no" answer is a finding.

7. Decisions → spec manifestation. For every architect decision under docs/decisions/ (if any), verify it shows up in spec/. Specifically check (these were flagged during 01-extract as candidates that may have been missed):
   - **`_sox_protocol` block** in `list_channels` output schema (version negotiation decision)
   - **`origin_server` field** in the envelope schema (federation-aware decision)
   - **`replay` as a distinct verb** in `spec/operations/` (or explicit deferral with rationale)
   - **`channels__ack` as a dedicated tool** in `spec/operations/` (or explicit deferral if reserved-envelope was chosen instead)
   - **`backpressure` field on send response** in send.output schema (advisory-vs-enforced decision)
   Any decision in docs/decisions/ that doesn't manifest in spec/ is either a deferral that should be marked explicitly, or a genuine miss. Both warrant a finding.

OUTPUT a review report at /Users/nix/dev/ai/sox-protocol/.workflow/plans/spec-extraction/reviews/01-extract.md with:

# spec-extraction 01-extract review

## Verdict
PASS | PASS-WITH-NOTES | FAIL

## Coverage matrix
| Protocol-tagged TODO id | Spec location | Adequate? |

## Findings
For each finding:
- Severity (blocking | warning | nit)
- File:line citation
- What's wrong
- Suggested fix

## Sign-off
If verdict is PASS or PASS-WITH-NOTES, list the specific concerns the user should be aware of even though they aren't blocking.

REPORT: verdict + count of findings by severity. ≤ 200 words.
```

## Exit criteria

Universal (`review` profile):
- [ ] `test -f .workflow/plans/spec-extraction/reviews/01-extract.md`
- [ ] `grep -E '^## Verdict' .workflow/plans/spec-extraction/reviews/01-extract.md`

Engagement-specific:
- [ ] Review verdict is `PASS` or `PASS-WITH-NOTES` (FAIL surfaces to user; remediation is a follow-up phase, not auto-advance)

## Outputs

- `.workflow/plans/spec-extraction/reviews/01-extract.md`

## Next state

Leaf phase. Engagement complete on DONE.
