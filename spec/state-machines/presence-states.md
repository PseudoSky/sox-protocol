# Agent Presence States — State Machine

**Protocol version:** 1.0  
**Status:** Normative

---

## 1. Overview

An agent's presence state describes its current operational posture as visible to peers. Presence transitions are self-reported via presence channel messages; the protocol does not track presence in the backing store as a separate record type.

---

## 2. States

| State | Description |
|---|---|
| `offline` | Agent is not running. No presence message has been received in the retention window. (Inferred by absence; not a sent state.) |
| `starting` | Agent has started but has not yet subscribed to its channels or loaded its discipline. Transient. |
| `active` | Agent is running and processing normally. Draining inbox at the expected cadence. |
| `idle` | Agent is running but not actively working (e.g. awaiting user instruction). May be slower to drain. |
| `busy` | Agent is mid-task with heavy workload. Inbox draining may be delayed beyond the normal cadence. |
| `unavailable` | Agent is shutting down or suspended. Will not drain inbox. |

---

## 3. State transition diagram

```mermaid
stateDiagram-v2
    [*] --> starting : agent process starts

    starting --> active : subscriptions registered;\ndiscipline loaded

    active --> idle : agent task completes;\nawaiting next instruction
    active --> busy : agent load high;\ncadence may be degraded
    active --> unavailable : shutdown initiated

    idle --> active : new task received
    idle --> unavailable : timeout or shutdown

    busy --> active : load normalises
    busy --> unavailable : shutdown initiated

    unavailable --> [*] : process exits

    note right of offline
        Inferred by absence of presence messages
        within the retention window.
        Not an explicitly sent state.
    end note
```

---

## 4. Transition rules

- An agent SHOULD publish a presence message whenever it transitions to a new state.
- An agent MUST publish `unavailable` before shutting down if it has time to do so (graceful shutdown). A crashed agent will not publish `unavailable`.
- An agent SHOULD publish `active` at startup once it has subscribed to its channels.
- An agent MAY publish `active` periodically as a heartbeat (recommended: every 60 seconds). This allows peers to infer liveness even without explicit state transitions.

---

## 5. Peer interpretation rules

Peers receiving presence updates SHOULD:

- Treat `active` updates as a liveness signal; absence of `active` for longer than the heartbeat interval SHOULD be treated as a proxy for `offline`.
- Not assume `unavailable` means "permanently gone" — the agent may restart.
- Not block on presence state; SOX is an async protocol. If a peer is `busy` or `unavailable`, the sender continues under its best-guess assumption and reconciles when the peer replies.

---

## 6. Protocol guarantees

- Presence messages have the same at-least-once delivery semantics as all SOX messages.
- The protocol does not guarantee freshness. A peer may read an `active` presence message that is minutes old. Treat presence as a hint.
- There is no server-side aggregated presence state in v1.0. Presence is message-driven.

---

## 7. Interaction with cadence enforcer

The cadence enforcer (see `spec/schemas/state.schema.json` and `spec/schemas/decision.schema.json`) does not inspect presence state. Its decisions are based solely on tool-call event counters. Presence state is orthogonal to the enforcer.

However, an agent in `busy` or `unavailable` state that has pending sends will trigger the enforcer's `stop_requested` block (if `force_drain_on_stop = true`) on its own shutdown path, prompting it to drain before exiting — which is correct behaviour.
