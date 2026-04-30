# Sequence Numbers — Primitive Spec

**Protocol version:** 1.0  
**Status:** Normative

---

## 1. Concept

SOX does not use explicit integer sequence numbers in v1.0. Instead, the combination of **`sent_at`** (Unix epoch seconds, floating-point) and **`message_id`** (backing-store-assigned unique identifier) serves as the ordering key within a channel.

This section specifies the ordering guarantees SOX provides, the limitations of the v1.0 ordering model, and the intended evolution toward stronger ordering.

---

## 2. Ordering fields

### 2.1 `sent_at`

- Type: `number` (JSON), floating-point, Unix epoch seconds.
- Assigned by the backing store at the moment it durably accepts the message.
- Used to sort messages within a single channel in ascending order.

### 2.2 `message_id`

- Type: `string`, non-empty.
- Assigned by the backing store; unique within the store.
- Used as a tie-break when two messages in the same channel have identical `sent_at` values.
- Also used by threads and trace IDs to reference a specific message.

---

## 3. Per-channel ordering guarantee

Within a single channel, the backing store MUST return messages to a given agent in ascending `sent_at` order. When two messages share the same `sent_at` timestamp (same-millisecond concurrent sends from different agents), the store's internal tie-break order applies and MUST be consistent across all `recv` calls to the same agent.

---

## 4. Cross-channel ordering guarantee

**None.** Messages across different channels in a single `recv` response may appear in any order. Agents MUST NOT assume any cross-channel ordering.

---

## 5. v1.0 limitations

- **No vector clocks.** SOX v1.0 uses wall-clock time (`sent_at`) for ordering. In a distributed deployment with multiple backing-store nodes, clock skew can produce inconsistent ordering. Vector-clock or hybrid-logical-clock causality tracking is a post-v1 item.
- **No global sequence number.** There is no monotonically increasing integer sequence number across channels or across all messages in the store.
- **No causal ordering.** SOX does not guarantee that a message sent in response to another message appears after it in any global ordering.

---

## 6. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | Per-channel `sent_at` ordering is the channel delivery contract |
| Threads ([threads.md](threads.md)) | Thread channels have independent per-channel ordering; thread order is independent of parent channel order |
| Trace IDs ([trace-ids.md](trace-ids.md)) | `correlation_id` links related messages but does not impose an ordering constraint |
| Pending state ([pending-state.md](pending-state.md)) | `sent_at` is used for timeout tracking in application-level pending state |
