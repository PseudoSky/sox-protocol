<!-- SPDX-License-Identifier: Apache-2.0 -->
# Groups — Primitive Spec

**Protocol version:** 1.0  
**Status:** Normative

---

## 1. Concept

A **group** is a named set of agents that collaborate over a shared channel. Groups are the primary topology for N:N messaging — multiple senders, multiple receivers, one channel.

SOX has no separate "group object" at the protocol layer. A group is realised by:

1. A conventionally named channel (e.g. `group:<name>` or `ticket:<id>`).
2. All participating agents subscribing to that channel pattern.

The protocol does not maintain a membership list for groups. Membership is implicit: an agent is "in" a group when it has an active subscription that matches the group's channel name.

---

## 2. Naming

Recommended naming conventions:

| Use case | Pattern | Example |
|---|---|---|
| Named persistent group | `group:<name>` | `group:security-team` |
| Task-scoped group | `ticket:<id>` | `ticket:ENGI-0042` |
| Broadcast group (one-to-many) | `broadcast:<topic>` | `broadcast:cto-announcements` |

All of these are ordinary channels. The prefix is advisory only.

---

## 3. Operations

Groups use the standard channel operations. No additional operations are required.

### Joining a group

An agent joins a group by subscribing to the group's channel pattern:

```text
{{subscribe_tool}}(pattern="ticket:ENGI-0042")
```

or, for all tickets:

```text
{{subscribe_tool}}(pattern="ticket:*")
```

### Sending to a group

```text
{{send_tool}}(channel="ticket:ENGI-0042", body={...})
```

All subscribed agents receive the message on their next `recv` call.

### Discovering groups

```text
{{list_tool}}()
```

Returns all active channels, from which group channels can be identified by name prefix.

---

## 4. State

A group has no protocol-level state object. The effective state is:

- **Subscribers** — agents with an active subscription matching the group's channel. Visible via `subscriber_count` in `{{list_tool}}` output.
- **Message backlog** — messages stored in the backing store not yet drained by each subscriber.

---

## 5. Group membership invariants

- **No forced membership.** The protocol does not support "adding" an agent to a group. Agents self-subscribe.
- **No forced removal.** The protocol does not support removing an agent from a group. An agent may unsubscribe by stopping its subscription pattern (subscription removal is implementation-defined; see backing-store port).
- **No membership enumeration.** The protocol exposes `subscriber_count` (an integer) but not the identities of subscribers. Identity enumeration is an implementation extension, not part of v1.0.

---

## 6. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | A group channel is an ordinary channel; all channel semantics apply |
| DMs ([dms.md](dms.md)) | An agent may DM a specific group member; requires knowing their `agent_id` |
| Threads ([threads.md](threads.md)) | A thread can be spawned off any group message via `correlation_id` |
| Presence ([presence.md](presence.md)) | Agents may publish presence to a group channel; receivers interpret it |
| ACK/NACK ([ack-nack.md](ack-nack.md)) | Group members acknowledge messages by sending back to the originating channel |
