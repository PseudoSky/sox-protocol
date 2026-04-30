# Direct Messages (DMs) — Primitive Spec

**Protocol version:** 1.0  
**Status:** Normative

---

## 1. Concept

A **direct message (DM)** is a private channel between one sender and one intended recipient. In SOX, DMs are not a separate protocol primitive — they are channels whose name encodes the intended recipient's agent ID.

This means DM delivery relies on the recipient subscribing to their own DM channel. The protocol does not provide a "push to agent" mechanism; the send-and-receive model is identical to group channels.

---

## 2. Naming convention

The recommended DM channel name format is:

```text
agent:<recipient-agent-id>
```

Example: to send a DM to agent `agent-beta`, send to channel `agent:agent-beta`.

Each agent SHOULD subscribe to `agent:<own-agent-id>` at startup so that DMs addressed to it are received automatically.

```text
{{subscribe_tool}}(pattern="agent:agent-beta")
```

---

## 3. Privacy model (v1.0)

**DMs are not confidential in v1.0.** Any agent subscribed to the channel `agent:<target>` receives the messages, not just the named agent. The naming convention provides routing by convention, not enforcement.

Confidentiality enforcement (channel ACLs backed on verified identity) is deferred to v1.0 per the identity roadmap (see [spec/ports/identity.md](identity.md) and the `channel-acls-backed-on-verified-identity` protocol TODO).

Agents MUST NOT transmit secrets or credentials over DM channels in v1.0.

---

## 4. Operations

DMs use the standard channel operations.

### Sending a DM

```text
{{send_tool}}(
  channel = "agent:agent-beta",
  body    = { "type": "clarification_request", ... },
  correlation_id = "req-007"
)
```

### Receiving DMs

The recipient drains their DM channel along with other subscribed channels:

```text
{{recv_tool}}(channels=["agent:agent-beta"])
```

or as part of a full drain:

```text
{{recv_tool}}()
```

### Replying to a DM

The reply is a new message sent back to the sender's `agent:<sender-id>` channel, using the same `correlation_id`:

```text
{{send_tool}}(
  channel        = "agent:agent-alpha",
  body           = { "type": "clarification_reply", "answer": "..." },
  correlation_id = "req-007"
)
```

---

## 5. Self-send exclusion

As of v1.0, agents receive their own sent messages by default (the backing store does not filter `sender == agent_id`). The `self-send-exclusion` feature (filter own messages in `recv` and `watch`) is a v1 protocol TODO.

Until self-send exclusion is implemented, agents SHOULD ignore messages whose `sender` field matches their own `agent_id`.

---

## 6. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | DMs are channels; all channel semantics apply |
| Groups ([groups.md](groups.md)) | A DM is a 1:1 specialisation; no conflict |
| ACK/NACK ([ack-nack.md](ack-nack.md)) | ACK/NACK messages are sent back to the originating DM channel |
| Trace IDs ([trace-ids.md](trace-ids.md)) | `correlation_id` links a DM to its reply |
| Identity ([spec/ports/identity.md](../ports/identity.md)) | Verified identity is required for true DM privacy; not enforced in v1.0 |
