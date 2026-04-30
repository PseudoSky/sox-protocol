<!-- SPDX-License-Identifier: Apache-2.0 -->
# Direct Messages (DMs) — Primitive Spec

**Protocol version:** 1.0
**Status:** Normative
**Supersedes:** previous `agent:<recipient-id>` naming convention

---

## 1. Concept

A **direct message (DM)** is a private, two-party channel between exactly two agents. In SOX, DMs are not a separate protocol primitive — they are managed channels whose name encodes both parties and whose membership is enforced server-side.

DMs reuse the full channel machinery: same envelope, same `seq` counter, same threading, same replay, same enforcer stop-block. No new delivery path or message type is introduced.

> **Decision source:** `docs/decisions/dm-semantics.md` — Option A

---

## 2. Naming convention

A DM channel name follows the reserved pattern:

```text
dm/<agent-id-A>~<agent-id-B>
```

where `<agent-id-A>` and `<agent-id-B>` are **lexicographically sorted** (ascending, byte-order comparison of UTF-8 encoded agent IDs). The `~` separator is used because it does not appear in valid agent ID strings and avoids ambiguity with the `/` path separator.

**Canonicalization rules:**

1. Compare agent IDs as Unicode strings using byte-order (code-point) comparison.
2. The lexicographically lesser ID comes first.
3. Agent IDs are treated as case-sensitive for comparison purposes.

**Example:** For agents `agent-alpha` and `agent-beta`:

```text
dm/agent-alpha~agent-beta
```

because `"agent-alpha" < "agent-beta"` lexicographically.

**Example:** For agents `zeta` and `alpha`:

```text
dm/alpha~zeta
```

---

## 3. Reserved namespace

The `dm/` prefix is **reserved**. Clients MUST NOT attempt to create or subscribe to channels beginning with `dm/` directly — the server MUST reject such operations unless issued through the DM creation path.

The server creates a DM channel automatically on the first send between two agents if it does not already exist.

---

## 4. Server-side enforcement

The server enforces the two-party constraint on every DM channel:

| Operation | Enforcement |
|---|---|
| `send` | Sender MUST be one of the two named agents. Rejected otherwise with `DM_MEMBERSHIP_VIOLATION`. |
| `subscribe` | Subscriber MUST be one of the two named agents. Rejected otherwise. |
| Wildcard `subscribe` on `dm/*` | MUST be rejected for all agents. The `dm/` prefix cannot be glob-subscribed. |
| `recv` | Standard channel semantics; only the subscribed agent sees its messages. |

The server derives the two named agents from the channel name by splitting on `~` after stripping the `dm/` prefix.

---

## 5. Privacy model

DM channels provide **routing by enforcement**, not cryptographic confidentiality.

The server ensures only the two named agents can send to or subscribe to the channel. A privileged server operator with direct backing-store access can read DM contents. This is a deployment/auth concern, not a protocol concern.

**v1.0:** Agents MUST NOT transmit credentials or secrets over DM channels unless the deployment guarantees backing-store confidentiality through out-of-band means.

> **Post-v1:** Cryptographic DM confidentiality (end-to-end encryption using the agents' Ed25519 keypairs from ADR 0002) is a roadmap item. The current identity primitive enables recipient-side key derivation but the encrypted-envelope spec is deferred.

---

## 6. Operations

DMs use the standard channel operations with the `dm/<sorted-pair>` channel name.

### Sending a DM

```text
{{send_tool}}(
  channel = "dm/agent-alpha~agent-beta",
  body    = { "type": "clarification_request", ... },
  correlation_id = "req-007"
)
```

The server verifies the sender is one of `agent-alpha` or `agent-beta` before persisting.

### Receiving DMs

Each agent subscribes to their own DM channels at startup. Since wildcard subscription on `dm/*` is blocked, agents must subscribe to specific DM channels they participate in:

```text
{{subscribe_tool}}(pattern="dm/agent-alpha~agent-beta")
```

Then drain normally:

```text
{{recv_tool}}()
```

### Replying to a DM

Send back to the same `dm/<sorted-pair>` channel — the pair is symmetric:

```text
{{send_tool}}(
  channel        = "dm/agent-alpha~agent-beta",
  body           = { "type": "clarification_reply", "answer": "..." },
  correlation_id = "req-007"
)
```

---

## 7. Channel discovery

DM channels appear in `{{list_tool}}` output like any other channel. Agents can identify them by the `dm/` prefix. The subscriber count on a DM channel MUST NOT exceed 2.

---

## 8. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | DMs are managed channels; all channel semantics apply (seq, threading, replay, enforcer) |
| Groups ([groups.md](groups.md)) | A DM is the two-party special case of the managed-channel model groups use |
| ACK/NACK ([ack-nack.md](ack-nack.md)) | Use the `channels__ack` tool; ACKs reference `message_id`, not channel |
| Sequence numbers ([sequence-numbers.md](sequence-numbers.md)) | Each DM channel has its own per-channel `seq` counter starting at 1 |
| Threads ([threads.md](threads.md)) | Threading via `reply_to` works inside DM channels identically to other channels |
| Identity ([spec/ports/identity.md](../ports/identity.md)) | Server enforcement relies on verified agent identity (ADR 0002) |
