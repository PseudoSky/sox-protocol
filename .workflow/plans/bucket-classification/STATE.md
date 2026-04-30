---
slug: bucket-classification
target: TODO.md restructured into protocol/pitch/implementation × v1/post-v1/deferred buckets, with consolidated architect-question queue. Output also includes a machine-readable classification artifact for downstream plans (spec-extraction, launch-narrative) to consume.
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
orchestrator_protocol: v1
---

# bucket-classification — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-classify-and-restructure | Tag every TODO item and rewrite the file | `READY` | general-purpose | 0 | 2026-04-29T00:00:00Z |

## Status legend

```
BLOCKED     → prerequisites not yet DONE
READY       → all prerequisites DONE; next eligible to pick up
IN_PROGRESS → an agent is currently executing
REVIEW      → agent reported done; exit criteria failed verification
DONE        → exit criteria verified
ABANDONED   → consciously dropped; reason in transitions
```

## Currently next action

`01-classify-and-restructure` is `READY`. Spawn `general-purpose` with the verbatim prompt from `phases/01-classify-and-restructure.md`.

## Transitions (append-only)

Most recent first.

- 2026-04-29T00:00:00Z 01-classify-and-restructure — initialized (READY)

## Open blockers

- (none)

## Resolved blockers

- (none)

## Termination targets

The engagement is `complete` when:

- [ ] Phase `01-classify-and-restructure` is DONE
- [ ] `TODO.md` contains six top-level sections: `## Protocol — v1`, `## Protocol — post-v1`, `## Pitch — v1`, `## Pitch — post-v1`, `## Implementation — v1`, `## Implementation — post-v1` (plus optional `## Deferred` and required `## Open architect questions`)
- [ ] `.workflow/plans/bucket-classification/classified.json` is valid JSON listing every original TODO item with bucket+milestone tags
- [ ] `.workflow/plans/bucket-classification/result.md` reports counts per bucket/milestone and the consolidated architect-question queue
