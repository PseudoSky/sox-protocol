<!-- SPDX-License-Identifier: Apache-2.0 -->
# BackingStore Port — Behaviour Contract

**Version:** 1.0  
**Status:** Normative  
**Scope:** Language-neutral. This document specifies required behaviour, not a language binding. Python, TypeScript, Rust, and all other implementations express this contract in their own idioms (ABC, interface, trait, etc.). If this document and any language-specific binding disagree, this document wins.

---

## 1. Purpose

The `BackingStore` port is the south / driven adapter port of the SOX hexagonal architecture. It is the persistence boundary between the SOX MCP server and a storage backend. Its sole job is: accept messages, hold them durably (to the degree the backend supports), and deliver them to subscribing agents reliably and in order.

Everything the MCP server's four tool handlers do on the persistence side flows through this port. Nothing above the port knows which backend is in use.

---

## 2. Required Methods

A conformant backing-store implementation MUST provide all five methods described below. Omitting any method makes the implementation non-conformant and MUST cause the SOX MCP server to refuse to start.

### 2.1 `send`

**Signature (behaviour description):**  
Accepts a message for a named channel, persists it, and returns a `(message_id, sent_at)` pair.

**Parameters:**

- `channel` (string, non-empty): the target channel name.
- `sender` (string, non-empty): the `agent_id` of the sending agent.
- `body` (object): opaque JSON object payload.
- `correlation_id` (string or null): optional caller-supplied token.

**Returns:** A pair of `(message_id: string, sent_at: number)` where `message_id` is a backing-store-assigned unique identifier for the message and `sent_at` is the Unix epoch seconds (floating-point) at which the store accepted the message.

**Atomicity:** A successful return from `send` MUST guarantee that the message is visible to all matching subscribers immediately. There is no "pending" or "in-flight" intermediate state visible to readers after `send` returns successfully.

**Failure:** If the store cannot durably accept the message, `send` MUST raise/return an error. A failed `send` MUST NOT result in a partially-persisted message that could be returned by a subsequent `recv`.

### 2.2 `recv`

**Signature (behaviour description):**  
Atomically drains pending messages for a given agent from one or more channels and marks them as delivered to that agent.

**Parameters:**

- `agent_id` (string, non-empty): the draining agent's identifier.
- `channels` (list of strings, or null): the channels to drain. When null, all channels to which `agent_id` is subscribed are drained.
- `max_messages` (integer, 1–1000): the upper bound on messages returned in one call. Default 50.

**Returns:** A list of message objects, each conforming to `spec/schemas/message.schema.json`. Within a single channel, messages are ordered by `sent_at` ascending. The order of messages across different channels in a single response is unspecified.

**Atomicity (per-agent):** The set of messages returned in one `recv` call MUST be marked delivered to `agent_id` as a single atomic operation. A message returned to `agent_id` in this call MUST NOT be returned to `agent_id` again in any subsequent `recv` call, even if a concurrent `recv` call from a different agent is in flight simultaneously. Concurrent `recv` calls from different agents MUST NOT interfere with each other's delivery sets.

**Non-blocking:** `recv` MUST return immediately with whatever messages are currently available. It MUST NOT block waiting for new messages to arrive.

### 2.3 `subscribe`

**Signature (behaviour description):**  
Registers a subscription: declares that `agent_id` wants to receive messages on channels matching `pattern`.

**Parameters:**

- `agent_id` (string, non-empty): the subscribing agent.
- `pattern` (string, non-empty, max 256 chars): a channel name pattern. Supports Unix-glob `*` wildcard applied to the full channel name. Also supports exact match (no wildcard).

**Returns:** A list of channel name strings that currently exist in the store and match `pattern`. An empty list is a valid return if no matching channels currently exist; the subscription is still registered and will deliver future messages on matching channels.

**Persistence:** Subscriptions MUST be persisted durably so that they survive MCP server restarts. An agent that subscribed before a server restart MUST have its subscription honoured after restart without re-subscribing.

**Idempotency:** Registering the same `(agent_id, pattern)` pair twice MUST be idempotent (no duplicate subscription, no error).

### 2.4 `list_channels`

**Signature (behaviour description):**  
Returns a list of known channels.

**Parameters:**

- `since` (number or null): optional Unix epoch seconds. When provided, returns only channels that have received a message since that timestamp. When null, the implementation SHOULD return channels with at least one subscriber or at least one message in the last 24 hours.

**Returns:** A list of objects, each with at minimum:

- `name` (string): channel name.
- `subscriber_count` (integer, ≥ 0): number of agents currently subscribed.

**NOTE — ambiguity:** The threshold for inclusion when `since` is null ("last 24 hours") is a default recommendation. Implementations MAY expose a different retention window as a configuration parameter; operators MUST document any deviation. This is noted as a TODO in `spec/schemas/tools/list-channels.output.schema.json`.

### 2.5 `watch`

**Signature (behaviour description):**  
An asynchronous generator (or equivalent in the target language) that yields new messages for a given agent as they arrive.

**Parameters:**

- `agent_id` (string, non-empty): the watching agent.

**Yields:** Message objects conforming to `spec/schemas/message.schema.json`, one at a time, as they become available in the backing store.

**Semantics — exactly-once-per-agent per invocation:** Each new message that matches any of `agent_id`'s subscriptions MUST be yielded exactly once by a given `watch` call for that agent. The same message MUST NOT be yielded twice to the same `watch` invocation.

**Semantics — non-duplicating across `watch` calls:** If `watch` is cancelled and restarted (e.g., on MCP server restart), the new `watch` invocation MUST NOT re-yield messages that were already delivered to the agent via a previous `recv` call.

**Semantics — non-blocking production:** The MCP server's listener task holds a long-lived `watch` generator and buffers yielded messages in a local in-memory mailbox. The `watch` generator MUST NOT block the production of messages on behalf of other agents; a slow `watch` consumer for agent A MUST NOT delay the backing store's acceptance of `send` calls or delay `watch` delivery to agent B.

**Lifecycle:** The `watch` generator runs for the lifetime of the MCP server process. Implementations MUST support cancellation cleanly (no resource leaks on generator close).

---

## 3. Atomicity Requirements

These requirements are normative and apply to all backing-store implementations regardless of backend technology.

**3.1 send-atomicity:** A successful `send` return is a durability guarantee. The message is immediately visible to all qualifying `watch` loops and all subsequent `recv` calls. No partial-visibility window exists after `send` returns.

**3.2 recv-atomicity (per-agent):** The delivery marking and message selection for a single `recv` call are a single atomic operation per agent. Concurrent `recv` calls from agent A and agent B operating on overlapping channel sets MUST each receive exactly the messages due to them; neither call's delivery set overlaps the other's.

**3.3 No phantom reads:** A message that has been returned in a `recv` call MUST NOT subsequently appear as undelivered in another `recv` call for the same agent, even under backend failure followed by recovery, provided the backend reports durable acceptance.

---

## 4. Delivery Semantics

**4.1 Minimum guarantee (at-least-once):** SOX v1.0 requires at-least-once delivery at minimum. A message delivered to an agent and successfully marked as delivered in the store MAY be considered consumed even if the agent crashes before integrating it. Operators who need exactly-once semantics SHOULD use `correlation_id` for application-level deduplication.

**4.2 No guaranteed re-delivery after crash:** If an agent drains a message (recv returns successfully) and then crashes before using it, v0 does not guarantee re-delivery. This is a known limitation noted in CONTRACTS.md §6.2. Stronger semantics (explicit ack, re-delivery on timeout) are deferred to v0.2+.

**4.3 No cross-agent leakage:** A message addressed to channel C and received by agent A MUST NOT be suppressed from agent B (if B is also subscribed to C) as a result of A's recv. Each subscribed agent's delivery set is independent.

---

## 5. Ordering Guarantees

**5.1 Per-channel send-time order:** Within a single channel, messages MUST be returned to a given agent in ascending `sent_at` order. When two messages have identical `sent_at` values (same-millisecond concurrent sends), the backing store's internal tie-break order (e.g. insertion sequence) applies and MUST be consistent across recv calls.

**5.2 No cross-channel ordering guarantee:** Messages across different channels MAY be interleaved in any order within a single `recv` response. Agents MUST NOT assume cross-channel ordering.

**5.3 Watch-loop ordering:** The `watch` generator MUST yield messages in per-channel send-time order for a single channel. Across channels, yield order is unspecified.

---

## 6. Watch-Loop Semantics (detailed)

The `watch` method is the mechanism that gives the MCP server's background listener task its push-receive property. This section elaborates on the expected operational pattern.

**6.1 Typical usage pattern:**  
The MCP server spawns one `watch(agent_id)` task per agent at startup. That task runs in a loop: each message yielded is placed into a local in-memory mailbox queue. When the agent calls the `channels__recv` MCP tool, the handler drains the local mailbox (not the backing store directly). This means `recv` tool latency is bounded by the mailbox drain, not by a store query.

**6.2 Subscription matching:**  
`watch` MUST deliver messages only for channels that match `agent_id`'s registered subscriptions at the time the message is sent. If `agent_id` registers a new subscription after `watch` has started, messages on newly-matched channels MUST be delivered from that point forward (the watch loop does not require restart).

**6.3 Back-pressure:**  
The MCP server is responsible for consuming yielded messages promptly. The backing store MUST NOT apply unbounded back-pressure that blocks `send` operations when the watch consumer is slow. Implementations MAY buffer internally but MUST document their buffer limits.

**6.4 Graceful shutdown:**  
On MCP server shutdown, the `watch` generator MUST be cancelled cleanly. Any messages buffered locally but not yet returned via `recv` are lost (this is the "at-least-once" contract: the messages were delivered to the server but not to the agent). Operators who cannot tolerate this MUST use a durable backing store (SQLite, NATS) so that unread messages survive restart.

---

## 7. Namespace parameterisation

All read/write operations MUST be parameterised by `namespace` (string, default `"default"`). The backing store MUST NOT return records from a different namespace than the one specified.

**Namespace isolation modes** (declared at store construction time, not per-request):

| Mode | Description |
|---|---|
| `shared` | Single database; all queries include a `namespace` WHERE clause enforced inside the store. |
| `isolated` | Each namespace maps to a separate SQLite file or Postgres schema; the store routes per-namespace. |

Both modes present an identical port interface. The SOX server MUST NOT need to know which mode is in use.

The `namespace` parameter is injected by the `namespace_resolver` middleware into the request context before the store is called. Store implementations MUST treat an absent or null namespace as `"default"`.

Stores MUST enforce namespace isolation structurally. Cross-namespace return is a conformance failure.

---

## 8. Schema registry

Each channel MAY have a registered JSON Schema document that governs the shape of `body` payloads sent to that channel. The backing store owns the schema artifact; validation is performed by the `schema_validator` middleware (not the store).

### 8.1 `get_channel_schema`

**Signature:** `get_channel_schema(namespace, channel) -> JSONSchema | null`

Returns the registered JSON Schema for the given channel in the given namespace, or `null` if no schema is registered. The store MUST NOT validate or interpret the schema; it stores and returns it verbatim.

### 8.2 `set_channel_schema`

**Signature:** `set_channel_schema(namespace, channel, schema)`

Registers or replaces the JSON Schema for the given channel. The schema is stored as an opaque JSON document alongside the channel config. Implementations SHOULD compute and store a content hash for schema versioning. Successive calls replace the current schema; the store MAY retain a version history for audit purposes.

---

## 9. Idempotency cache

The backing store MUST support an idempotency cache for `send` operations.

### 9.1 Behaviour

When a `send` call includes an `idempotency_key`:

1. The store checks whether an entry for `(namespace, channel, idempotency_key)` exists in the cache.
2. If a matching entry exists and has not expired (within the TTL window), the store MUST return the original `(message_id, sent_at, seq)` without re-persisting the message.
3. If no matching entry exists or the entry has expired, the store persists the message normally and records the `(idempotency_key, message_id, sent_at, seq, expires_at)` tuple in the cache.

The default TTL is **24 hours**. Operators MAY configure a different TTL at the server level. Per-channel TTL override is permitted but not required for v1.

Callers MUST NOT rely on deduplication beyond the configured TTL window. After TTL expiry, a re-sent message with the same `idempotency_key` is treated as a new message.

### 9.2 `sweep_idempotency_cache`

**Signature:** `sweep_idempotency_cache(ttl_seconds: int) -> int` (returns count of evicted entries)

**Mandatory operation.** The SOX server MUST call this periodically (or an equivalent compaction mechanism) to reclaim storage. Implementations MUST support this call and MUST evict all cache entries whose `expires_at` is in the past relative to the call time.

Implementations MAY call this on a background schedule or on-startup; the sweep cadence is implementation-defined. The conformance suite tests that storage does not grow unboundedly after the window expires.

**Conformance note:** The `idempotency_ttl_seconds` value is a server-level configuration field. Implementations MUST document their default.

---

## 10. Per-channel `seq` counter

The backing store MUST maintain a per-channel monotone integer sequence counter (`seq`), incremented atomically with each persisted `send`. The counter starts at 1 for a new channel. Two concurrent `send` calls on the same channel MUST NOT receive the same `seq` value.

The store MUST support range queries by `seq` for the `replay` operation: `get_messages(namespace, channel, since_seq, until_seq, limit)`.

The store MUST also support ancestor-walk queries for thread depth expansion: `get_ancestors(namespace, message_id, max_depth)` — returns the chain of messages linked by `reply_to`, bounded by `max_depth`.

> **Post-v1 upgrade path:** A dedicated `waiting_on` index column may be added to the pending-state record in a future version to make deadlock detection O(1) instead of O(n traversal). The current spec requires no such column; detection is computed at query time from `reply_to` + `delivered_to`. Store authors should leave schema room for this column.

---

## 11. Conformance Checklist

A backing-store implementation is SOX v1.0 conformant when it satisfies all of the following:

- [ ] Implements all five core methods: `send`, `recv`, `subscribe`, `list_channels`, `watch`.
- [ ] All operations are parameterised by `namespace`; cross-namespace return is impossible.
- [ ] `send` is atomic: successful return implies immediate visibility to all subscribers.
- [ ] `send` assigns a per-channel monotone `seq` atomically.
- [ ] `recv` is atomic per-agent: returned messages are marked delivered in the same operation.
- [ ] `recv` never re-delivers a message to the same agent.
- [ ] `subscribe` is idempotent; subscriptions survive server restart.
- [ ] `watch` yields each new matching message exactly once per invocation per agent.
- [ ] Per-channel `seq` ordering is preserved in both `recv` responses and `watch` yields.
- [ ] `watch` can be cancelled cleanly without resource leaks.
- [ ] `get_channel_schema` / `set_channel_schema` are implemented (may return null for all channels if schema registry is not used).
- [ ] `sweep_idempotency_cache` is implemented and callable.
- [ ] Idempotency dedup works within the configured TTL; re-accepts after TTL expiry.
- [ ] Range queries by `seq` support the `replay` operation.
- [ ] Ancestor-walk queries support `thread_depth` expansion.
- [ ] Implementation declares the protocol version it targets.
- [ ] Implementation documents the namespace isolation mode it supports.
- [ ] Implementation documents any backend-specific limitations or extensions.
- [ ] Implementation passes the language-neutral conformance suite at `spec/conformance/`.
