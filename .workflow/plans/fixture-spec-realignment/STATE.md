---
slug: fixture-spec-realignment
target: Close the 9 HTTP conformance failures that map to v1 MUST features. Each failure is either a real impl gap (reply_to silently dropped, replay/since not honored, unsubscribe doesn't discard queue) or a spec/impl mismatch (group_invite output fields). Goal: HTTP conformance reaches 33/0/34 — parity with stdio. Eliminate any harness simulator paths that mask the gap (per RESUME.md §"harness's stdio adapter has been masking real spec/impl gaps").
created: 2026-05-04
last_event: 2026-05-04T00:00:00Z
orchestrator_protocol: v1
parent_plan: plugin-architecture (post-v1-program follow-on)
prereqs: []  # all P1–P6 closed
priority: HIGH — these are spec-declared v1 MUST features that are silently broken
---

# fixture-spec-realignment — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Inspect each of the 9 failures; for each, decide fix-spec-or-fix-impl; produce per-fixture plan with file paths and root-cause analysis | `READY` | sox-cto-system:planner | 0 | 2026-05-04T00:00:00Z |
| 02-fix-reply-to | Plumb `reply_to` through `StoreDispatchMiddleware` → `BackingStore.send` signature → memory + sqlite store persistence → recv echo. Closes 3 fixtures (`threading/01-reply-to-link`, `threading/02-deep-thread`, `threading/03-thread-depth-zero`). Delete the `tools/conformance_runner.py:918` monkeypatch that simulates `reply_to`. | `BLOCKED` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 03-fix-replay-since | Investigate why `replay/01-replay-since-seq` and `replay/02-replay-empty-future-cursor` return 0 messages where harness simulation returns 2. Likely: `BackingStore.replay` impl doesn't honor `since` cursor end-to-end. Audit and fix; delete any harness simulation. | `BLOCKED` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 04-fix-unsubscribe-discard | Per V1-SCOPE.md `unsubscribe` row ("Discards queued-but-unread messages"): unsubscribe must purge the listener's pending queue for matching channels. Closes `subscription-patterns/02-unsubscribe-discards-queue`. Audit `MemoryStore.unsubscribe` and `SqliteStore.unsubscribe`; both must implement the discard. | `BLOCKED` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 05-fix-presence-namespace | Closes 2 fixtures: `presence/01-heartbeat-updates-presence-channel` (heartbeat tool must emit on `sox/presence` channel per V1-SCOPE.md heartbeat row) and `namespace-isolation/02-version-block` (list_channels must return the `_sox_protocol` version-negotiation block per V1-SCOPE.md). Likely small individually but related to wire-protocol completeness. | `BLOCKED` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 06-fix-group-invite-output | Resolve spec/impl mismatch: `spec/operations/group_invite.output.schema.json` says `{invited, agent_id}` but impl emits `{group_id, invited_agent}`. Decide which is canonical (spec normally wins; check ADR / git history for original intent). Update the loser. Delete the `tools/conformance_runner.py:1108` client-side remap that masks this on stdio. Closes `groups/01-create-invite-join`. | `BLOCKED` | python-pro | 0 | 2026-05-04T00:00:00Z |
| 07-review | Code review covering all 6 fixes + verification that no new harness simulations were introduced. HTTP conformance MUST reach 33/0/34 (parity with stdio). Closes engagement. | `BLOCKED` | code-reviewer | 0 | 2026-05-04T00:00:00Z |

## Currently next action

Dispatch **phase 01-plan** to a planner agent. Inputs:
- The 9 failures listed in commit `bb7aaa7`'s body and in this STATE.md's phases 02–06
- `tools/conformance_runner.py` lines 766–1127 (the `SharedMemoryTarget` simulator) — every harness simulation that masks a real gap must be identified and slated for deletion as part of the corresponding fix
- `docs/V1-SCOPE.md` — the authoritative v1 contract that each fixture validates
- Each failure's YAML fixture under `spec/conformance/`

Planner produces `implementation-plan.json` with: per-failure root-cause hypothesis, files to touch, harness simulations to delete, test additions, ordering dependencies (e.g. reply_to must land before any thread-depth fixture can pass).

## Termination targets

- [ ] All 7 phases DONE
- [ ] HTTP conformance: 33 passed, 0 failed, 34 skipped (parity with stdio — currently 24/9/34)
- [ ] stdio conformance: 33 passed, 0 failed, 34 skipped (no regression)
- [ ] All harness simulations identified in this engagement deleted from `tools/conformance_runner.py`
- [ ] `BackingStore.send` interface accepts `reply_to: str | None` parameter; `MemoryStore` and `SqliteStore` both persist it; `recv` returns it
- [ ] `BackingStore.replay(channel, since, until, limit)` honors `since` cursor end-to-end on both transports
- [ ] `unsubscribe` discards queued-but-unread messages from listener queue (per V1-SCOPE.md)
- [ ] `channels__heartbeat` emits update event on `sox/presence` channel (per V1-SCOPE.md presence.md §2)
- [ ] `list_channels` response includes the `_sox_protocol` version-negotiation block on every call (per V1-SCOPE.md)
- [ ] `group_invite` output field-name aligned across spec + impl + fixture; client-side remap at conformance_runner.py:1108 deleted
- [ ] mypy --strict clean
- [ ] pytest baseline preserved (≥ 1230 passed)
- [ ] No new harness simulations introduced — every fix is a real-wire fix

## Why this engagement is HIGH PRIORITY

V1-SCOPE.md declares these features as v1 MUST. The implementation accepts the input shapes and returns success-looking responses, but silently drops or mishandles the documented semantics. Shipping v1 with these open is shipping a spec that lies about what the system does. Each failure is independently verifiable via the existing conformance runner — no new tooling needed; the gap is purely implementation work.

## Reference

- The 9 failures are categorized in commit `bb7aaa7`'s body
- Original surfacing: P5-04 review identified these as the natural successor engagement
- Spec authority: `docs/V1-SCOPE.md`
- Harness simulator inventory: `tools/conformance_runner.py:766-1127`
