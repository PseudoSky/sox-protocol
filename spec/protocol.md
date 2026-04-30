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

## The four core operations

All SOX-conformant implementations expose exactly these four operations. Concrete tool names vary by adapter; the spec uses placeholder tokens that adapters substitute at install time.

| Operation | Placeholder | Semantics |
|---|---|---|
| `send` | `{{send_tool}}` | Append a message to a named channel. Non-blocking; returns `{sent_at, message_id}` once the backing store durably accepts it. |
| `recv` | `{{recv_tool}}` | Drain the local mailbox. Non-blocking; returns immediately with whatever has accumulated since the last drain. |
| `subscribe` | `{{subscribe_tool}}` | Register interest in channels matching a glob pattern. Persists across server restarts. |
| `list_channels` | `{{list_tool}}` | Discover active channels. Also exposes the server's `protocol_version` for version-mismatch detection. |

Full JSON Schemas for inputs and outputs: [spec/operations/](operations/)

---

## Message envelope shape

Every message stored and returned by SOX has the following wire shape (see [spec/envelopes/](envelopes/) for reserved body types):

```json
{
  "channel":        "<string — channel name>",
  "sender":         "<string — agent_id of sending agent>",
  "body":           { "<opaque JSON object>" },
  "correlation_id": "<string | null>",
  "sent_at":        "<number — Unix epoch seconds>",
  "message_id":     "<string — backing-store-assigned ID>"
}
```

The `body` is opaque to the protocol. Recommended body conventions (advisory, not required):

| Field | Type | Meaning |
|---|---|---|
| `type` | string | Message kind: `clarification_request`, `clarification_reply`, `status_update`, `handoff_ready`, `sox-ack`, `sox-nack`, `sox-error`, `sox-invite` |
| `subject` | string | Short human-readable summary |
| `context` | string | Background the receiver needs |
| `question` | string | Used with `clarification_request` |
| `answer` | string | Used with `clarification_reply` |
| `urgency` | string | `low` / `normal` / `high` — advisory hint only |

Reserved body types (`sox-ack`, `sox-nack`, `sox-error`, `sox-invite`) have normative JSON Schemas under [spec/envelopes/](envelopes/).

---

## Architecture layers

```text
Layer 5 — System prompt (one-line bootstrap per agent)
Layer 4 — Cadence enforcer (pure function; runtime-agnostic)
Layer 3 — Discipline (markdown; runtime-agnostic)
Layer 2 — MCP server (four tools; asyncio listener)
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

---

## Spec authority

`spec/` is the canonical source. `docs/CONTRACTS.md` is a narrative mirror; when they conflict, `spec/` wins.
