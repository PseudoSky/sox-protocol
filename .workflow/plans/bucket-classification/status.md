---
slug: bucket-classification
state: initialized
bucket: meta
stream: A
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: critical
unblocks: [spec-extraction, launch-narrative]
depends_on: []
---

# Engagement: bucket-classification

## Objective
Tag every item in `TODO.md` with one of `{protocol, pitch, implementation}` and a milestone tag `{v1, post-v1, deferred}`. Output a re-organized backlog grouped by bucket and milestone.

## Acceptance criteria
- [ ] Every existing TODO item has both a bucket and milestone tag
- [ ] Items contradicting the protocol-vs-implementation split are flagged with rationale
- [ ] Output written to `TODO.md` (in place restructure, with sections per bucket × milestone)
- [ ] Items deferred past v1 are listed under a clear "post-v1" section, not removed
- [ ] An "open architect questions" section consolidates every `Q (architect)` callout from the original

## Inputs
- `/Users/nix/dev/ai/sox-protocol/TODO.md`
- `/Users/nix/dev/ai/sox-protocol/docs/vision-discussion-2026-04-29.md` (vision context)

## Outputs
- Rewritten `TODO.md`
- `.workflow/plans/bucket-classification/result.md` summarizing classification decisions

## Suggested executor
`general-purpose` agent. This is synthesis work, not coding.

## State transitions
- 2026-04-29 initialized — workflow-architect
