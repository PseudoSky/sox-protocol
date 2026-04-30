<!-- SPDX-License-Identifier: Apache-2.0 -->
# Groups — Primitive Spec

**Protocol version:** 1.0
**Status:** Normative
**Supersedes:** previous model where groups had no membership list and membership was implicit via subscription

---

## 1. Concept

A **group** is a managed channel under the `group/<group-id>` prefix whose membership is maintained by the server in a dedicated membership table. Groups are the primary topology for N:N messaging — one sender, multiple receivers, one channel — and are the fan-out primitive for orchestrator-to-worker patterns.

Groups reuse the full channel machinery: same envelope, same `seq` counter, same threading, same replay, same enforcer. Messaging verbs (`channels__send`, `channels__recv`) are unchanged. Group lifecycle (create, invite, join, leave, list members) uses dedicated tools that mutate the server-side membership table.

> **Decision source:** `docs/decisions/groups-model.md` — Option A (managed channel)

---

## 2. Naming convention

Group channel names follow the reserved pattern:

```text
group/<group-id>
```

`<group-id>` MAY be human-chosen (e.g., `group/eng-team`) or a server-assigned opaque identifier (e.g., `group/01HXYZ...`). The server determines the assignment strategy at group creation time based on the `id_mode` parameter.

The `group/` prefix is **reserved**. Clients MUST NOT create or subscribe to channels beginning with `group/` directly outside of the lifecycle verbs below.

---

## 3. Reserved prefixes summary

| Prefix | Type | Enforcement |
|---|---|---|
| `dm/` | DM channels | Two-party only; server-enforced |
| `group/` | Group channels | Membership-table enforced |
| `sox/` | Server-derived channels | Server-emitted only; agents cannot write |

---

## 4. Membership table contract

The server maintains a membership table with the following structure per group:

| Field | Type | Description |
|---|---|---|
| `group_id` | string | Channel name without the `group/` prefix |
| `agent_id` | string | Member agent's verified identity |
| `joined_at` | number | Unix epoch seconds when membership was established |
| `status` | string | `active` or `invited` |

**Enforcement on every `send` and `subscribe`:** The server MUST verify the calling agent is an `active` member of the group. Non-members receive a `GROUP_MEMBERSHIP_REQUIRED` error.

**Enforcement on wildcard subscribe:** Agents CANNOT glob-subscribe to `group/*`. Wildcard patterns that would match `group/` channels are rejected.

---

## 5. Lifecycle verbs

Group lifecycle is managed through the following tools. All lifecycle tools require a verified agent identity.

### 5.1 `group_create`

Creates a new group channel and adds the creating agent as the first `active` member.

**Parameters:**

- `group_id` (string, optional): desired group ID. If omitted, server assigns an opaque ID.
- `display_name` (string, optional): human-readable name for tooling display.

**Returns:** `{ group_id: "group/<group-id>", created_at: <number> }`

### 5.2 `group_invite`

Invites an agent to a group. The inviting agent MUST be an `active` member. The invited agent's status is set to `invited`.

**Parameters:**

- `group_id` (string): the `group/<group-id>` channel.
- `agent_id` (string): the agent to invite.

**Returns:** `{ group_id: <string>, invited_agent: <string>, invited_at: <number> }`

### 5.3 `group_join`

An invited agent accepts membership. Transitions the calling agent's status from `invited` to `active`.

**Parameters:**

- `group_id` (string): the `group/<group-id>` channel.

**Returns:** `{ group_id: <string>, joined_at: <number> }`

### 5.4 `group_leave`

An active member leaves the group. The server removes the agent from the membership table.

**Parameters:**

- `group_id` (string): the `group/<group-id>` channel.

**Returns:** `{ group_id: <string>, left_at: <number> }`

### 5.5 `group_list_members`

Returns the current membership table for a group. Caller MUST be an `active` member.

**Parameters:**

- `group_id` (string): the `group/<group-id>` channel.

**Returns:** Array of `{ agent_id, status, joined_at, presence_state }` objects.

> **Post-v1:** Member roles (owner, admin, member, observer) are out of scope for v1. All `active` members have equal permissions within the group. Role-based access is a middleware/hook layer concern deferred to v1.x.

---

## 6. Fan-out semantics

Sending to a group channel delivers the message to all `active` members — this is the fan-out primitive. No separate `channels__fanout` tool exists; `channels__send` to a `group/<group-id>` channel IS the fan-out.

```text
{{send_tool}}(
  channel = "group/eng-team",
  body    = { "type": "clarification_request", ... }
)
```

The server delivers to all active members' subscriber queues atomically. Members receive it on their next `recv` drain.

---

## 7. Collect (fan-in)

After broadcasting to a group, an orchestrator may wait for replies using `channels__collect`. See `spec/operations/channels_collect.input.schema.json` for the full schema.

```text
channels__collect(
  reply_to = "<message_id of the broadcast>",
  count    = 3,
  timeout  = 30
)
```

Returns `{ received: [...], missing: [...], timed_out: bool }`.

> **Post-v1:** `channels__collect` is marked `x-status: planned`. Quorum semantics, cancel verb, and multiple-collector semantics are open questions documented in the schema.

---

## 8. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | Groups are managed channels; all channel semantics apply (seq, threading, replay) |
| DMs ([dms.md](dms.md)) | DMs and groups follow the same managed-channel model with different membership policies |
| ACK/NACK ([ack-nack.md](ack-nack.md)) | Group messages require one ACK per recipient via `channels__ack`; tracked individually |
| Sequence numbers ([sequence-numbers.md](sequence-numbers.md)) | Each group channel has its own per-channel `seq` counter |
| Threads ([threads.md](threads.md)) | Threading via `reply_to` works inside group channels identically to other channels |
| Presence ([presence.md](presence.md)) | Members publish presence via `channels__heartbeat`; `sox/presence` reflects group member states |
