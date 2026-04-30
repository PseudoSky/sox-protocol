# Decision: heartbeat-mechanism

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q2 (presence / heartbeat)

## Context
The `list_pending` + enforcer stop-block pattern depends on knowing which agents are alive. Heartbeat can be a dedicated tool (`channels__heartbeat`), a convention on a reserved system channel (`sox/presence`), or both. Heartbeat is operationally critical — wrong choice forces a breaking change later or pollutes the message log with high-frequency noise.

## Decision
**Option A — Dedicated `channels__heartbeat` tool.** Heartbeat is a first-class verb that updates a server-tracked liveness record keyed by agent-id. It does not produce a message in any channel and does not appear in replay. Observers and monitors that need a feed of presence events subscribe to a server-emitted `sox/presence` channel where the *server* publishes derived presence-change events (`agent_online`, `agent_offline`, `agent_stale`) — these are not heartbeats themselves, they are coalesced state-transitions.

## Rationale
A heartbeat is a control-plane signal, not a conversation. Putting raw heartbeats on a channel pollutes replay, inflates backing-store size linearly with agent count × heartbeat rate, and forces every consumer to filter them out. The `runtime-monitoring-tripwires-agentic.md` finding (memory) frames liveness as a tripwire concern that wants its own measurement surface, not co-mingling with the data plane. Option C's split — heartbeat tool for input, derived presence channel for observers — gets the best of both: cheap dedicated path for the common write, channel-shaped feed for the rare reader. The trade-off accepted: server must own a presence state machine (online/stale/offline with timeouts). That work is unavoidable regardless — `list_pending` already implies it.

## Consequences
- Positive: Heartbeat write path is one tool call, no envelope construction, no thread, no replay write. Cheapest possible signal.
- Positive: `sox/presence` events are coalesced (one transition per state change, not one per heartbeat). Observers get useful semantics, not raw noise.
- Positive: `list_pending` reads from the same liveness record heartbeat updates. Single source of truth.
- Negative: Two surfaces to spec (tool + reserved channel), but they serve disjoint roles.
- Negative: Server keeps in-memory or fast-store presence state; backing-store port needs a "liveness record" capability or this lives in a separate ephemeral store. Decide in `list_pending` design doc.
- Spec impact: `spec/presence.md` defines `channels__heartbeat` verb (parameters: agent_id implicit from auth, optional status hint), the liveness state machine (online/stale/offline with default timeouts), and the `sox/presence` reserved channel event shapes. `ports/backing-store.md` may gain optional "presence store" capability or delegate to a sidecar.

## Open questions for follow-up
- Default heartbeat interval and stale/offline timeouts. Suggest 10s interval, 30s stale, 90s offline; confirm against `list_pending` design doc.
- Whether heartbeat carries optional payload (current task, load) or is parameter-free. Lean parameter-free for v1; extend later.
- Whether `sox/presence` is subscribable by any agent or requires an observer role. Tie to ACL/middleware decision.
