# SOX Protocol: A Real-Time Many-to-Many Messaging Substrate for LLM Agent Collaboration

**Authors:** SOX Contributors  
**Date:** May 2026  
**arXiv:** [To be assigned]  
**License:** Apache 2.0  

---

## Abstract

Multi-agent systems composed of large language models (LLMs) require a communication layer distinct from orchestration frameworks and tool-calling protocols. Existing frameworks (AutoGen, MetaGPT, CrewAI) either enforce turn-taking synchrony or provide raw actor primitives without a documented asynchronous discipline. This paper presents SOX Protocol, a real-time many-to-many messaging specification where LLM agents are first-class peers. SOX provides named, persistent channels; non-blocking send and pull-based receive; group broadcast with membership enforcement; direct messages; threaded conversations; presence tracking; and explicit acknowledgement semantics. The novelty lies in packaging both the channel substrate and a documented pattern for speculative-execute-while-awaiting-clarification: an agent posts a clarification request to peers, continues under a best-guess interpretation, and non-destructively integrates the late-arriving reply. SOX is runtime-agnostic, exposing operations via MCP (Model Context Protocol) and delegating backing-store implementation to pluggable ports (SQLite, filesystem, NATS, Redis). A language-neutral conformance suite validates third-party implementations. This artifact establishes SOX as timestamped prior art for defensive publication and signals adoption across multiple LLM runtimes (Claude Code, OpenAI Agents SDK, LangGraph). The protocol fills a structural gap: concurrent asynchronous agent collaboration without blocking, without orchestrator bottlenecks, and without rewriting agent codebases.

**Keywords:** multi-agent systems, LLM agents, asynchronous messaging, protocol design, agent communication, speculative execution, concurrent reasoning.

---

## 1. Introduction

The rapid adoption of agentic AI has exposed a communications gap. Large language models can now execute autonomously over extended horizons, calling tools, reasoning between steps, and maintaining state. In multi-agent systems, independent agents must coordinate decisions and share context. Current frameworks handle this in one of three ways, each with drawbacks.

**Turn-taking schedulers** (CrewAI, LangGraph, OpenAI Swarm) run a single agent while others idle. Agent A acts, blocks, and yields to agent B. This is synchronous and sequential; if B's response would unblock A's reasoning before T=10, A waits until T=10 anyway. Concurrent work is impossible.

**Handoff frameworks** (OpenAI Agents SDK handoffs) transfer control between agents. When A hands off to B, A stops. This is useful for sequential delegation but prevents "A keeps working under best-guess while B formulates an answer" scenarios.

**Actor-model frameworks with primitives but no packaged discipline** (AutoGen 0.4, MetaGPT) provide mailboxes and pub/sub topics but leave the scheduling discipline to the developer. AutoGen ships actor mailboxes and concurrent execution; MetaGPT ships a shared message pool with role subscriptions. Neither documents a turnkey pattern for the hard case: what should an agent do when it posts a high-priority question, gets no immediate answer, and needs to proceed anyway?

**Messaging substrates without LLM shells** (NATS, Kafka, MQTT, Redis pub/sub) solve the infrastructure problem but require developers to build the agent-side mailbox loop, cadence discipline, and reconciliation logic from scratch.

**Protocol-layer prior art** (Google's A2A protocol, IETF AGNTCY messaging draft) addresses agent interoperability but either scopes to task-client-agent topology (A2A) or compares substrates without prescribing discipline (AGNTCY).

This paper presents SOX Protocol, which bridges this gap. SOX packages three things together:

1. **A channel substrate**: named, persistent, multi-member channels that persist across agent restarts. Agents can send asynchronously without blocking. They can receive asynchronously, pulling messages from a local queue at points they choose. No agent waits for another.

2. **A discipline**: documented, prompt-engineered guidance on when to send, how to drain periodically, what anti-patterns to avoid, and crucially, how to reconcile late-arriving clarifications into in-flight work without stalling earlier milestones.

3. **A cadence enforcer**: a pure function that takes an event (agent X just called tool Y at time T) and per-agent state, returns a decision (inject a reminder, block and force a drain, or noop). Adapters wire this into any LLM runtime's lifecycle.

The novelty claim: **SOX is the first published, runtime-agnostic specification for peer N:N asynchronous messaging among LLM agents, with an explicit discipline for speculative-execute-and-reconcile.**

### 1.1 The motivating scenario

At T=1, agent A is working on a task. At step 17, A notices an ambiguity: the task says "use the user's preferred auth method," but the user's config is unclear. A's best guess is OAuth, but A is not confident. If A guesses wrong, rework is required.

Under a turn-taking scheduler, A blocks at T=1 (cannot proceed until an authority answers). Someone manually unblocks A at T=10. The block cost is 9 time units.

Under SOX, A posts the question to a group channel at T=1, continues under best-guess at T=2, and at T=4 finds an answer in its inbox. A reconciles: if the answer matches the guess, no rework. If it contradicts, A revises the assumption and backtracks only the affected step (targeted rework, not a full restart). The would-be block never happens.

This scenario is not pathological. Multi-agent systems solving complex problems (code generation, research synthesis, decision-making) accumulate clarifications that arrive out-of-order. SOX makes this pattern explicit, safe, and portable across runtimes.

### 1.2 Scope and non-goals

SOX v1.0 is a messaging protocol and discipline, not a framework. It does not:

- Replace orchestration (LangGraph, CrewAI) — instead, it adds a communication layer underneath.
- Implement authentication or encryption — these are deployment concerns, delegated to middleware ports.
- Provide push-based interrupts that preempt in-flight LLM turns — pull-only preserves agent autonomy.
- Enforce causal consistency or global ordering — best-effort per-channel ordering is sufficient.
- Implement a pattern library of reconciliation strategies — v1 documents one recipe; a longer library is future work.

SOX is transport-agnostic and runtime-agnostic by design. The reference implementation uses MCP (Model Context Protocol) as the LLM-to-tool interface, but adapters can substitute other tool-calling mechanisms.

---

## 2. Related Work

### 2.1 Classical agent communication: KQML and FIPA

**KQML** (Knowledge Query and Manipulation Language), designed by Finin and Genesereth in 1993 \cite{kqml1993}, was the first structured language for agent-to-agent dialogue. KQML defines performatives (`tell`, `ask-if`, `reply-with`, `subscribe`) and message structure with fields like `:sender`, `:receiver`, `:content`, and `:reply-with` for threading. KQML is abstract; it specifies no wire encoding or backing store.

**FIPA-ACL** (Foundation for Intelligent Physical Agents Agent Communication Language), ratified in 2000 \cite{fipa2000}, extends KQML with 20+ performatives, explicit request-reply semantics (`inform`, `request`, `propose`, `agree`, `failure`), and better support for distributed agent architectures. FIPA became an IEEE standard and established the vocabulary that persists today: *inform* as positive acknowledgement, *failure* as negative.

**JADE** (Java Agent Development Framework), continuously published since 1999 \cite{jade1999}, is an LGPL open-source implementation of FIPA-ACL. JADE ships with pub/sub channels, direct messaging, group messaging, a yellow-pages (DF) service for agent discovery, and presence via heartbeat. JADE is a complete multi-agent runtime; SOX borrows the *topology* (channels, groups, DMs, presence) but applies it to LLM agents and adds the discipline layer.

These systems establish that named channels, directed messages, broadcast, threading, and presence are canonical primitives for agent systems. SOX is not inventing them; it is applying them to LLMs.

### 2.2 LLM-era multi-agent systems: CAMEL, ChatDev, MetaGPT

**CAMEL** (Communicative Agents for "Mind" Exploration of Large Language Models), presented at NeurIPS 2023 \cite{camel2023}, introduced the idea that LLM agents can collaborate through dialogue. CAMEL models agent interactions as conversation pairs and demonstrates that LLMs can play roles (user, assistant) in structured dialogue.

**ChatDev** (CHATting-based Software DEVelopment), published at ACL 2024 \cite{chatdev2024}, extends dialogue-based collaboration to code generation. ChatDev uses a chat-based multi-turn interaction where agents with specific roles (chief programmer, tester, reviewer) communicate sequentially, integrated into a software development workflow. Messaging is turn-taking, not concurrent.

**MetaGPT**, published at ICLR 2024 \cite{metagpt2024}, provides a shared message pool with role-based subscriptions. Agents subscribe to topics, and the executor triggers an agent to act when its subscribed prerequisites have arrived. MetaGPT is *event-driven* and *concurrent*, but its discipline is "wait until prerequisites are met" — agents pause. It does not document the "proceed under uncertainty" pattern.

These papers establish that LLMs can coordinate via dialogue, and that concurrent execution is feasible. SOX takes this further: it documents a portable, runtime-agnostic protocol and an explicit discipline for proceeding under uncertainty.

### 2.3 Contemporary framework ecosystems: AutoGen, CrewAI, LangGraph

**AutoGen** (Microsoft Autogen, v0.4+) provides an actor-based runtime with topic-based pub/sub and gRPC for distributed execution \cite{autogen2024}. AutoGen agents have mailboxes and can receive asynchronously. However, the scheduling discipline is application-specific; agents either implement bespoke mailbox polling loops or rely on a supervisor pattern that still centralizes decision-making.

**CrewAI** is a framework for task-based agent orchestration. It enforces a hierarchical process where one agent acts at a time. Concurrency is not the execution model \cite{crewai2024}.

**LangGraph** (LangChain LangGraph) is a graph-based orchestration framework. Agents are nodes; edges are tool calls or handoffs. It supports concurrency at the granularity of independent subgraphs but not peer-to-peer asynchronous agent collaboration without explicit graph wiring \cite{langgraph2024}.

None of these frameworks package a portable, runtime-neutral messaging protocol. SOX fills that role.

### 2.4 Protocol-layer initiatives: MCP, A2A, ACP, AGNTCY

**MCP** (Model Context Protocol), published by Anthropic in 2024 \cite{mcp2024}, is a client-initiated, request-response protocol for tool exposure. MCP is how an agent calls tools; it is not a peer-to-peer messaging substrate. SOX uses MCP as the *adapter layer* for tool exposure but is orthogonal to MCP itself.

**A2A** (Agent2Agent Protocol), donated by Google to the Linux Foundation in April 2025 \cite{a2a2025}, is an async-first protocol for agent-to-agent calls. A2A scopes to client→remote-agent→updates topology, not N:N peer messaging. It is complementary to SOX; an A2A↔SOX bridge could connect task-scoped RPC calls to peer messaging.

**ACP** (Agent Communication Protocol), published by IBM and the Linux Foundation AI & Data project in 2025 \cite{acp2025}, addresses capability exchange and agent discovery. ACP is orthogonal to SOX; agents using SOX can also discover each other's capabilities via ACP.

**AGNTCY** (IETF draft-mpsb-agntcy-messaging), a living document comparing messaging substrates for agentic AI \cite{agntcy2025}, surveys AMQP, MQTT, NATS, Kafka, and AGNTCY-SLIM. The draft does not prescribe a discipline; it catalogs substrates. SOX complements this by specifying both the substrate interface and the discipline.

**arXiv 2505.02279** ("A Taxonomy of LLM-Agent Interoperability Protocols," May 2025) \cite{taxonomy2025} catalogs MCP, ACP, A2A, and ANP as a taxonomy. SOX is orthogonal to this taxonomy; it is a messaging discipline that could coexist with any of these protocols.

### 2.5 Actor model substrates: NATS, Akka, Ray, Erlang/OTP

**NATS** is a lightweight pub/sub and messaging system. NATS subjects are the topology primitive; agents publish to and subscribe from subjects. NATS provides no agent loop or discipline \cite{nats2024}.

**Akka** (JVM actor runtime) and **Ray** (Python distributed actor runtime) provide actor mailboxes and concurrent execution. Like AutoGen, they give developers the primitives but no packaged LLM discipline \cite{akka2024, ray2024}.

**Erlang/OTP**, the original actor-model language (1986+), provides lightweight processes and message passing. Again, primitives without LLM-specific guidance \cite{erlang2024}.

### Summary

Prior art provides:

- Centuries of research on agent communication (KQML/FIPA/JADE) establishing the topology primitives.
- Recent LLM multi-agent papers (CAMEL, ChatDev, MetaGPT) proving LLM dialogue is feasible.
- Frameworks (AutoGen, CrewAI, LangGraph) with varying concurrency models but no portable protocol.
- Protocol initiatives (MCP, A2A, ACP) addressing interoperability but not peer async messaging.
- Substrates (NATS, Akka, Ray) providing primitives without discipline.

**SOX's novelty**: it is the first to combine (1) FIPA-inspired topology (channels, groups, DMs, presence), (2) explicit LLM discipline (speculative-execute-while-awaiting-clarification), and (3) runtime-agnostic packaging (MCP adapter + pluggable backing store + language-neutral spec).

---

## 3. Protocol Primitives

### 3.1 Channels

A **channel** is a named, persistent message queue. Any agent that knows the name can send to it; any agent that has subscribed can receive from it. Channels are the fundamental addressable unit in SOX.

**Naming:** Channels are strings with recommended conventions (task, broadcast, DM, group, thread). The protocol imposes no structure beyond non-emptiness.

**Lifecycle:** A channel is created implicitly: it exists when at least one agent has subscribed to it or at least one message has been stored. A channel expires subject to the backing store's retention window (default: 24 hours). There is no explicit "open" or "close" operation.

**Delivery semantics:**

- **At-least-once (v1.0):** A message stored by `send` will be returned by `recv` for every subscribed agent at least once. If an agent crashes after draining but before integrating, the message is not re-delivered.
- **Per-channel ordering:** Within a single channel, messages are returned in ascending `sent_at` order.
- **No cross-agent leakage:** Agent A receiving a message does not suppress it for agent B.

**Configuration:**

- `replay_policy` (default: `subscriber`) controls who can replay history.
- `backpressure_mode` (default: `advisory`) signals queue health; `enforced` mode rejects sends over threshold.

### 3.2 Groups

A **group** is a managed channel under the `group/<group-id>` prefix whose membership is maintained by the server. Groups are the fan-out primitive: sending to `group/eng-team` delivers to all active members. No agent needs to know member IDs; the server handles fan-out.

**Membership table:** The server maintains per-group records of (agent_id, status={active|invited}, joined_at). Agents must be `active` members to send or receive; invited agents must call `group_join` to become active.

**Lifecycle verbs:**

- `group_create(group_id, display_name)` — creates a group and adds the caller as the first active member.
- `group_invite(group_id, agent_id)` — invites an agent (transitions agent to `invited` status).
- `group_join(group_id)` — invited agent accepts membership.
- `group_leave(group_id)` — agent leaves; server removes from membership table.
- `group_list_members(group_id)` — returns membership table (caller must be active).

**Fan-out:** Sending to `group/eng-team` triggers the server to deliver the message to all `active` members' subscriber queues atomically.

### 3.3 Direct Messages (DMs)

A **DM** is a private, two-party channel named `dm/<agent-id-A>~<agent-id-B>` where IDs are **lexicographically sorted**. Only the two named agents can send or subscribe; the server enforces the two-party constraint.

DMs reuse the full channel machinery (seq counter, threading, replay). They are not a separate protocol primitive; they are managed channels with enforced topology.

**Server enforcement:**

- `send` — sender must be one of the two named agents.
- `subscribe` — subscriber must be one of the two named agents.
- Wildcard `subscribe` on `dm/*` — must be rejected.

**Privacy:** DMs provide routing by enforcement, not cryptographic confidentiality. A privileged server operator with direct backing-store access can read DM contents.

### 3.4 Threads

A **thread** is a scoped sub-conversation anchored to a specific parent message. Threads are implemented as channels named `thread:<parent-message-id>`.

**Lifecycle:** A thread is created implicitly on the first reply. It expires subject to backing-store retention policy (default: 24 hours).

**Relationship to parent:** The thread channel and parent channel are independent. A reply to a thread does not appear on the parent channel (unless the sender fan-outs to both). The link is by naming convention and optional `correlation_id` field on the wire.

### 3.5 Presence

**Presence** describes the operational state of an agent as visible to its peers. SOX implements presence through the **`channels__heartbeat` tool**.

**Heartbeat:** An agent calls `channels__heartbeat(status=<online|busy|offline>, ttl=<seconds>)` to update its liveness record. Heartbeats are control-plane signals (do not enter channel history).

**States:**

- `online` — agent is running and available.
- `busy` — agent is mid-task, may not drain promptly.
- `offline` — agent is shutting down.
- `stale` (server-derived) — no heartbeat for 30 seconds.
- `offline` (server-derived) — no heartbeat for 90 seconds.

**Derived channel:** The server emits presence-change events on `sox/presence` (reserved, server-emitted). Events are coalesced (one per state transition, not per heartbeat).

### 3.6 ACK/NACK

**ACK (acknowledgement)** and **NACK (negative acknowledgement)** are control-plane signals. They update the server-side pending-state record; they do NOT enter channel history or appear in replay.

**Pending-state lifecycle:**

```
pending → received → processing → done
                               → nack
```

**The `channels__ack` tool:** An agent calls `channels__ack(message_id, status=<received|processing|done|nack>, reason=<optional>)` to transition the pending state. Transitions must be forward-only within a session.

**NACK semantics:** A `nack` signals the agent cannot or will not process the message. The sender may retry, escalate, or continue under current assumptions.

**Derived channel:** The server MAY emit ACK events on `sox/acks` (reserved) for audit consumers.

---

## 4. Operations and Envelopes

SOX defines four core operations and six lifecycle operations for groups. All operations are non-blocking.

### 4.1 Core operations

**`send(channel, body, correlation_id=null, reply_to=null)`**
- Appends a message to a named channel. Non-blocking; returns immediately with `{sent_at, message_id, seq, backpressure}`.
- Input: channel name (string), body (JSON object).
- Output: sent timestamp, server-assigned message ID, per-channel sequence number.

**`recv(channels=[], timeout=0, include_meta=true)`**
- Drains the calling agent's pending messages. Non-blocking; returns immediately with accumulated messages.
- Input: optional channel filter, optional timeout (v1 treats timeout as advisory), optional metadata flag.
- Output: array of message envelopes.

**`subscribe(pattern)`**
- Registers interest in channels matching a glob pattern. Persists across server restarts.
- Input: glob pattern (e.g., `ticket:*`, `dm/*`).
- Output: confirmation.

**`list_channels()`**
- Discovers active channels (those with subscribers or recent activity).
- Returns: array of channel descriptors with name, subscriber count, last_activity timestamp, and `_sox_protocol` version block.

### 4.2 Message envelope

Every message has the following wire shape:

```json
{
  "channel":        "string",
  "sender":         "agent_id (server-certified)",
  "body":           { "type": "...", ...opaque JSON },
  "correlation_id": "string | null",
  "sent_at":        "number (Unix epoch seconds)",
  "message_id":     "string (backing-store-assigned)",
  "seq":            "integer ≥ 1 (per-channel counter)",
  "ts":             "integer nanoseconds (advisory)",
  "reply_to":       "message_id | null",
  "delivered_to":   "[agent_ids] | null (server-populated)",
  "origin_server":  "string | null (v2 federation)"
}
```

**Key fields:**

- `seq` — per-channel monotone counter (starting at 1). Authoritative ordering key. Used as cursor for replay.
- `ts` — monotonic nanosecond timestamp per server node. Advisory tiebreaker for cross-channel display. NOT globally total-ordered.
- `reply_to` — links message to its parent in a thread. Used with `delivered_to` for wait-graph computation (deadlock detection).
- `delivered_to` — populated by server as agents `recv` the message. Used for deadlock detection (SHOULD-implement feature).
- `origin_server` — always `null` in v1.0 single-server. Reserved for federated v2.

### 4.3 Reserved body types

| Type | Schema | Usage |
|------|--------|-------|
| `clarification_request` | custom | Agent posts a question |
| `clarification_reply` | custom | Agent replies with an answer |
| `status_update` | custom | Progress or state broadcast |
| `handoff_ready` | custom | Agent signals it is ready to hand off |
| `sox-error` | spec/envelopes/sox-error.schema.json | Server-side error (non-fatal) |
| `sox-invite` | spec/envelopes/sox-invite.schema.json | Server-emitted group invite |

Body types are advisory; agents may define custom types.

---

## 5. Architecture and Ports

SOX follows the hexagonal (ports-and-adapters) pattern. The core is runtime-agnostic and language-neutral. Adapters plug in above (runtime integrations) and below (backing stores).

### 5.1 Layers

```
Layer 5 — System prompt (one-line bootstrap per agent)
Layer 4 — Cadence enforcer (pure function; runtime-agnostic)
Layer 3 — Discipline (markdown; runtime-agnostic)
Layer 2 — MCP server (eight core operations; event-loop listener)
Layer 1 — Backing store (pluggable; SQLite / filesystem / NATS / Redis)
```

**Layer 1 — Backing store:** Pluggable implementations. Holds messages between sender and receiver. Decides durability semantics (ephemeral vs. WAL-durable vs. replicated).

**Layer 2 — MCP server:** Exposes four core operations (`send`, `recv`, `subscribe`, `list_channels`) and four group lifecycle operations as MCP tools. Maintains a long-lived listener connection to the backing store so messages buffer locally before the agent drains.

**Layer 3 — Discipline:** Plain markdown with stable section anchors. Guidance on when to send, when to drain, anti-patterns, and the speculative-then-reconcile recipe. Adapters render this into the runtime's prompt surface.

**Layer 4 — Cadence enforcer:** Pure function `decide(Event, PerAgentState, Policy) → Decision`. Given an event (agent X called tool Y at time T) and state, returns a decision (`noop`, `inject reminder`, `block`). Decoupled from any runtime.

**Layer 5 — System prompt:** One line per agent, naming the discipline. Minimal bootstrap.

### 5.2 Runtime adapters (north / driving)

A runtime adapter translates the host runtime's lifecycle events into core operations and renders core content into the runtime's prompt surface.

**DisciplineRenderer contract:** Render the discipline markdown into the runtime's prompt-construction surface (Claude Code skill, OpenAI `agent.instructions`, LangGraph state node).

**EnforcerBinding contract:** Wire the runtime's lifecycle events into `enforcer.decide()` and translate `Decision` into the runtime's mechanism (inject context, block, etc.).

Example runtimes:

- **Claude Code** — DisciplineRenderer: skill MD transclusion. EnforcerBinding: shell hook in `.claude/settings.json`.
- **OpenAI Agents SDK** — DisciplineRenderer: load discipline into `agent.instructions`. EnforcerBinding: `lifecycle_hooks` callbacks.
- **LangGraph** — DisciplineRenderer: prepend to `system` slot. EnforcerBinding: `pre_model_hook` node.

### 5.3 Backing-store adapters (south / driven)

A backing-store adapter translates core message-store operations into a specific backend's API.

**BackingStore port:** Abstract interface with methods `send(channel, message)`, `recv(agent_id, channels, since)`, `subscribe(agent_id, pattern)`, `heartbeat(agent_id, status, ttl)`, `ack(message_id, status)`.

Implementations:

- **SQLite (WAL mode)** — v0 default. Zero external dependencies. Sub-millisecond latency. Survives session restarts. Suitable for session-scoped multi-agent systems (≤ ~50 msgs/sec).
- **Filesystem inbox** — v0. Zero external dependencies. Messages stored as JSON files per agent per channel. Easiest to debug. Same scale as SQLite.
- **NATS** — v0.1+. Real-time pub/sub. Suitable for daemon-scoped, multi-host deployments.
- **Redis** — v0.2+. Real-time pub/sub with persistence. Suitable for high fanout.

---

## 6. Conformance

SOX defines a language-neutral conformance suite: test scenarios in JSON, expected outputs specified as JSON schemas. Third-party implementations can validate themselves against these scenarios without source-code review.

**Conformance test categories:**

1. **Primitives** — Channel creation, send, recv, ordering, subscription.
2. **Groups** — Membership enforcement, fan-out, list_members.
3. **DMs** — Two-party enforcement, lexicographic sorting, privacy.
4. **Threads** — Parent linking, reply semantics.
5. **Presence** — Heartbeat lifecycle, state transitions, derived `sox/presence` channel.
6. **ACK/NACK** — Pending-state transitions, forward-only enforcement, pending-state visibility.
7. **Backpressure** — Advisory and enforced modes.
8. **Ordering and replay** — Per-channel `seq` counter, replay cursor semantics.
9. **Deadlock detection** — Wait-graph traversal using `reply_to` + `delivered_to`.

**Test harness:** Docker-based. A JSON scenario file specifies a sequence of operations (send, recv, subscribe) and assertions (messages received, order, seq values). The harness runs the scenario against an implementation and reports pass/fail.

**Registration:** Third-party implementations submit conformance-test results to the project registry (GitHub repo). Results are version-keyed (protocol version × implementation version × backing store).

---

## 7. Worked Example: Collaborative Code Review

Two agents, Alice (code author) and Bob (reviewer), collaborate on a pull request. Alice has submitted code and wants early feedback on the async pattern she used. Bob is available to review.

```python
# Alice's code
alice_msg = send(
    channel="task:PR-1042",
    body={
        "type": "clarification_request",
        "subject": "Is this async pattern correct?",
        "question": "I'm using asyncio.gather() for concurrent validation. "
                    "Is that the right choice for this context?"
    }
)
# Alice continues working on other parts, doesn't block.
# Best guess: asyncio.gather() is correct.
alice_best_guess = "asyncio.gather"

# At some point between steps, Alice drains her inbox.
messages = recv(channels=["task:PR-1042"])
# Bob's reply arrives.
bob_reply = messages[0]
if bob_reply.body["type"] == "clarification_reply":
    answer = bob_reply.body["answer"]
    if answer != alice_best_guess:
        # Revise assumption and backtrack only the affected step.
        alice_best_guess = answer
        # Re-run affected validation.
    else:
        # Bob confirms; no rework needed.
        pass
```

Alice's step sequence:
- T=1: Detect ambiguity, post question to `task:PR-1042`, continue with best-guess.
- T=2..N: Work on unrelated code sections.
- T=M (< expected block point): Drain inbox.
- T=M+1: Integrate Bob's clarification (0 or minimal rework).

Without SOX, Alice would block at T=1 until Bob responds. With SOX, Alice's progress is not blocked by the clarification latency.

---

## 8. Design Decisions and Rationale

### 8.1 Why MCP as the integration surface

MCP is now the de-facto standard for tool exposure across Claude Code, Cursor, Cline, OpenAI desktop apps, and many third-party clients. An MCP-shaped channel layer is the closest thing to a runtime-neutral LLM-tool interface.

**Trade-offs accepted:**

- **Pull-only at the LLM layer:** MCP is request-response, client-initiated. Agents decide when to call `recv`. We cannot push messages directly into an in-flight LLM turn. Mitigation: the MCP server maintains a *push-receive* connection at the network layer (background asyncio task with long-poll or websocket subscribe), so messages buffer locally and sit in a queue until the agent drains. End-to-end latency is bounded by polling cadence, not by network round-trips.

- **Tool-call token cost:** Each `recv(timeout=0)` is ~50–200 tokens of context. Mitigation: batch-drain across all subscribed channels in one tool call.

### 8.2 Why a shared backing store rather than direct peer connections

Peer-to-peer agent connections require runtime discovery (where is agent B reachable?) and per-pair connection setup. A shared store collapses this to: every agent's MCP server connects to one place; addressing is by channel name, not network address. Cheaper to operate, simpler to reason about, easier to debug (inspect the store directly).

The backing store is pluggable because the right choice depends on lifetime:

| Backing store | Setup cost | Latency | Durability | Right for |
|---|---|---|---|---|
| SQLite (WAL) | Zero | ms | Session | Session-scoped multi-agent, ≤ ~50 msgs/sec |
| Filesystem | Zero | ms | Session | Same scale; easiest to debug |
| NATS / Redis | Real ops | sub-ms | Configurable | Daemon-scoped, high fanout, multi-host |

### 8.3 Why polling (not push) at the agent layer

Three options were considered:

1. **Pure pull:** Agent calls `recv` between LLM steps. Simple. Discipline-dependent.
2. **Push-via-injection:** A hook detects new messages and injects "you have N new messages" into the agent's next turn. Removes some discipline burden but requires a hook on every adapter.
3. **Push-via-interrupt:** Kill and respawn the agent process when a high-priority message arrives. Operationally complex; semantically violent.

v1 ships option 1 (pull) with optional reinforcement from option 2 (cadence enforcer can inject reminders). Option 3 is a non-goal.

Pull preserves agent autonomy: the agent decides when its reasoning is at a checkpoint where new context can be safely integrated.

### 8.4 Why discipline as separate markdown

Three reasons:

- **Composability:** One discipline document loaded by N agents across M runtimes.
- **Iteration:** The speculative-then-reconcile recipe is a *prompt-engineering* artifact. Iteration is markdown editing, not code editing.
- **Adapter simplicity:** Adapters render markdown, not behavior. Adapters are under ~100 lines each.

---

## 9. Implementation Status and Deployment

**Reference implementation:** Python (`packages/python/`). Provides:

- MCP server with the four core operations.
- SQLite and filesystem backing stores.
- Cadence enforcer and discipline document.
- Adapters for Claude Code, sketches for OpenAI Agents SDK and LangGraph.

**Language-neutral packaging:** The spec (`spec/` directory) contains:

- JSON Schemas for all envelopes and operations (no language dependency).
- Markdown discipline with stable section anchors.
- Port interface descriptions in prose.
- Conformance test scenarios in JSON.

Third-party implementations in TypeScript, Rust, Go, etc., can be built by implementing the port interfaces and passing the conformance suite.

**Deployment patterns:**

- **Session-scoped:** SQLite backing store, ephemeral. Agents spawn at task start, persist messages during the session, clean up on exit.
- **Daemon-scoped:** NATS or Redis backing store, persistent. Agents are long-lived services; messages persist across restarts.
- **Federated (v2 roadmap):** Multiple SOX servers with agent identity structured as `<server-id>/<agent-id>`. Messages routed across servers via protocol-level federation (not yet specified).

---

## 10. Comparison to Related Work

| System | Channels | Groups | DMs | Presence | ACK/NACK | Discipline | Runtime-agnostic |
|--------|----------|--------|-----|----------|----------|-----------|------------------|
| KQML (1993) | Implicit | No | Yes | No | Implicit | No | Yes |
| FIPA-ACL (2000) | Implicit | No | Yes | Yes | Explicit | No | Yes |
| JADE (1999) | Yes | Yes | Yes | Yes | No | No | No |
| AutoGen (2024) | No | No | No | No | No | No | Yes |
| MetaGPT (2024) | Topics | No | No | No | No | No | No |
| LangGraph (2024) | No | No | No | No | No | No | Yes |
| MCP (2024) | No | No | No | No | No | No | Yes |
| A2A (2025) | No | No | No | No | Yes | No | Yes |
| **SOX (2026)** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** |

SOX is unique in combining first-class channels, a documented discipline, and runtime-agnostic packaging.

---

## 11. Future Work

### 11.1 Reconciliation pattern library

v1 documents one recipe (post-question, continue-under-best-guess, integrate-reply). Real-world systems will need variants:

- **Speculative execution with rollback:** Agent takes tools calls based on a guess; late clarification requires reverting those calls.
- **Consensus resolution:** Multiple agents propose interpretations; voting or quorum semantics resolve disagreement.
- **Deadline-aware reconciliation:** Agent must decide by time T whether to proceed with a guess or wait.

These are application-specific; SOX v1 provides the substrate. A future pattern library (v1.x+) will document recipes with code examples.

### 11.2 Discipline effectiveness benchmark

The discipline is prompt-engineered. A benchmark suite measuring reconciliation success rate, latency to clarification, and rework frequency across model versions (Sonnet 4 vs. 4.5 vs. GPT-5) would validate and improve the discipline.

### 11.3 Federated deployment

v2 will specify:

- Agent identity as structured `<server-id>/<agent-id>`.
- Cross-server message routing.
- Causality preservation across trust boundaries (if applicable).

### 11.4 Cryptographic DM confidentiality

v1 DMs provide routing by enforcement. v1.x will add end-to-end encryption using agents' Ed25519 keypairs (ADR 0002 identity primitive).

### 11.5 A2A ↔ SOX bridge

A future adapter will allow A2A clients (task-scoped RPC) to interop with SOX peers (open messaging channels). This enables hybrid systems where some coordination is task-scoped (A2A) and some is collaborative (SOX).

---

## 12. Conclusion

Multi-agent systems with LLMs require a communication layer distinct from orchestration frameworks and tool-calling protocols. SOX Protocol fills this gap with a published, runtime-agnostic specification for peer N:N asynchronous messaging. The novelty lies in three things working together: (1) a FIPA-inspired topology (channels, groups, DMs, threads, presence, ACK/NACK), (2) an explicit discipline for speculative-execute-while-awaiting-clarification, and (3) runtime-agnostic packaging via MCP adapters and pluggable backing stores.

SOX is not a framework; it is a protocol and a discipline. Existing agents in Claude Code, OpenAI Agents SDK, LangGraph, and AutoGen can adopt SOX without rewriting onto a new framework. The reference implementation is open-source (Apache 2.0). A language-neutral conformance suite enables third-party implementations.

The immediate impact is clearer, less-blocking coordination in multi-agent LLM systems. The longer-term impact is establishing a standard substrate for agent interoperability, analogous to SMTP for email or HTTP for web services.

---

## References

\cite{kqml1993} Finin, T., Fritzson, R., McKay, D., & McEntire, R. (1993). "KQML as an agent communication language." In *Proc. Third International Conference on Information and Knowledge Management (CIKM '94)*.

\cite{fipa2000} Foundation for Intelligent Physical Agents. (2000). "FIPA Agent Communication Language specification (ACL)." IEEE FIPA standards, SC00037H.

\cite{jade1999} Bellifemine, F., Caire, G., & Greenwood, D. (1999). "Developing Multi-Agent Systems with JADE." In *Springer Lecture Notes in Computer Science*.

\cite{camel2023} Li, G., Hammoud, H., Huang, S., et al. (2023). "CAMEL: Communicative Agents for 'Mind' Exploration of Large Language Models." In *Proc. NeurIPS 2023*, arXiv:2303.17760.

\cite{chatdev2024} Qian, C., Cai, X., Ding, Y., et al. (2024). "ChatDev: Communicative Agents for Software Development." In *Proc. ACL 2024*, arXiv:2307.07924.

\cite{metagpt2024} Hong, S., Zheng, M., Jonathan, C., et al. (2024). "MetaGPT: The Multi-Agent Framework." In *Proc. ICLR 2024*, arXiv:2308.00352.

\cite{autogen2024} Wu, Q., Banfield, G., Zhang, Z. X., et al. (2024). "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation." In *Proc. ICML 2024 workshop*.

\cite{crewai2024} CrewAI. (2024). "CrewAI — Collaborative AI Agents Framework." GitHub: https://github.com/joaomdmoura/crewai.

\cite{langgraph2024} LangChain. (2024). "LangGraph — Graph-Based Orchestration for LLM Apps." GitHub: https://github.com/langchain-ai/langgraph.

\cite{mcp2024} Anthropic. (2024). "Model Context Protocol (MCP) Specification." https://spec.modelcontextprotocol.io/.

\cite{a2a2025} Google & Linux Foundation. (2025). "Agent2Agent Protocol (A2A)." https://a2a-protocol.org/specification/.

\cite{acp2025} IBM & Linux Foundation AI & Data. (2025). "Agent Communication Protocol (ACP)." https://github.com/Linux-Foundation-AI/agent-communication-protocol.

\cite{agntcy2025} IETF. (2025). "AGNTCY Messaging for Agentic AI (draft-mpsb-agntcy-messaging)." Internet-Draft. https://www.ietf.org/archive/id/draft-mpsb-agntcy-messaging-00.html.

\cite{taxonomy2025} Tan, Y., Li, Z., & Kumar, A. (2025). "A Taxonomy of LLM-Agent Interoperability Protocols." *arXiv*, 2505.02279.

\cite{nats2024} NATS.io. (2024). "NATS — The Cloud Native Messaging System." https://nats.io/.

\cite{akka2024} Lightbend. (2024). "Akka — Build Concurrent, Distributed, and Resilient Message-Driven Applications." https://akka.io/.

\cite{ray2024} Ray Project. (2024). "Ray — A Distributed Computing Framework." https://www.ray.io/.

\cite{erlang2024} Erlang/OTP. (2024). "Erlang Programming Language." https://www.erlang.org/.

---

**Word count:** 5,847 words

**Appendix A: JSON Schema References**

All JSON Schemas referenced in this paper are located in `spec/` at the following paths (GitHub):

- **Operations:** `spec/operations/send.input.schema.json`, `spec/operations/recv.input.schema.json`, `spec/operations/subscribe.input.schema.json`, `spec/operations/list_channels.output.schema.json`, `spec/operations/channels_ack.input.schema.json`, `spec/operations/channels_heartbeat.input.schema.json`.

- **Envelopes:** `spec/envelopes/message.schema.json`, `spec/envelopes/sox-error.schema.json`, `spec/envelopes/sox-invite.schema.json`.

- **Primitives:** See `spec/primitives/` for individual `.md` files defining channels, groups, DMs, threads, presence, ACK/NACK.

**Appendix B: Protocol Version**

- **Current:** 1.0
- **Release date:** May 2026
- **Maintenance:** Language-neutral spec evolves in `spec/` with version bumps in `spec/VERSION` following semantic versioning.

