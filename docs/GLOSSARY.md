# SOX Protocol — Glossary

Precise definitions of terms used throughout this protocol. The field uses several of these words inconsistently; the definitions below are normative for the SOX documents.

---

## Conformance suite

The language-neutral test harness in `spec/conformance/`. Defines scenarios as JSON files; runs them against any implementation that exposes a SOX MCP server. Pass-or-fail is the verification authority for whether a language implementation is "SOX v1.0-compliant." See [CONTRACTS.md](./CONTRACTS.md) §10.

## Package

A language-specific implementation of the SOX protocol, living in `packages/<lang>/` in the monorepo. v0 implements `packages/python/`; `packages/typescript/` and `packages/rust/` are placeholder directories with READMEs that document the conformance bar and invite community contributions.

## Port binding

A specific language's expression of a port. The `BackingStore` ABC in `packages/python/src/sox_protocol/core/ports/backing_store.py` is the *Python binding* of the `BackingStore` port; the *port itself* is specified in prose at `spec/ports/backing-store.md`. Different language packages have different bindings; all bindings must conform to the same port spec.

## Reference implementation

The language implementation maintained in this repo as the canonical worked example of how to bind to the protocol. v0 ships `packages/python/` as the reference implementation. Other-language implementations are welcomed but not required to be canonical — passing the conformance suite is what makes them SOX-compliant, not being in this repo.

## Spec (the SOX spec)

The canonical, language-neutral artefact in `spec/`. Contains:

- `spec/schemas/` — JSON Schema files for the enforcer internals (`Event`, `Decision`, `Policy`, `State`) and the canonical wire envelope (`Message`), plus MCP tool I/O schemas under `spec/schemas/tools/` for the stdio MCP binding. For the full 15-operation schema surface, see `spec/operations/`. Both directories are kept in sync and are each authoritative for their respective binding.
- `spec/operations/` — adapter-neutral JSON Schema files for all 15 v1 operations. Used by the HTTP transport and conformance suite.
- `spec/discipline/` — the markdown discipline document with stable section anchors and `{{placeholder}}` tool-name tokens, plus worked examples.
- `spec/ports/` — port behaviour contracts in prose (`backing-store.md`, `transport.md`, `identity.md`, `middleware.md`, `runtime-discipline-renderer.md`, `runtime-enforcer-binding.md`).
- `spec/conformance/` — language-neutral test harness with JSON scenario files.

The spec is the protocol. Implementations consume from `spec/` and conform to it.

## Adapter

A thin shim between the runtime-agnostic SOX core and a specific agent runtime (Claude Code, OpenAI Agents SDK, LangGraph, etc.). An adapter implements two contracts: **DisciplineRenderer** and **EnforcerBinding** (see [CONTRACTS §7](./CONTRACTS.md#7-adapter-conformance-checklist)). Adapters contain no business logic; they only translate between the runtime's conventions and the SOX core.

## Agent

An LLM-driven autonomous process with a distinct identity, capable of taking actions (typically via tools) over multiple LLM turns. In SOX, an agent must have:

- a stable string identifier (its `agent_id`),
- a persistent process or runtime that can hold state between turns,
- access to the four SOX MCP tools.

Excluded: "agents" that are pure single-turn LLM calls without state or process identity.

## Backing store

The persistence layer of SOX. Holds messages and subscriptions on behalf of the MCP server. Pluggable: SQLite (default), filesystem, in-memory, NATS, Redis, etc. Defined by the `BackingStore` interface in [CONTRACTS §6](./CONTRACTS.md#6-backing-store-interface).

## Bootstrap line

The minimal one-line snippet inserted into a participating agent's system prompt that names the discipline document. Its purpose is to make the existence of channels known so the agent can elect to load the full discipline when relevant. Distinct from embedding the full discipline in the system prompt (which v0 explicitly rejects in favour of progressive disclosure).

## Broker

An optional external messaging service (NATS, Redis, Kafka). In SOX terminology, a broker is one possible *implementation* of the backing store. Used loosely in some other literature to mean any messaging substrate; SOX prefers "backing store" for the abstract role and "broker" only for external broker-shaped implementations.

## Cadence enforcer

The pure-function component that decides whether to inject reminders or block actions based on the agent's tool-call history. Signature: `decide(event, state, policy) → decision`. Runs in adapters in response to runtime lifecycle events. Not the same as the discipline (which is prose) — the enforcer is deterministic logic; the discipline is opinionated guidance.

## Channel

A named, multi-member messaging topic. SOX channels:

- have string names (e.g., `ticket:ENGI-0042`),
- accept any number of senders and receivers (1:1, 1:N, N:N),
- are created implicitly on first send,
- persist as long as the backing store keeps the messages (backing-store-dependent retention).

Distinct from **subscription**: a channel exists in the backing store; a subscription is an agent's expressed interest in receiving messages from one or more channels.

## Channel pattern

A glob-style string used for subscription. Examples: `ticket:ENGI-0042` (exact), `ticket:ENGI-*` (glob). Defined per [CONTRACTS §5.3](./CONTRACTS.md#53-channels__subscribe).

## Correlation ID

An optional string field on a message used to associate replies with the request they answer. SOX does not enforce request/reply semantics on correlation IDs; they are advisory metadata for sender and receiver convention.

## Discipline (the SOX discipline)

The runtime-agnostic markdown document containing opinionated guidance on when and how to use channels: when to send, polling cadence, the speculative-then-reconcile recipe, anti-patterns, and what not to use channels for. Has stable section anchors per [CONTRACTS §2](./CONTRACTS.md#2-discipline-document-structure) so adapters can render it consistently.

Distinct from the cadence enforcer: the discipline is what the agent reads; the enforcer is what runs deterministically around the agent.

## Drain (verb)

To call `channels__recv` and consume messages from the local mailbox. The discipline specifies when an agent should drain (between major decisions; before stop). The cadence enforcer can inject reminders when an agent has not drained for too long.

## Enforcer

Short for **cadence enforcer**.

## Event

The input to the cadence enforcer's `decide()` function. A typed record of something that happened in the runtime: a tool was used, a turn started, the agent is about to stop, etc. Defined in [CONTRACTS §3.1](./CONTRACTS.md#31-event).

## Group channel

A channel with N>1 members on either send or receive side (most often both). The default scoping for collaborative work in SOX (e.g., all agents on a ticket join `ticket:<id>`).

## Handoff

In other multi-agent literature (OpenAI Agents SDK, CrewAI hierarchical), "handoff" means transferring control: agent A stops, agent B starts. **SOX does not use this meaning.** SOX channels are not handoffs; both agents continue to run. When a SOX message body has `type: "handoff_ready"`, that is a *protocol signal* between two concurrently-running agents, not a control transfer.

## Hook

In SOX adapter contexts: a runtime-specific lifecycle interception point where the cadence enforcer is called. In Claude Code: configured in `.claude/settings.json` as `PreToolUse`, `PostToolUse`, `Stop`, etc. In other runtimes the same concept appears under names like `lifecycle_hooks`, `pre_model_hook`, `step_callback`.

## Inbox

Synonym for **mailbox**. The local in-memory queue (held by the MCP server's listener task) into which messages accumulate between agent `recv` calls.

## Inject (action)

A `Decision` value meaning the runtime should add the decision's message text to the agent's next-turn context. Distinct from `block` (prevent action) and `noop` (do nothing).

## Listener

The asyncio background task running inside the SOX MCP server. Maintains a long-lived connection to the backing store and pulls messages as they arrive, buffering them in memory so the agent's `channels__recv` tool calls return immediately. The listener is what gives SOX network-layer push-receive semantics despite MCP being client-pull.

## Mailbox

The in-memory queue maintained by the MCP server's listener for an agent. Synonym for inbox. Distinct from the backing store's persistent message log: the mailbox is a local cache; the backing store is the source of truth.

## MCP (Model Context Protocol)

Anthropic-originated, industry-standard protocol for exposing tools to LLM agents. SOX's tool surface (Layer 2 in [DESIGN §4.1](./DESIGN.md#41-layer-diagram)) is implemented as an MCP server. SOX is not a replacement for or competitor to MCP; it builds on it.

## Message

A unit of communication in SOX. Wire envelope fields: `channel`, `sender`, `body` (opaque JSON object), `sent_at` (timestamp), `message_id` (unique), `seq` (per-channel monotone counter, authoritative ordering key), plus optional `correlation_id`, `ts` (advisory nanosecond timestamp), `reply_to` (thread parent), `delivered_to` (delivery tracking for deadlock detection), `origin_server` (null in v1.0, reserved for federation), `_meta` (observability metadata). Normative definition: `spec/schemas/message.schema.json` and `spec/protocol.md §Message envelope shape`.

## Non-blocking

Operations (send, recv) that return immediately rather than waiting for an event. SOX's send and recv are both non-blocking by definition: send returns when the message is durably accepted; recv returns immediately with whatever has accumulated, even if that is zero messages.

## Peer

Another SOX agent on the same backing store. Peers can address each other by `agent:<id>` or interact via shared group channels. SOX has no hierarchy: all agents are peers.

## Policy

The operator-configurable parameters governing the cadence enforcer (thresholds for reminders, whether to force drain on stop, default reminder texts). Defined in [CONTRACTS §4](./CONTRACTS.md#4-policy-schema).

## Progressive disclosure

The pattern of loading the full discipline document only when the agent recognises a relevant situation, rather than embedding it always-on in the system prompt. Achieved by Claude Code's skill-loading mechanism (skill is loaded when its `description` matches what the agent is doing). Cheaper in token cost than always-on.

## Pull

Receive semantics where the consumer asks for messages, and gets only what has accumulated (possibly zero). SOX is pull-only at the LLM layer (the agent calls `channels__recv`) and push-receive at the network layer (the MCP server's listener subscribes to the backing store).

## Push

The opposite of pull: the producer (or broker) delivers messages to the consumer without being asked. SOX uses push at the network layer (backing store → MCP listener) but not at the LLM layer (no preempting in-flight LLM turns in v0).

## Reconciliation

The process by which an agent integrates a late-arriving reply into its in-progress reasoning. Two cases:

- **Confirmation:** the reply matches the agent's best-guess; reconciliation is annotating the working notes "assumption confirmed."
- **Contradiction:** the reply contradicts the best-guess; reconciliation requires revising the assumption and (potentially) rolling back work.

SOX provides a recipe in the discipline; the *machinery* of reconciliation (rollback, merge) is agent-task-specific and outside the protocol's scope. See [DESIGN §7.1](./DESIGN.md#71-reconciliation-when-the-agent-has-committed-to-a-path).

## Recv

The non-blocking drain operation. Returns all messages accumulated in the mailbox since the last drain.

## Send

The non-blocking publish operation. Returns when the message is durably accepted by the backing store.

## Skill (in Claude Code)

A markdown file with frontmatter that Claude Code can load on-demand based on a `description` match. SOX's discipline is rendered into a Claude Code skill named `inter-agent-channels` by the Claude Code adapter. The skill format is Claude Code-specific; the *content* (the discipline markdown) is runtime-agnostic.

## Speculative-then-reconcile

The signature pattern SOX is built to support: the agent posts a clarification request, continues working under a recorded best-guess assumption, and integrates the late-arriving reply non-destructively. This pattern is documented in the discipline as a recipe; broader pattern catalogue is deferred to [FUTURE §3](./FUTURE.md#3-speculative-execute-and-reconcile-pattern-library).

## Speculative execution

Borrowed from CPU microarchitecture: predict, execute, correct on misprediction. In SOX, a synonym for the "act under best-guess interpretation while awaiting clarification" half of the speculative-then-reconcile pattern.

## State

Per-agent persistent counters and timestamps maintained by the cadence enforcer. Schema in [CONTRACTS §3.2](./CONTRACTS.md#32-state). Persisted in SQLite, transactionally read-modify-written per `decide()` call.

## Subagent

In Claude Code: a task-spawned child Claude process. SOX agents on the Claude Code adapter are typically subagents, but the protocol works for any agent runtime where the agent has a stable identity and a process to host an MCP client.

## Subscription

An agent's expressed interest in messages from a channel pattern. Persisted in the backing store. An agent receives messages only from channels matching its subscriptions (plus implicit subscriptions to its direct mailbox `agent:<id>`).

## Topic

In some prior literature (AutoGen, NATS, Kafka), "topic" is the named subscription target. SOX uses **channel** as the equivalent term throughout, for consistency.

## Turn

One LLM completion (potentially containing multiple tool calls). Used in cadence enforcer thresholds (`reminder_threshold_turns`).

## Turn-taking

The synchronous-scheduler shape used by CrewAI, LangGraph, and OpenAI Swarm: one agent acts while others wait. SOX is explicitly not turn-taking; agents run concurrently.
