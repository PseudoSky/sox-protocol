<!-- SPDX-License-Identifier: Apache-2.0 -->
# Trace IDs — Primitive Spec

**Protocol version:** 1.0  
**Status:** Normative

---

## 1. Concept

A **trace ID** in SOX is the `correlation_id` field on the wire envelope — a caller-supplied string token that logically links related messages across one or more channels. It is the primary mechanism for:

- Request-reply pairing (sender sets `correlation_id`; receiver echoes it in the reply).
- Application-level deduplication (at-least-once delivery mitigation).
- Thread anchoring (a thread channel `thread:<parent-message-id>` links via the parent message's `message_id`).
- Cross-channel conversation tracing.

---

## 2. Wire representation

The `correlation_id` field appears on every SOX message envelope:

```json
{
  "channel":        "...",
  "sender":         "...",
  "body":           {...},
  "correlation_id": "<string | null>",
  "sent_at":        1714300000.0,
  "message_id":     "msg-0000001"
}
```

- Type: `string` (max 128 characters) or `null`.
- Set by the **sender** at send time; stored verbatim; echoed back in `recv` output.
- The protocol does not parse or interpret the value — it is opaque.

---

## 3. Semantics

### 3.1 Request-reply pairing

The sender sets a unique `correlation_id` on a request message. The receiver includes the same `correlation_id` on its reply. The sender matches incoming messages against its pending requests by `correlation_id`.

### 3.2 At-least-once deduplication

Because SOX provides at-least-once delivery, an agent MAY receive the same logical message more than once after a crash-and-restart scenario. Setting a deterministic `correlation_id` (e.g. derived from the task and step identifiers) allows receivers to detect and discard duplicates by tracking previously seen `correlation_id` values.

### 3.3 Thread anchoring

When an agent spawns a thread channel (`thread:<parent-message-id>`), it SHOULD set `correlation_id` = the parent `message_id` on all thread messages. This makes the parent-thread relationship explicit in message metadata.

---

## 4. Uniqueness requirements

- The protocol does NOT enforce `correlation_id` uniqueness. Two different senders may use the same value.
- Senders SHOULD use UUIDs or a structured format like `<agent-id>-<counter>` to avoid collision.
- Receivers SHOULD scope deduplication by `(sender, correlation_id)` rather than `correlation_id` alone.

---

## 5. v1.0 limitations

- `correlation_id` is application-assigned; the protocol does not generate or validate it.
- There is no distributed tracing integration (e.g. W3C TraceContext header); adding a `traceparent` field in `body` is a valid application-level extension.
- The protocol does not provide a "trace" query (retrieve all messages in a conversation by `correlation_id`). That is a backing-store query concern, not a protocol operation.

---

## 6. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| ACK/NACK ([ack-nack.md](ack-nack.md)) | `correlation_id` is the mandatory link from ACK/NACK to the original request |
| Threads ([threads.md](threads.md)) | Thread messages SHOULD set `correlation_id` to the parent `message_id` |
| Pending state ([pending-state.md](pending-state.md)) | Pending state is indexed by `correlation_id` |
| Channels ([channels.md](channels.md)) | `correlation_id` is stored and echoed verbatim; channel semantics are unaffected |
| Sequence numbers ([sequence-numbers.md](sequence-numbers.md)) | `correlation_id` does not impose ordering; ordering is determined by `sent_at` |
