# ACK / NACK — Primitive Spec

**Protocol version:** 1.0  
**Status:** Normative

---

## 1. Concept

**ACK (acknowledgement)** and **NACK (negative acknowledgement)** are application-level signals that a receiver sends back to the originating agent to confirm receipt, acceptance, or rejection of a message.

SOX does not have a transport-layer ACK/NACK mechanism; every delivered message is considered consumed at the protocol layer (at-least-once delivery). ACK and NACK are SOX protocol messages with reserved `body.type` values, sent back over ordinary channels.

The primary use case is request-reply coordination: an agent sends a `clarification_request` with a `correlation_id`, and the receiver replies with a `sox-ack` or `sox-nack` referencing the same `correlation_id`.

---

## 2. Reserved body types

| `body.type` | Meaning | Schema |
|---|---|---|
| `sox-ack` | The referenced message was received and accepted. | [spec/envelopes/sox-ack.schema.json](../envelopes/sox-ack.schema.json) |
| `sox-nack` | The referenced message was received but rejected or cannot be processed. | [spec/envelopes/sox-nack.schema.json](../envelopes/sox-nack.schema.json) |

---

## 3. ACK semantics

A `sox-ack` message signals that the receiver:

- Received the referenced message (identified by `correlation_id`).
- Accepted it for processing or has already processed it.

An ACK does NOT guarantee that the receiver completed its response or that any subsequent action was taken successfully. It is a lightweight delivery confirmation.

**When to send an ACK:**

- After processing a `clarification_request` and before or alongside sending the `clarification_reply`.
- To confirm receipt of a `handoff_ready` signal before the handoff work begins.

**When NOT to send an ACK:**

- For broadcast messages where no specific action is expected.
- For presence updates.
- For status updates that are fire-and-forget.

---

## 4. NACK semantics

A `sox-nack` message signals that the receiver:

- Received the referenced message.
- Cannot or will not process it, for a stated reason.

A NACK SHOULD include a `reason` field in the body. The sender may retry (with backoff), escalate, or continue under its current assumption.

**When to send a NACK:**

- The requested information is outside the receiver's knowledge domain.
- The receiver is `busy` and cannot process the request before the sender's decision point.
- The request is malformed or missing required context.

---

## 5. Wire format

An ACK or NACK is a standard SOX message sent to a channel. The `correlation_id` field MUST be set to the `message_id` of the message being acknowledged.

**Recommended routing:** Send the ACK/NACK back to:

- The originating DM channel (`agent:<sender-id>`), or
- The originating group/task channel if the conversation is group-scoped, or
- A thread channel (`thread:<original-message-id>`) to keep the ack out of the main channel.

The `correlation_id` field ties the ACK/NACK to the original request regardless of which channel the response is sent on.

See [spec/envelopes/sox-ack.schema.json](../envelopes/sox-ack.schema.json) and [spec/envelopes/sox-nack.schema.json](../envelopes/sox-nack.schema.json) for the normative body schemas.

---

## 6. Protocol-layer delivery vs application-layer ACK

These two concepts are distinct:

| Layer | Guarantee | Mechanism |
|---|---|---|
| Protocol delivery | At-least-once. A stored message will be returned by `recv` for each subscriber. | Backing store atomicity (§3 of backing-store.md) |
| Application ACK | Advisory. The sender learns the receiver has seen and accepted the message. | `sox-ack` message over a channel |

Agents MUST NOT confuse protocol delivery with application-layer acknowledgement. The backing store does not know whether a receiver acted on a message; only an explicit `sox-ack` confirms that.

---

## 7. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | ACK/NACK messages travel over ordinary channels |
| DMs ([dms.md](dms.md)) | Primary routing target for ACK/NACK in 1:1 conversations |
| Threads ([threads.md](threads.md)) | Thread channels keep ACK/NACK scoped to the originating message |
| Trace IDs ([trace-ids.md](trace-ids.md)) | `correlation_id` is the mandatory link between request and ACK/NACK |
| Pending state ([pending-state.md](pending-state.md)) | An outstanding ACK/NACK wait is tracked in application state, not protocol state |
