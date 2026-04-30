<!-- SPDX-License-Identifier: Apache-2.0 -->
# Pending State — Primitive Spec

**Protocol version:** 1.0  
**Status:** Normative

---

## 1. Concept

**Pending state** describes the set of messages an agent has sent but for which it has not yet received a corresponding reply or acknowledgement. It is an application-level concept: the SOX protocol does not track whether a sent message was replied to. Pending state lives in the agent's reasoning context, not in the backing store.

Understanding pending state is essential to the speculative-then-reconcile discipline: an agent works under best-guess assumptions while pending state is non-empty and reconciles when replies arrive.

---

## 2. Relationship to protocol state

The protocol exposes two signals relevant to pending state:

| Signal | Protocol field | Location |
|---|---|---|
| Outbound send recorded | `sends_since_last_drain` in enforcer `State` | `spec/schemas/state.schema.json` |
| Potential inbox non-empty | Inferred from `sends_since_last_drain > 0` in enforcer `decide()` | `spec/schemas/decision.schema.json` |

The enforcer uses `sends_since_last_drain` as a heuristic to infer that the agent may have pending replies. It does NOT track individual request-reply pairs; that is the agent's responsibility.

---

## 3. Application-level pending state model

An agent managing pending state SHOULD maintain (in its own context, not in the protocol):

```text
pending_requests: [
  {
    correlation_id:  "<string>",
    channel:         "<string — where reply is expected>",
    assumption:      "<string — what the agent is proceeding under>",
    sent_at:         "<number — Unix epoch seconds>",
    status:          "<waiting | acked | replied | nacked | timed-out>"
  },
  ...
]
```

On each `recv` drain, the agent SHOULD scan returned messages for `correlation_id` values that match entries in `pending_requests` and update their status.

---

## 4. Pending state transitions

```text
[sent] → waiting
waiting → acked       (recv returns a sox-ack with matching correlation_id)
waiting → replied     (recv returns a clarification_reply with matching correlation_id)
waiting → nacked      (recv returns a sox-nack with matching correlation_id)
waiting → timed-out   (agent decides enough time has elapsed without reply)
```

`timed-out` is an agent-determined transition; the protocol has no timeout mechanism in v1.0.

---

## 5. Speculative-execute-while-pending

While one or more requests are in `waiting` state:

1. The agent SHOULD continue work under its recorded best-guess assumption.
2. The agent SHOULD drain its inbox at every major decision checkpoint.
3. On a `replied` transition, the agent SHOULD reconcile the reply with its in-progress work per the speculative-then-reconcile recipe in `spec/discipline/discipline.md`.
4. On a `timed-out` transition, the agent SHOULD treat the best-guess assumption as confirmed for practical purposes, while noting that no confirmation was received.

---

## 6. Protocol-level pending state (enforcer)

The cadence enforcer tracks a coarser pending state for reminders only. Its `sends_since_last_drain` counter is reset on every `recv`, regardless of whether any reply was found. The enforcer does not know about individual requests; it only knows "the agent has sent N times since it last drained."

---

## 7. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| ACK/NACK ([ack-nack.md](ack-nack.md)) | Receipt of `sox-ack` / `sox-nack` transitions pending state |
| Trace IDs ([trace-ids.md](trace-ids.md)) | `correlation_id` is the key that links a reply to a pending request |
| Channels ([channels.md](channels.md)) | The reply channel determines where to drain for a pending reply |
| Sequence numbers ([sequence-numbers.md](sequence-numbers.md)) | `sent_at` provides the timestamp for timeout calculations |
