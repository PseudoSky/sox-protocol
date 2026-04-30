# Threads — Primitive Spec

**Protocol version:** 1.0  
**Status:** Normative

---

## 1. Concept

A **thread** is a scoped sub-conversation anchored to a specific parent message. Threads allow agents to discuss a particular message without polluting the parent channel with replies.

SOX implements threads as ordinary channels whose name encodes the parent message ID. No separate protocol mechanism is required.

---

## 2. Naming convention

The recommended thread channel name format is:

```text
thread:<parent-message-id>
```

Example: to reply to message `msg-0000042`, send to channel `thread:msg-0000042`.

Participants in a thread subscribe to the thread channel explicitly; they are not auto-enrolled by virtue of subscribing to the parent channel.

---

## 3. Lifecycle

A thread channel is created implicitly when the first reply is sent. It expires subject to the backing store's retention policy (default: 24 hours of inactivity).

There is no protocol-level "close thread" operation. Threads are considered active as long as messages are being stored.

---

## 4. Relationship to parent channel

The thread channel and the parent channel are independent in the protocol. A message sent to `thread:msg-0000042` does NOT appear on the parent channel. Agents that want thread replies to also appear on the parent channel must implement application-level fan-out (send the same message to both channels).

The link between a thread message and its parent is by naming convention only. The `correlation_id` field on the wire envelope SHOULD be set to the parent `message_id` to make the relationship explicit in message metadata.

---

## 5. Operations

Threads use the standard channel operations.

### Starting a thread

```text
{{send_tool}}(
  channel        = "thread:msg-0000042",
  body           = { "type": "clarification_reply", "answer": "..." },
  correlation_id = "msg-0000042"
)
```

### Subscribing to a thread

```text
{{subscribe_tool}}(pattern="thread:msg-0000042")
```

### Reading a thread

```text
{{recv_tool}}(channels=["thread:msg-0000042"])
```

---

## 6. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | A thread channel is an ordinary channel |
| Groups ([groups.md](groups.md)) | Thread participants are a subset of the parent group; self-selected |
| ACK/NACK ([ack-nack.md](ack-nack.md)) | ACK/NACK within a thread is sent to the thread channel |
| Trace IDs ([trace-ids.md](trace-ids.md)) | `correlation_id` = parent `message_id` makes the parent-thread link explicit |
| Sequence numbers ([sequence-numbers.md](sequence-numbers.md)) | Per-thread ordering is the same as any channel |
