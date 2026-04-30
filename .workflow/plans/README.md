# SOX Protocol — engagement plans

Self-contained, separable work plans for getting SOX from current state to launchable v1, plus a post-v1 web frontier. Each plan has its own directory with a `status.md` defining objective, acceptance criteria, inputs, outputs, dependencies, and suggested executor.

## Streams

Five parallel work streams plus a Stream 0 bootstrap that runs first. Plans within a stream are sequential; streams run in parallel where dependencies allow.

```
Stream 0 — Orchestrator bootstrap (RUN FIRST)
  [0] orchestrator-bootstrap

Stream A — Protocol foundation
  [1] bucket-classification ──→ [2] spec-extraction ──→ [5] conformance-suite

Stream B — Extensibility & security
  [3] identity-primitive ──→ [4] hooks-middleware

Stream C — Demo & adoption surface (v1)
  [6] chat-tui-demo
  [7] reference-agent

Stream D — Launch wrapping
  [8] defensive-publication      (soft-dep on [2])
  [9] launch-narrative           (dep on [1], soft-dep on [2] and [6])

Stream E — Web frontier (post-v1)
  [10] http-transport ──→ [11] ts-sdk ──→ [12] chat-webapp
```

## Critical path (v1)

`[1] bucket-classification → [2] spec-extraction → [9] launch-narrative` plus `[6] chat-tui-demo`.

Everything else in v1 is parallelizable around that spine. Stream E is post-v1 — it ships after launch and depends on a stable spec.

## Plans

| # | Slug | Bucket | Priority | Milestone | Stream | Depends on |
|---|---|---|---|---|---|---|
| 0 | [orchestrator-bootstrap](./plans/orchestrator-bootstrap/status.md) | meta | critical | v1 | 0 | — (run first) |
| 1 | [bucket-classification](./plans/bucket-classification/status.md) | meta | critical | v1 | A | — |
| 2 | [spec-extraction](./plans/spec-extraction/status.md) | protocol | critical | v1 | A | 1 |
| 3 | [identity-primitive](./plans/identity-primitive/status.md) | protocol+impl | critical | v1 | B | — |
| 4 | [hooks-middleware](./plans/hooks-middleware/status.md) | protocol+impl | high | v1 | B | 3 |
| 5 | [conformance-suite](./plans/conformance-suite/status.md) | protocol+impl | high | v1 | A | 2 |
| 6 | [chat-tui-demo](./plans/chat-tui-demo/status.md) | pitch+impl | critical | v1 | C | — |
| 7 | [reference-agent](./plans/reference-agent/status.md) | pitch+impl | high | v1 | C | — |
| 8 | [defensive-publication](./plans/defensive-publication/status.md) | pitch | high | v1 | D | — |
| 9 | [launch-narrative](./plans/launch-narrative/status.md) | pitch | high | v1 | D | 1 |
| 10 | [http-transport](./plans/http-transport/status.md) | implementation | medium | post-v1 | E | 2 |
| 11 | [ts-sdk](./plans/ts-sdk/status.md) | implementation | medium | post-v1 | E | 2, 10 |
| 12 | [chat-webapp](./plans/chat-webapp/status.md) | pitch+impl | medium | post-v1 | E | 10, 11 |

## How to dispatch

**All 12 engagements have been decomposed into the new STATE.md + phases/ format.** Each engagement has its own state machine; the orchestrator obeys `.workflow/templates/ORCHESTRATOR-CONTRACT.md`.

To advance an engagement: read its `STATE.md` → spawn the named agent for the lowest-ordinal `READY` phase → run the verbatim prompt block → execute every Exit Criteria checkbox via Bash → on all-pass, mutate STATE.md (DONE + promote unblocked phases + transition row) and commit per the trailer rules; on any-fail, mark REVIEW + commit + surface to user.

Each plan is designed to be picked up by a single agent per phase and run to completion against its phase's acceptance criteria. Suggested specialists per engagement:

```text
Plan 1 → general-purpose (synthesis)
Plan 2 → api-designer + architect-reviewer
Plan 3 → architect-reviewer (ADR) → backend-developer (impl)
Plan 4 → backend-developer
Plan 5 → test-automator
Plan 6 → python-pro
Plan 7 → python-pro
Plan 8 → content-marketer (preprint) + general-purpose (housekeeping)
Plan 9 → content-marketer
```

## Suggested execution order

**Week 1 (parallel):**
- Plan 1 (bucket-classification) — fast synthesis, unblocks A and D
- Plan 3 (identity-primitive ADR portion) — decision unblocks B
- Plan 6 (chat-tui-demo) — independent; the demo recording feeds Plan 9

**Week 2 (parallel):**
- Plan 2 (spec-extraction) — depends on 1 done
- Plan 3 (identity-primitive impl) — depends on ADR done
- Plan 7 (reference-agent) — independent
- Plan 8 (defensive-publication, license + SWHID portions) — independent of code

**Week 3 (parallel):**
- Plan 4 (hooks-middleware) — depends on 3
- Plan 5 (conformance-suite) — depends on 2
- Plan 8 (defensive-publication, preprint) — depends on 2
- Plan 9 (launch-narrative) — depends on 1, 6 done

**Week 4:**
- Integration / dogfooding / launch prep

## Status

All plans currently `initialized`. Update each plan's `status.md` `state:` field as work progresses:

```
initialized → in_progress → complete
                          → blocked (with reason)
                          → abandoned (with reason)
```
