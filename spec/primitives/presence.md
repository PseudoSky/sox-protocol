<!-- SPDX-License-Identifier: Apache-2.0 -->
# Presence — Primitive Spec

**Protocol version:** 1.0  
**Status:** Normative

---

## 1. Concept

**Presence** describes the operational state of an agent as visible to its peers — whether it is actively processing, idle, or unavailable. Presence is a first-class coordination signal: knowing that a peer is active before sending a clarification request allows an agent to choose its best-guess assumption strength.

SOX implements presence as ordinary messages sent to a presence channel. There is no dedicated presence sub-protocol; no heartbeat or keep-alive mechanism is built into v1.0.

---

## 2. Presence channels

The recommended presence channel name format is:

```text
presence:<agent-id>
```

Example: `presence:agent-alpha`

An agent publishes its own presence by sending to its presence channel. Peers subscribe to presence channels of agents they care about.

A global presence broadcast channel may also be used:

```text
presence:all
```

---

## 3. Presence states

| State | Meaning |
|---|---|
| `active` | Agent is running and processing normally. |
| `idle` | Agent is running but not actively working (e.g. waiting for user input). |
| `busy` | Agent is mid-task and may not drain its inbox promptly. |
| `unavailable` | Agent is shutting down or paused. |

These states are advisory. The protocol does not enforce any behaviour based on a peer's presence state.

---

## 4. Presence message format

A presence message uses the standard channel envelope. The `body` SHOULD follow this convention:

```json
{
  "type": "presence",
  "state": "<active | idle | busy | unavailable>",
  "agent_id": "<string>",
  "detail": "<optional string — free-form>",
  "timestamp": "<number — Unix epoch seconds>"
}
```

The `type` field MUST be `"presence"` to allow receivers to dispatch on it. All other fields are advisory.

---

## 5. Protocol guarantees

- Presence messages are delivered with the same at-least-once semantics as all SOX messages.
- The protocol does not guarantee freshness: an agent may be `unavailable` by the time a peer reads its last `active` presence update. Peers MUST treat presence as a hint, not a guarantee.
- There is no implicit presence timeout or expiry in v1.0. Presence state persists in the backing store until the retention window expires or a new presence message overwrites it.

---

## 6. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | Presence channels are ordinary channels |
| Groups ([groups.md](groups.md)) | Group members may publish presence to the group channel or to their own presence channel |
| ACK/NACK ([ack-nack.md](ack-nack.md)) | Presence updates do not require acknowledgement |
| Pending state ([pending-state.md](pending-state.md)) | An agent marked `unavailable` may have a non-empty inbox; this is expected and handled by the at-least-once delivery contract |

---

## 7. v1.0 limitations

- No server-side presence tracking. The backing store holds presence messages as ordinary messages; there is no aggregated "current state" query.
- No automatic `unavailable` broadcast on crash. An agent that crashes does not emit a final presence message. Peers SHOULD treat a long absence of `active` updates as a proxy for unavailability.
- Heartbeat-based presence (periodic `active` messages at a configured interval) is a v1 implementation recommendation but not a protocol requirement in v1.0.
