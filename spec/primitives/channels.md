# Channels — Primitive Spec

**Protocol version:** 1.0  
**Status:** Normative

---

## 1. Concept

A **channel** is a named, persistent message queue shared among one or more agents. It is the fundamental addressable unit in SOX. Channels have no fixed membership list and no owner — any agent that knows a channel name can send to it; any agent that has subscribed can receive from it.

Channels are created implicitly: a channel exists whenever at least one agent has subscribed to it or at least one message has been stored in it within the backing store's retention window.

---

## 2. Naming

Channel names are strings with a maximum length of 256 characters. SOX places no structural requirement on names beyond non-emptiness, but the following naming conventions are recommended:

| Convention | Pattern | Use case |
|---|---|---|
| Task / ticket channel | `ticket:<id>` or `task:<id>` | Agents collaborating on a specific work item (e.g. `ticket:ENGI-0042`) |
| Broadcast channel | `broadcast:<topic>` | One-to-many announcements (e.g. `broadcast:status`) |
| Direct channel (DM) | `agent:<target-agent-id>` | Agent-to-agent private messages (see [dms.md](dms.md)) |
| Group channel | `group:<name>` | Named groups of agents (see [groups.md](groups.md)) |
| Thread | `thread:<parent-message-id>` | Scoped reply thread off a parent message (see [threads.md](threads.md)) |

Naming conventions are advisory. The protocol does not parse or validate channel names beyond length.

---

## 3. Operations

Channels participate in all four core operations:

### 3.1 `{{send_tool}}`

Appends a message to a channel. The message is immediately visible to all matching subscribers. Non-blocking.

Input schema: `spec/operations/send.input.schema.json`  
Output schema: `spec/operations/send.output.schema.json`

### 3.2 `{{recv_tool}}`

Drains the calling agent's pending messages from one or more channels. Non-blocking; returns immediately with what has accumulated. Marks returned messages as delivered to this agent atomically.

Input schema: `spec/operations/recv.input.schema.json`  
Output schema: `spec/operations/recv.output.schema.json`

### 3.3 `{{subscribe_tool}}`

Registers the calling agent's interest in channels matching a glob pattern. Subscription persists in the backing store across server restarts.

Input schema: `spec/operations/subscribe.input.schema.json`  
Output schema: `spec/operations/subscribe.output.schema.json`

### 3.4 `{{list_tool}}`

Returns all discoverable channels (those with at least one subscriber or recent activity). Discovery does not require subscription.

Output schema: `spec/operations/list_channels.output.schema.json`

---

## 4. State

A channel's state is maintained entirely by the backing store. From the protocol's perspective:

- **Exists** — at least one subscription matches this channel name, or at least one message has been stored and not yet expired.
- **Active** — has at least one message stored since the backing store's retention cutoff (default: 24 hours).
- **Empty** — no pending messages for a given agent. A drain on an empty channel returns `messages: []`.

The channel primitive has no concept of "open" or "closed"; there is no channel lifecycle signal beyond the implicit creation and expiry described above.

---

## 5. Delivery semantics

- **At-least-once (v1.0).** A message stored by `send` will be returned by `recv` for every subscribed agent at least once. If an agent drains a message and crashes before integrating it, the message is not re-delivered. See [pending-state.md](pending-state.md) for the pending/delivered lifecycle and [ack-nack.md](ack-nack.md) for explicit acknowledgement patterns.
- **Per-channel ordering.** Within a single channel, messages are returned in ascending `sent_at` order. Across channels in a single `recv` call, order is unspecified.
- **No cross-agent leakage.** Agent A receiving a message from channel C does not suppress that message for agent B, which is also subscribed to C. Delivery sets are per-agent.

---

## 6. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Subscriptions (subscribe operation) | Determine which channels an agent receives from on `recv` |
| Groups ([groups.md](groups.md)) | A group is a named set of agents sharing a group channel; no special protocol behaviour beyond naming |
| DMs ([dms.md](dms.md)) | A DM is a channel named `agent:<target-id>`; same wire protocol |
| Threads ([threads.md](threads.md)) | A thread is a channel named `thread:<parent-message-id>` |
| Presence ([presence.md](presence.md)) | Agents publish presence updates to presence channels |
| ACK/NACK ([ack-nack.md](ack-nack.md)) | Acknowledgements are messages sent back to the originating channel with a reserved body type |
| Sequence numbers ([sequence-numbers.md](sequence-numbers.md)) | `message_id` and `sent_at` together determine per-channel order |
| Trace IDs ([trace-ids.md](trace-ids.md)) | `correlation_id` on the wire envelope links related messages across channels |
