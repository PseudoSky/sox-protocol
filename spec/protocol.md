<!-- SPDX-License-Identifier: Apache-2.0 -->
# SOX Protocol — Overview

**Protocol version:** 1.0  
**Status:** Normative  
**Canonical source:** `spec/` (this directory)

---

## What is SOX?

SOX is a real-time many-to-many messaging protocol in which LLM agents are first-class peers. It fills a structural gap in multi-agent systems: no existing framework packages a documented, runtime-agnostic pattern for *speculative-execute-while-awaiting-clarification* — an agent posts a question to peers, continues under a best-guess interpretation, and non-destructively integrates the late-arriving answer.

SOX provides:

- Named, persistent channels that any agent can join.
- Non-blocking `send` (fire-and-forget into the backing store).
- Pull-based, non-blocking `recv` (the agent controls when it drains).
- Glob-pattern subscriptions for selective channel membership.
- A cadence enforcer that reminds agents to drain without interrupting their reasoning.

---

## The novelty claim

> **Group chat for LLM agents** — SOX is the first published, runtime-agnostic specification for peer N:N asynchronous messaging among LLM agents, with an explicit discipline for speculative-execute-and-reconcile.

Competing systems either pause agent A while B answers (turn-taking schedulers, handoff frameworks) or provide the raw actor primitives without a packaged cadence discipline (AutoGen, MetaGPT). SOX packages both the channel layer and the discipline. See [docs/DESIGN.md §1–2](../docs/DESIGN.md) for the full survey.

---

## Protocol operations

All SOX-conformant implementations expose the following core operations. Group lifecycle, agent discovery, and subscription management operations are defined in their respective primitive sections. Concrete tool names vary by adapter; the spec uses placeholder tokens that adapters substitute at install time.

| Operation | Placeholder | Status | Semantics |
|---|---|---|---|
| `send` | `{{send_tool}}` | v1 MUST | Append a message to a named channel. Non-blocking; returns `{sent_at, message_id, seq, backpressure}` once the backing store durably accepts it. |
| `recv` | `{{recv_tool}}` | v1 MUST | Drain the local mailbox. Non-blocking; returns immediately with whatever has accumulated since the last drain. |
| `subscribe` | `{{subscribe_tool}}` | v1 MUST | Register interest in channels matching a glob pattern. Persists across server restarts. |
| `unsubscribe` | `unsubscribe` | v1 MUST | Remove channel subscriptions matching names or glob patterns. Discards queued-but-unread messages for removed subscriptions. |
| `list_channels` | `{{list_tool}}` | v1 MUST | Discover active channels. Returns the `_sox_protocol` version block for version negotiation. |
| `channels__ack` | `channels__ack` | v1 MUST | Signal ACK/NACK for a message. Control-plane only; does not enter channel history. |
| `channels__heartbeat` | `channels__heartbeat` | v1 MUST | Update the server-side liveness record. Control-plane only. |
| `replay` | `replay` | v1 MUST | Replay historical messages from a channel using a per-channel `seq` cursor. |
| `channels__collect` | `channels__collect` | planned | Server-side fan-in aggregation: wait for N replies to a broadcast. See `x-status: planned` in schemas. |
| `group_create` | `group_create` | v1 MUST | Create a new group channel and add the creating agent as the first active member. See spec/primitives/groups.md §5.1. |
| `group_invite` | `group_invite` | v1 MUST | Invite an agent to a group. Calling agent must be an active member. See spec/primitives/groups.md §5.2. |
| `group_join` | `group_join` | v1 MUST | Accept a group invitation; transition calling agent's status from invited to active. See spec/primitives/groups.md §5.3. |
| `group_leave` | `group_leave` | v1 MUST | Leave a group; server removes calling agent from the membership table. See spec/primitives/groups.md §5.4. |
| `group_list_members` | `group_list_members` | v1 MUST | Return the current membership list for a group. See spec/primitives/groups.md §5.5. |
| `list_agents` | `list_agents` | v1 MUST | Return the server-tracked liveness table for all known agents. Each entry carries `agent_id`, `presence_state` (online/busy/stale/offline), `last_heartbeat_at` (integer nanoseconds), and optional `namespace`. Supports `status_filter` and `namespace` query parameters. See spec/primitives/presence.md §2. |

Full JSON Schemas for inputs and outputs: [spec/operations/](operations/)

---

## Connection bootstrap

The following sequence SHOULD be followed by any client establishing a session with a SOX server. Deviation requires justification; skipping steps is permitted at the client's risk.

1. **SHOULD** — Call `list_channels`. Read the `_sox_protocol` block to verify server version compatibility. Skipping this step proceeds without a version handshake at the client's risk; the server does not enforce a minimum-version check on other operations.
2. **SHOULD** — Call `subscribe` with desired channel patterns. Order-dependent; messages sent to subscribed channels before this call may be missed.
3. **SHOULD** — Call `list_agents` (if agent discovery is needed) or subscribe to `sox/presence` to enumerate active peers. `list_agents` returns the full server-tracked liveness table; `sox/presence` provides a live event feed of state transitions.
4. **SHOULD** — Call `recv` as the first drain. The first `recv` call drains messages queued during any offline period.

> **Post-v1:** `list_pending` — surfaces queued unreplied messages and their ACK states. In v1 use `recv` to drain and track state client-side.

---

## Message envelope shape

Every message stored and returned by SOX has the following wire shape (see [spec/envelopes/](envelopes/) for reserved body types):

```json
{
  "channel":        "<string — channel name>",
  "sender":         "<string — agent_id of sending agent; server-certified>",
  "body":           { "<opaque JSON object>" },
  "correlation_id": "<string | null>",
  "sent_at":        "<number — Unix epoch seconds, floating-point>",
  "message_id":     "<string — backing-store-assigned ID>",
  "seq":            "<integer ≥ 1 — per-channel monotone counter>",
  "ts":             "<integer — server-assigned monotonic nanosecond timestamp, advisory>",
  "reply_to":       "<string | null — message_id this message replies to; null if not a reply>",
  "delivered_to":   "<string[] | null — agent_ids that have recv'd this message; server-populated for deadlock detection>",
  "origin_server":  "<string | null — server_id in federated deployments; null in single-server v1>"
}
```

**Envelope field notes:**

| Field | Assigned by | Notes |
|---|---|---|
| `seq` | Server | Per-channel monotone counter starting at 1. Authoritative ordering key within a channel. Cursor for `replay`. |
| `ts` | Server | Monotonic nanosecond timestamp per server node. Advisory tiebreaker for cross-channel display ordering. NOT globally total-ordered. |
| `reply_to` | Sender (via `send` input) | Links a message to its parent in a thread. Used with `thread_depth` on `recv`. Combined with `delivered_to` for wait-graph computation (deadlock detection). |
| `delivered_to` | Server | Populated by server as agents `recv` the message. Used for deadlock detection wait-graph at query time. SHOULD-implement feature (see §Deadlock detection below). |
| `origin_server` | Server | Always `null` in v1.0 single-server deployments. Reserved for federated v2. The structured identity form `<server-id>/<agent-id>` is documented in `spec/ports/identity.md`. |

### Observability extension: `_meta`

When `include_meta: true` (the default), `recv` responses carry an optional `_meta` object on each message:

```json
{
  "_meta": {
    "trace_id":           "<string — distributed trace ID>",
    "middleware_timings": ["<string — 'middleware_name:Nms'>"],
    "server_node_id":     "<string>"
  }
}
```

`_meta` is absent when `include_meta: false` is set on the `recv` call. Server operators may set a deployment-wide default via server configuration; per-request `include_meta` overrides the deployment default. See `docs/decisions/observability-meta-mode.md`.

### Deadlock detection

The `reply_to` and `delivered_to` fields together enable server-side wait-graph computation. If agent A is waiting for a reply from agent B (A sent a message to B, `delivered_to` includes B, B has not ACK'd), and agent B is waiting for a reply from agent A (symmetric), a cycle exists.

Detection is performed at query time by traversing the pending-state records using `reply_to` + `delivered_to`. This is a **SHOULD-implement** feature, not MUST. At v1 scale (tens of agents, hundreds of pending replies), O(n) traversal on demand is acceptable.

> **Post-v1:** A dedicated `waiting_on` index column in the backing store is documented as a v1.x upgrade path in `spec/ports/backing-store.md` for deployments where detection latency at scale becomes a concern.

The `body` is opaque to the protocol. Recommended body conventions (advisory, not required):

| Field | Type | Meaning |
|---|---|---|
| `type` | string | Message kind: `clarification_request`, `clarification_reply`, `status_update`, `handoff_ready`, `sox-error`, `sox-invite` |
| `subject` | string | Short human-readable summary |
| `context` | string | Background the receiver needs |
| `question` | string | Used with `clarification_request` |
| `answer` | string | Used with `clarification_reply` |
| `urgency` | string | `low` / `normal` / `high` — advisory hint only |

Reserved body types (`sox-error`, `sox-invite`) have normative JSON Schemas under [spec/envelopes/](envelopes/). The `sox-ack` and `sox-nack` schemas now apply to `channels__ack` tool responses, not channel messages (see [spec/primitives/ack-nack.md](primitives/ack-nack.md)).

### Federation-aware design

`origin_server` is always `null` in v1.0 single-server deployments. In a federated v2 deployment, it carries the originating server's identifier. Agent identities in a federated deployment use the structured form `<server-id>/<agent-id>`; in v1.0, the `<server-id>/` prefix is implicit (empty) and agent IDs are bare strings. See `spec/ports/identity.md`.

---

## Architecture layers

```text
Layer 5 — System prompt (one-line bootstrap per agent)
Layer 4 — Cadence enforcer (pure function; runtime-agnostic)
Layer 3 — Discipline (markdown; runtime-agnostic)
Layer 2 — MCP server (eight core operations; event-loop listener (non-blocking I/O))
Layer 1 — Backing store (pluggable; SQLite / filesystem / NATS / Redis)
```

The protocol is defined at layers 1–4. Layer 5 is the adapter's concern.

---

## Key primitives

| Primitive | Spec location |
|---|---|
| Channels | [spec/primitives/channels.md](primitives/channels.md) |
| Groups | [spec/primitives/groups.md](primitives/groups.md) |
| Direct messages (DMs) | [spec/primitives/dms.md](primitives/dms.md) |
| Threads | [spec/primitives/threads.md](primitives/threads.md) |
| Presence | [spec/primitives/presence.md](primitives/presence.md) |
| ACK / NACK | [spec/primitives/ack-nack.md](primitives/ack-nack.md) |
| Pending state | [spec/primitives/pending-state.md](primitives/pending-state.md) |
| Sequence numbers | [spec/primitives/sequence-numbers.md](primitives/sequence-numbers.md) |
| Trace IDs | [spec/primitives/trace-ids.md](primitives/trace-ids.md) |

---

## Port contracts

| Port | Direction | Spec location |
|---|---|---|
| BackingStore | South / driven | [spec/ports/backing-store.md](ports/backing-store.md) |
| Transport | North / driving (wire) | [spec/ports/transport.md](ports/transport.md) |
| Identity | North / driving (auth) | [spec/ports/identity.md](ports/identity.md) |
| Middleware | North / driving (pipeline) | [spec/ports/middleware.md](ports/middleware.md) |
| DisciplineRenderer | North / driving (prompt) | [spec/ports/runtime-discipline-renderer.md](ports/runtime-discipline-renderer.md) |
| EnforcerBinding | North / driving (lifecycle) | [spec/ports/runtime-enforcer-binding.md](ports/runtime-enforcer-binding.md) |

---

## State machines

- Message lifecycle: [spec/state-machines/message-lifecycle.md](state-machines/message-lifecycle.md)
- Agent presence states: [spec/state-machines/presence-states.md](state-machines/presence-states.md)

---

## Versioning

The protocol version is in `spec/VERSION`. MAJOR.MINOR policy:

- **Minor bump** — backward-compatible (new optional fields, new tools). Implementations of vN.M MUST accept inputs from vN.(≤M).
- **Major bump** — breaking change. Implementations MUST refuse cross-major interaction.

The `channels__list_channels` response includes `protocol_version` so adapters can detect mismatches at runtime.

Clients that skip `list_channels` proceed without a version handshake at their own risk; the server does not enforce a minimum-version check on other operations.

---

## Health and observability

> **Post-v1:** A `channels_health` operation exposing store status, queue depth, and circuit-breaker state is planned for post-v1. In v1, health is signalled via `GET /health` on the HTTP transport only.

---

## Spec authority

`spec/` is the canonical source. `docs/CONTRACTS.md` is a narrative mirror; when they conflict, `spec/` wins.
