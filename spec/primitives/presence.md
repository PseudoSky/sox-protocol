<!-- SPDX-License-Identifier: Apache-2.0 -->
# Presence — Primitive Spec

**Protocol version:** 1.0
**Status:** Normative
**Supersedes:** previous spec that stated "no dedicated presence sub-protocol; no heartbeat or keep-alive mechanism is built into v1.0"

---

## 1. Concept

**Presence** describes the operational state of an agent as visible to its peers. SOX v1.0 implements presence through a dedicated **`channels__heartbeat` tool** that updates a server-tracked liveness record. Heartbeats are control-plane signals — they do NOT produce messages in any channel and do NOT appear in replay.

Observers that need a feed of presence events subscribe to the server-emitted **`sox/presence`** derived channel, which publishes coalesced state-transition events (not raw heartbeats).

> **Decision source:** `docs/decisions/heartbeat-mechanism.md` — Option A (dedicated tool)

---

## 2. The `channels__heartbeat` tool

An agent signals liveness by calling the heartbeat tool:

```text
channels__heartbeat(
  status = "<online | busy | offline>",
  ttl    = <integer seconds, optional>
)
```

**Input schema:** `spec/operations/channels_heartbeat.input.schema.json`
**Output schema:** `spec/operations/channels_heartbeat.output.schema.json`

The tool updates the server-side liveness record for the calling agent (keyed by `agent_id` from the verified connection identity). No message is written to any channel.

The `agent_id` is NOT a parameter — it is derived from the authenticated connection (see `spec/ports/identity.md`).

---

## 3. Presence states

| State | Meaning |
|---|---|
| `online` | Agent is running and available to process messages. |
| `busy` | Agent is mid-task and may not drain its inbox promptly. |
| `offline` | Agent is shutting down or paused; peers should not expect prompt responses. |

The server tracks an additional derived state:

| Derived state | Trigger |
|---|---|
| `stale` | No heartbeat received within the stale threshold (default: 30 seconds). |
| `offline` (server-derived) | No heartbeat received within the offline threshold (default: 90 seconds). |

Default heartbeat interval: 10 seconds. Agents SHOULD call `channels__heartbeat` at least once every 10 seconds to maintain `online` status.

---

## 4. Liveness state machine

```
[new connection]
      │
      ▼
   online ──heartbeat(online/busy)──► online/busy
      │
      │  no heartbeat for 30s
      ▼
    stale
      │
      │  no heartbeat for 90s
      ▼
   offline ◄──heartbeat(offline)
```

State transitions are server-computed; the agent only sends the `status` hint. The server MAY override a hint (e.g., clamp `online` to `stale` if heartbeat intervals are too infrequent).

---

## 5. `sox/presence` derived channel

The server emits presence-change events on the reserved `sox/presence` channel. Events are **coalesced** — one event per state transition, not one per heartbeat:

```json
{
  "event":     "agent_online | agent_offline | agent_stale | agent_busy",
  "agent_id":  "<string>",
  "state":     "online | busy | stale | offline",
  "changed_at": "<number — Unix epoch seconds>"
}
```

Agents MAY subscribe to `sox/presence` to observe peer liveness:

```text
{{subscribe_tool}}(pattern="sox/presence")
```

The `sox/` prefix is reserved for server-emitted channels. Agents MUST NOT write to `sox/presence`.

> **Post-v1:** Whether `sox/presence` subscription requires an observer ACL role is deferred to the auth middleware design. In v1.0, any authenticated agent may subscribe.

---

## 6. Relationship to other presence signals

The previous model (agents publishing `presence` body-type messages to `presence:<agent-id>` channels) is **deprecated** as the primary mechanism. It remains technically possible (presence channels are just regular channels) but:

- It is NOT server-tracked; the server liveness record is only updated by `channels__heartbeat`.
- The enforcer stop-block uses the server liveness record, not channel-published presence.
- `list_pending` reads from the same liveness record as `channels__heartbeat`.

Agents SHOULD use `channels__heartbeat` for liveness. The `presence:<agent-id>` channel pattern MAY be used for rich presence payloads (current task description, load metrics) as a complement, but MUST NOT be relied upon for protocol-level liveness.

---

## 7. Protocol guarantees

- Heartbeat writes are non-blocking and do not enter channel history.
- The server MUST NOT lose the liveness record due to a backing-store failure; presence state MAY be held in a fast ephemeral store sidecar.
- There is no automatic `offline` broadcast on agent crash — the server derives `stale`/`offline` from timeout, not from a final signal. Peers observing `sox/presence` see the server-derived transition event.

---

## 8. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | `sox/presence` is a server-emitted channel; heartbeats do NOT write to channels |
| ACK/NACK ([ack-nack.md](ack-nack.md)) | Presence updates do not require acknowledgement |
| Pending state ([pending-state.md](pending-state.md)) | `list_pending` reads from the same liveness record that `channels__heartbeat` writes |
| Identity ([spec/ports/identity.md](../ports/identity.md)) | `agent_id` is derived from the verified connection identity, not from tool call parameters |
