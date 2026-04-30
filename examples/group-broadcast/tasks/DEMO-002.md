# DEMO-002 — Parallel implementation sprint with status broadcasts

**Ticket:** DEMO-002
**Channel:** `ticket:DEMO-002`
**Agents:** implementer, reviewer, docs-writer

## Task description

Three agents are working in parallel on DEMO-002:

- **implementer** — building the core feature (`POST /orders` handler).
- **reviewer** — conducting ongoing code review of landed commits.
- **docs-writer** — writing endpoint documentation.

All three subscribe to `ticket:DEMO-002` at startup for coordination.

## Broadcast protocol

When the implementer completes a meaningful sub-task, it broadcasts a
`status_update` message to `ticket:DEMO-002`. The reviewer and docs-writer
update their working context on their next drain without replying.

This is a **broadcast-only** demo. No replies are expected or sent.
Receivers acknowledge by updating their internal state only.

## Sub-tasks

### implementer

1. Implement `POST /orders` handler with domain model.
2. Broadcast status after completing the handler.
3. Write unit tests.
4. Broadcast status after tests pass.

### reviewer

1. Subscribe to `ticket:DEMO-002`.
2. Wait for first implementer broadcast at each drain checkpoint.
3. Queue a code-review batch when a "handler complete" update arrives.
4. Continue reviewing without replying to the channel.

### docs-writer

1. Subscribe to `ticket:DEMO-002`.
2. Drain at decision points.
3. When a "handler complete" broadcast arrives, start writing endpoint docs
   with real commit references from the broadcast body.
4. Continue without replying to the channel.

## Acceptance criteria

- The implementer sends at least one `status_update` to `ticket:DEMO-002`.
- Both reviewer and docs-writer drain and record the update in their state.
- Neither reviewer nor docs-writer sends a reply message to the channel.
- All three agents' final states show the broadcast was received.
