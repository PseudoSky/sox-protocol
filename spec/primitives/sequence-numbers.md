<!-- SPDX-License-Identifier: Apache-2.0 -->
# Sequence Numbers — Primitive Spec

**Protocol version:** 1.0
**Status:** Normative
**Supersedes:** previous spec that stated "SOX does not use explicit integer sequence numbers in v1.0"

---

## 1. Concept

Every SOX message carries a **per-channel monotone integer sequence number** (`seq`) assigned by the server at the moment the message is durably accepted. Sequence numbers start at 1 for each channel and increment by 1 for each new message. They are the authoritative ordering key within a channel and the cursor for replay queries.

A separate, optional **server-assigned monotonic timestamp** (`ts`) is included in the envelope as a tiebreaker for cross-channel display ordering. `ts` is advisory, not authoritative.

> **Decision source:** `docs/decisions/seq-ordering-scope.md` — Option B (per-channel seq)

---

## 2. `seq` — per-channel monotone counter

| Property | Value |
|---|---|
| Type | Integer (≥ 1) |
| Scope | Per channel. Each channel has an independent counter. |
| Assignment | Server-assigned at durable `send` acceptance. |
| Starting value | 1 (first message on any channel) |
| Increment | Strictly +1 per message within a channel |
| Cross-channel ordering | Not defined by `seq`. Use `ts` for display ordering across channels. |

The backing store MUST assign `seq` atomically with message persistence. Two messages on the same channel MUST NOT share a `seq` value.

Clients use `seq` as a **cursor** for replay:

```text
replay(channel="ticket:ENGI-0042", since=42, until=null, limit=100)
```

returns all messages with `seq > 42` on that channel, in ascending `seq` order.

---

## 3. `ts` — server-assigned monotonic timestamp

| Property | Value |
|---|---|
| Type | Integer (Unix epoch nanoseconds) |
| Scope | Server-wide monotonic (monotone per server node, not globally) |
| Assignment | Server-assigned at durable `send` acceptance |
| Guarantee | Monotone per server node; NOT globally total-ordered in multi-node or federated deployments |
| Purpose | Advisory tiebreaker for cross-channel display ordering; human-readable timeline in tooling |

`ts` MUST be monotone: for two messages accepted by the same server node, if message A is accepted before message B, `ts(A) <= ts(B)`. Wall-clock skew MUST be corrected to maintain this guarantee (monotonic clock source recommended). Implementations MUST NOT use ISO-8601 strings for `ts`; integer nanoseconds ensure wire-level interop across runtimes.

Clients and tooling MAY sort a unified timeline by `ts`, accepting that this ordering is advisory, not authoritative. Agents MUST NOT make correctness decisions based on `ts` alone.

---

## 4. Per-channel ordering guarantee

Within a single channel:

- Messages are returned by `recv` and `replay` in ascending `seq` order.
- `seq` ordering is the authoritative order; `sent_at` (the legacy float timestamp field) is retained for backward compatibility but `seq` supersedes it for ordering purposes.
- The backing store MUST perform atomic increment of the per-channel `seq` counter; no two concurrent `send` calls on the same channel may receive the same `seq`.

---

## 5. Cross-channel ordering guarantee

**None.** Messages across different channels have no protocol-level total order. Agents MUST NOT assume cross-channel ordering.

For display-time ordering across channels, sort by `ts` and treat the result as advisory.

---

## 6. Federation-aware design

Per-channel `seq` is federation-shaped by design:

- A federated v2 deployment can maintain per-channel `seq` independently on each server node.
- The `origin_server` envelope field (see `spec/protocol.md`) disambiguates messages that share a `seq` value across federated channels.
- No global counter must be unwound in a v2 migration.

---

## 7. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | Each channel has an independent `seq` counter; `seq` is the per-channel ordering key |
| Replay | `since` parameter is a per-channel `seq` cursor; see `spec/operations/replay.input.schema.json` |
| Threads ([threads.md](threads.md)) | Thread channels have independent `seq` counters; thread order is independent of parent channel `seq` |
| ACK/NACK ([ack-nack.md](ack-nack.md)) | ACKs do not consume `seq` slots (ACKs are control-plane, not channel messages) |
| Pending state ([pending-state.md](pending-state.md)) | `seq` is used as replay cursor for recovering missed messages after reconnection |
