---
phase_id: 01-classify-and-restructure
title: Tag every TODO item and rewrite the file
agent: general-purpose
profile: meta
estimated_effort: 1 hour
prereqs: []
unblocks: []
parallelizable_with: []
writes: ["TODO.md", ".workflow/plans/bucket-classification/**"]
reads:  ["TODO.md", "docs/vision-discussion-2026-04-29.md", ".workflow/plans/README.md", ".workflow/plans/bucket-classification/status.md"]
context_size: medium
---

# 01 — Classify and restructure

## Objective

Read every actionable item in `/Users/nix/dev/ai/sox-protocol/TODO.md`, tag it with two labels (bucket × milestone), and rewrite the file in the new bucket-grouped structure. Also produce a `classified.json` artifact downstream engagements can consume programmatically and a `result.md` summary.

This is one specialist's work end-to-end: read, judge, write. Not split across phases because no specialist handoff occurs — the agent that judges is the agent that writes.

## Inputs

- `/Users/nix/dev/ai/sox-protocol/TODO.md` — the source backlog (~230 items across ~25 sections)
- `/Users/nix/dev/ai/sox-protocol/docs/vision-discussion-2026-04-29.md` — vision context defining the three buckets and the launch-critical-path framing
- `/Users/nix/dev/ai/sox-protocol/.workflow/plans/README.md` — engagement overview; the launch-critical path is in there
- `/Users/nix/dev/ai/sox-protocol/.workflow/plans/bucket-classification/status.md` — engagement objective and acceptance criteria (read; do not modify)

## Prompt (verbatim — do not paraphrase when dispatching)

```text
You are classifying and restructuring a software-project backlog. The project is SOX Protocol — a real-time many-to-many chat protocol for LLM agents. The backlog at /Users/nix/dev/ai/sox-protocol/TODO.md has roughly 230 items across ~25 thematic sections.

Your task has THREE deliverables in one pass: classify every item, rewrite TODO.md in the new structure, and emit a summary.

READ FIRST:
1. /Users/nix/dev/ai/sox-protocol/TODO.md — the entire file
2. /Users/nix/dev/ai/sox-protocol/docs/vision-discussion-2026-04-29.md — defines the three buckets and the v1 critical path
3. /Users/nix/dev/ai/sox-protocol/.workflow/plans/README.md — engagement landscape

THE THREE BUCKETS:

- protocol → must be in the spec; defines what "SOX" means; required for cross-implementation interop. Example: "reply_to field on send" — every conformant implementation must support it.
- pitch → shapes how the project is received and adopted; lives in narrative/marketing/posture artifacts. Example: "Animated terminal recording embedded in README".
- implementation → reference Python package and tooling; can be replaced or ported without touching the protocol. Example: "Cursor-based pagination on recv()" — useful at scale, not protocol-defining.

THE THREE MILESTONES:

- v1 → mandatory for the launch moment
- post-v1 → ships after launch in versioned releases
- deferred → genuinely speculative; parking-lot

THE THREE-QUESTION TEST (apply to every item):

1. "If a Rust implementation didn't have this, would it still be SOX?" No → protocol. Yes → keep going.
2. "If we removed this, would the project's story still land?" No → pitch. Yes → keep going.
3. "If we replaced this with a different choice (different store, transport, auth), would users notice across implementations?" Yes → implementation.

For ambiguous items, apply the test verbatim and record the rationale.

ARCHITECT QUESTIONS:

The TODO contains many "Q (architect):" callouts. Do NOT classify these as actionable items. Instead, collect them into a separate list with the question text and the section it appears in.

DELIVERABLE 1 — /Users/nix/dev/ai/sox-protocol/.workflow/plans/bucket-classification/classified.json

Schema (JSON):

{
  "source_file": "TODO.md",
  "source_line_count": <int>,
  "items": [
    {
      "id": "<stable-slug-derived-from-text>",
      "section": "<original H2/H3 section>",
      "text": "<verbatim item text minus the leading '- [ ] '>",
      "bucket": "protocol|pitch|implementation",
      "milestone": "v1|post-v1|deferred",
      "ambiguity": "low|medium|high",
      "rationale": "<one sentence; required only when ambiguity != low>"
    },
    ...
  ],
  "architect_questions": [
    {
      "section": "<H2/H3 section>",
      "question": "<verbatim question text>"
    },
    ...
  ],
  "counts": {
    "by_bucket": {"protocol": <n>, "pitch": <n>, "implementation": <n>},
    "by_milestone": {"v1": <n>, "post-v1": <n>, "deferred": <n>},
    "by_bucket_x_milestone": {"protocol-v1": <n>, ...}
  },
  "notes": "<one-paragraph reflection on contradictions or surprises>"
}

DELIVERABLE 2 — /Users/nix/dev/ai/sox-protocol/TODO.md (overwrite) with structure:

# SOX Protocol — backlog

> Classified <YYYY-MM-DD>. Source classification: `.workflow/plans/bucket-classification/classified.json`. Update via `bucket-classification` engagement re-run.

## Protocol — v1
(One bullet per item; preserve original section as H3 sub-grouping inside; verbatim text)

## Protocol — post-v1
...

## Pitch — v1
...

## Pitch — post-v1
...

## Implementation — v1
...

## Implementation — post-v1
...

## Deferred
(only if any items have milestone="deferred"; group by bucket as H3)

## Open architect questions
(One bullet per architect_questions[] entry. Format: "**<question>** — original section: <section>")

DELIVERABLE 3 — /Users/nix/dev/ai/sox-protocol/.workflow/plans/bucket-classification/result.md

# bucket-classification — result

## Counts
(Markdown table from classified.json.counts)

## Architect questions queue
(Numbered list from classified.json.architect_questions, sorted by their original section order)

## Surprises and contradictions
(One-paragraph excerpt from classified.json.notes plus any contradictions you noticed)

## Recommended question-resolution order
(Your synthesized opinion on which architect questions to resolve first. Maximum 5 entries.)

HARD CONSTRAINTS:

- Do not skip items. If unclassifiable, mark ambiguity="high" and explain.
- Architect questions go in their own list, not the items array.
- Every item gets BOTH a bucket and a milestone — no nulls.
- The id field must be unique; derive deterministically from text (kebab-case, first 6 words).
- In TODO.md rewrite: use VERBATIM text from items[].text. Do not edit, summarize, or "improve".
- Do not introduce new items. classified.json is the closed set.
- H2 ordering MUST be exactly: Protocol-v1, Protocol-post-v1, Pitch-v1, Pitch-post-v1, Implementation-v1, Implementation-post-v1, Deferred (if any), Open architect questions.

ACCEPTANCE (self-check before reporting done):

- [ ] classified.json exists, is valid JSON, has items[] + architect_questions[] + counts
- [ ] Every items[] entry has non-empty bucket, milestone, id, text, section
- [ ] All ids are unique
- [ ] TODO.md has the seven required H2 sections in the required order plus required preamble citing classified.json
- [ ] Every items[] entry appears as a bullet in TODO.md
- [ ] Every architect_questions[] entry appears under "Open architect questions"
- [ ] result.md exists with the four required H2 sections

REPORT (final response): one paragraph summarizing classification balance (e.g. "of 230 items, 68 protocol / 32 pitch / 130 implementation; 89 v1 / 121 post-v1 / 20 deferred"), plus the top 5 ambiguous items with assigned bucket and rationale, plus confirmation that all three deliverables were written.
```

## Exit criteria

- [ ] `test -f /Users/nix/dev/ai/sox-protocol/.workflow/plans/bucket-classification/classified.json`
- [ ] `python3 -c "import json; d=json.load(open('.workflow/plans/bucket-classification/classified.json')); assert 'items' in d and 'architect_questions' in d and 'counts' in d"`
- [ ] `python3 -c "import json; d=json.load(open('.workflow/plans/bucket-classification/classified.json')); items=d['items']; assert all(i.get('bucket') in {'protocol','pitch','implementation'} for i in items); assert all(i.get('milestone') in {'v1','post-v1','deferred'} for i in items)"`
- [ ] `python3 -c "import json; d=json.load(open('.workflow/plans/bucket-classification/classified.json')); ids=[i['id'] for i in d['items']]; assert len(ids) == len(set(ids))"`
- [ ] `test -f /Users/nix/dev/ai/sox-protocol/TODO.md`
- [ ] `grep -q '^## Protocol — v1' TODO.md && grep -q '^## Protocol — post-v1' TODO.md && grep -q '^## Pitch — v1' TODO.md && grep -q '^## Pitch — post-v1' TODO.md && grep -q '^## Implementation — v1' TODO.md && grep -q '^## Implementation — post-v1' TODO.md && grep -q '^## Open architect questions' TODO.md`
- [ ] `grep -q 'classified.json' TODO.md`
- [ ] `python3 -c "import json; d=json.load(open('.workflow/plans/bucket-classification/classified.json')); todo=open('TODO.md').read(); missing=[i['text'][:40] for i in d['items'] if i['text'][:30] not in todo]; assert not missing, f'missing items: {missing[:3]}'"`
- [ ] `test -f /Users/nix/dev/ai/sox-protocol/.workflow/plans/bucket-classification/result.md`
- [ ] `grep -E '^## (Counts|Architect questions queue|Surprises and contradictions|Recommended question-resolution order)' .workflow/plans/bucket-classification/result.md | wc -l | grep -q '^[[:space:]]*4$'`

## On verification failure

If JSON malformed or missing fields: re-spawn citing the failing checkbox.
If items missing from rewritten TODO: agent likely lost some during section-grouping; re-spawn with the specific missing item ids.
If section headings wrong: re-spawn with the exact required ordering pasted in feedback.

## Outputs

- `.workflow/plans/bucket-classification/classified.json`
- `/Users/nix/dev/ai/sox-protocol/TODO.md` (rewritten)
- `.workflow/plans/bucket-classification/result.md`

## Next state

This is a leaf phase for this engagement. When DONE, the engagement is complete. Downstream engagements (`spec-extraction`, `launch-narrative`) read from the rewritten TODO.md and `classified.json`.

## Notes

The three deliverables stay in one phase because they're produced by one specialist's coherent thought process: classifying an item and writing it into its bucket section is the same act. Splitting at logical sub-step boundaries would force the agent to re-load context twice without any specialist transition. The `classified.json` artifact provides auditability — if a tag is wrong, the user edits JSON, not TODO.md, and a future re-run can re-derive TODO.md from the corrected source.
