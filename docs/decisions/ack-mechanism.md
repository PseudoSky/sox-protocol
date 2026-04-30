# Decision: ack-mechanism

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q3 (ACK / processing signal)

## Context
ACK is the signal that an agent has received and is processing (or has finished processing) a specific message. It feeds `list_pending` and the enforcer stop-block. Modeling it as a dedicated tool minimizes token cost and keeps the conversation log clean; modeling it as a reserved envelope (`{"type": "sox/ack", "ref": "<msg_id>"}`) reuses existing primitives but spends a full send round-trip and adds a record to thread history.

## Decision
**Option A — Dedicated `channels__ack` tool.** ACK is a control verb, not a message. The tool takes a message-id (and optionally a status: `received` | `processing` | `done` | `nack`) and updates the server-side pending-state record. ACKs do not appear in channel replay or thread history. If a downstream system needs an audit trail of ACKs, it subscribes to a server-emitted `sox/acks` derived channel (parallel to the `sox/presence` pattern from heartbeat-mechanism).

## Rationale
Same architectural logic as heartbeat: ACK is control-plane state for the enforcer, not content for the conversation. Putting ACKs in thread history clutters every replay with bookkeeping (each substantive message could spawn 2–4 ACK envelopes from multiple recipients), inflates token cost for any agent doing replay, and forces ACK-filtering into every reader. The `dispatch-prompt-budget-contract.md` finding frames every additional message in a chain as a non-trivial budget tax. A dedicated tool is also cheaper in tool-call tokens than a `channels__send` with a structured envelope. Consistency with the heartbeat decision is itself a virtue — both are control-plane signals with the same shape (write via tool, derived channel for observers). Trade-off accepted: external systems that want ACK visibility must subscribe to the derived channel rather than reading the main thread; documented up-front.

## Consequences
- Positive: Cleanest token cost on the dominant path. ACK is a single short tool call, no envelope construction, no thread bloat.
- Positive: `list_pending` reads directly from the same pending-state record `channels__ack` writes. Single source of truth.
- Positive: Thread history is purely substantive content. Replay stays cheap and human-readable.
- Negative: Two surfaces to spec for observers (ack tool + derived channel), like heartbeat.
- Negative: Interop with external systems that already model ACK as a message (rare in agent contexts) requires a small adapter. Acceptable.
- Spec impact: `spec/ack.md` defines `channels__ack` verb (params: `message_id`, `status`), the pending-state lifecycle (`pending → received → processing → done | nack`), and the optional `sox/acks` derived channel. `spec/enforcer.md` references the pending-state record as the stop-block input. `spec/list_pending.md` (per vision doc) reads the same record.

## Open questions for follow-up
- Whether `nack` carries a reason code and whether the protocol defines a standard taxonomy or leaves it free-text. Defer to enforcer design doc.
- Auto-ACK on recv vs. explicit ACK after processing. Lean explicit (status transitions are meaningful); confirm against `list_pending` semantics.
- Whether group messages require N ACKs (one per recipient) tracked individually. Yes — needed for fan-out collect; see fanout-collect decision.
