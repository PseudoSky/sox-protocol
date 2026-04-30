<!-- SPDX-License-Identifier: Apache-2.0 -->
# ACK / NACK — Primitive Spec

**Protocol version:** 1.0
**Status:** Normative
**Supersedes:** previous model where ACK/NACK were SOX messages with reserved `body.type: sox-ack` sent over ordinary channels

---

## 1. Concept

**ACK (acknowledgement)** and **NACK (negative acknowledgement)** are control-plane signals, not conversation messages. An ACK or NACK updates the server-side pending-state record for a message; it does NOT enter channel history, does NOT appear in replay, and does NOT consume a `seq` slot on any channel.

The primary use case is request-reply coordination: an agent processes a `clarification_request` and signals its progress through the pending-state lifecycle via the `channels__ack` tool.

> **Decision source:** `docs/decisions/ack-mechanism.md` — Option A (dedicated tool)

---

## 2. The `channels__ack` tool

ACK and NACK are issued by calling the dedicated `channels__ack` tool:

```text
channels__ack(
  message_id = "<string>",
  status     = "<received | processing | done | nack>",
  reason     = "<optional string>"   // used with status=nack
)
```

**Input schema:** `spec/operations/channels_ack.input.schema.json`
**Output schema:** `spec/operations/channels_ack.output.schema.json`

The tool updates the server-side pending-state record for `message_id` and returns a confirmation. No message is written to any channel.

---

## 3. Pending-state lifecycle

The ACK status field drives the following lifecycle:

```
pending → received → processing → done
                               → nack
```

| Status | Meaning |
|---|---|
| `received` | The agent has retrieved the message and is about to work on it. |
| `processing` | The agent has begun working on the referenced message. |
| `done` | The agent has finished processing; the message is resolved. |
| `nack` | The agent cannot or will not process the message. The `reason` field SHOULD explain why. |

Transitions MUST be forward-only within a session. The server SHOULD reject a transition that moves backward (e.g., `done → received`).

ACK is explicit — the server does NOT auto-ACK on `recv`. Each status transition must be issued by the agent deliberately.

---

## 4. NACK semantics

A `nack` signals the agent received the message but cannot process it. The sender MAY:

- Retry with backoff.
- Escalate to a different agent.
- Continue under its current assumption.

The `reason` field is free text in v1.0. A standard taxonomy of reason codes is deferred to the enforcer design document.

> **Post-v1:** Standard NACK reason codes (e.g., `CAPACITY_EXCEEDED`, `DOMAIN_MISMATCH`, `TIMEOUT`) will be defined when the enforcer spec lands.

---

## 5. Relationship to channel history

ACKs are control-plane only:

| Property | ACK (v1.0) |
|---|---|
| Appears in channel replay | No |
| Counted in channel `seq` | No |
| Visible in `recv` drain | No |
| Stored in pending-state record | Yes |
| Observable by audit consumers | Via `sox/acks` derived channel (see §6) |

The previous model (ACK as a `sox-ack` body-type message over ordinary channels) is **removed**. The `spec/envelopes/sox-ack.schema.json` and `spec/envelopes/sox-nack.schema.json` files remain valid but now define the body schemas for `channels__ack` tool responses, not channel messages.

---

## 6. `sox/acks` derived channel (optional)

For audit consumers that need an ACK feed, the server MAY emit a derived `sox/acks` channel. This channel is server-emitted (not written by agents) and carries structured ACK events:

```json
{
  "message_id": "<string>",
  "agent_id":   "<string>",
  "status":     "received | processing | done | nack",
  "reason":     "<string | null>",
  "acked_at":   "<number — Unix epoch seconds>"
}
```

Downstream systems that require ACK visibility MUST subscribe to `sox/acks`; they MUST NOT rely on ACK messages appearing in the originating channel.

The `sox/` prefix is reserved for server-emitted derived channels and MUST NOT be used by agents.

---

## 7. Protocol-layer delivery vs. application-layer ACK

These two concepts remain distinct:

| Layer | Guarantee | Mechanism |
|---|---|---|
| Protocol delivery | At-least-once. A stored message will be returned by `recv` for each subscriber. | Backing store atomicity |
| Application ACK | Control signal. The agent reports its processing progress for the pending-state record. | `channels__ack` tool |

---

## 8. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | ACKs do NOT travel over channels; they update the pending-state record directly |
| Pending state ([pending-state.md](pending-state.md)) | `channels__ack` is the sole writer to pending-state status transitions |
| Groups / fan-out ([groups.md](groups.md)) | Group messages require one ACK per recipient; tracked individually for fan-out collect |
| Sequence numbers ([sequence-numbers.md](sequence-numbers.md)) | ACKs do not consume `seq` slots |
| Deadlock detection | `delivered_to` in the envelope plus `reply_to` provide the wait graph; ACK status feeds the resolution signal |
