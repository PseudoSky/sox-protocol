# SOX Protocol v0.0.1 — Speculative-execute-while-awaiting as a first-class pattern

Today we're launching SOX Protocol: a runtime-agnostic channel layer for multi-agent LLM systems. SOX is not a framework and not a messaging library. It's a published, language-neutral specification plus a production-ready Python reference implementation that packages a specific discipline — how to work on ambiguous context, post clarifications to peers without blocking, and integrate late-arriving answers non-destructively.

The protocol fills a structural gap in the multi-agent LLM landscape: *no surveyed framework markets a documented pattern for speculative-execute-while-awaiting-clarification.*

---

## The gap

Consider a multi-agent system where agent A is working on a task and encounters an ambiguity that, left unresolved, will cause a blocker at step 20. A should be able to post a clarification request to a group channel, continue working under a best-guess interpretation, and when B answers at step 4, reconcile that answer into A's in-progress reasoning — either confirming the guess (no rework) or revising it (targeted rework). The block at step 20 never happens.

This is not turn-taking (CrewAI, LangGraph, OpenAI Swarm). In those frameworks, one agent acts while others idle. When A asks B for clarification, B is waiting; when B replies, A waits.

This is not handoff control (OpenAI Agents SDK, CrewAI hierarchical delegation). Control doesn't transfer. A keeps the cognitive thread; B is a peer providing context.

This is not actor primitives (AutoGen 0.4+, MetaGPT). Those frameworks provide mailboxes and pub/sub. The technical building blocks exist. But they ship no packaged *discipline* — when to send without blocking, how to reconcile late answers, how to avoid send-and-wait anti-patterns. Integrators wire the discipline themselves.

Protocol-layer prior art (A2A, MCP, AGNTCY) either targets a different topology (task-scoped client→agent rather than peer N:N) or analyzes substrates without prescribing a discipline.

The result: speculative-execute-while-awaiting is a known-good pattern in single-agent prompt engineering (work under uncertainty, flag assumptions, integrate context), but multi-agent systems have no standard way to do it across independent agent processes.

---

## The thesis

Multi-agent LLM systems need a *peer-to-peer channel layer* with three properties:

1. **Non-blocking sends.** `send()` returns immediately; the sender does not wait for a receiver to read.
2. **Deferred, polled receives.** Each agent maintains a local mailbox; it drains the mailbox at chosen points between reasoning steps.
3. **A documented pattern for reconciliation.** When late context arrives, agents integrate it without stalling earlier — the recipe is part of the protocol, not left to integrators.

That's SOX: speculative execution with a discipline-enforced cadence that prevents the worst anti-patterns (send and wait, forgetting to drain, exiting with a full inbox).

The portable core is small:

- A **markdown discipline document** — opinionated guidance on when to send, when to drain, when *not* to use channels, worked examples of the reconciliation recipe.
- A **pure-function cadence enforcer** — decides when to inject reminders or block actions based on operator-tunable policy.
- An **MCP server** — exposes non-blocking send/recv tools, maintains a persistent connection to a backing store.
- A **pluggable backing store** — SQLite (default), filesystem, NATS, Redis. Agents don't need to know each other's addresses; they just read from and write to a shared store.

The runtime-specific bits (Claude Code skills, OpenAI Agents SDK hooks, LangGraph nodes) are isolated to thin adapters living in language-specific packages. The discipline and enforcer are reusable across all runtimes.

---

## The shape

**v0.0.1 ships:**

- **Protocol spec (v1.0)** — frozen. JSON Schemas for wire definitions, formal port contracts (BackingStore, DisciplineRenderer, EnforcerBinding), 7-scenario conformance harness.
- **Python reference implementation** — complete. SQLite, filesystem, and in-memory backing stores. Claude Code runtime adapter. Conformance suite passing. Production-ready.
- **Placeholder TypeScript and Rust ports** — conformance bar documented; architecture suggested; contribution process clear.
- **Comprehensive documentation** — design rationale, usage guide, contracts, FUTURE roadmap, 40+ source bibliography, glossary.
- **Two end-to-end examples** — two-agent clarification (A posts a question, B answers, A reconciles) and group broadcast (A announces status to all on a channel).

The Python package is on PyPI:

```bash
pip install sox-protocol
python -m sox_protocol.adapters.runtimes.claude_code install
```

This installs the MCP server, registers it with Claude Code, creates a skill containing the full discipline, and initialises the SQLite backing store. A one-line bootstrap pointer in agent prompts makes the skill discoverable.

---

## Why this matters

**For single-project teams:** Spinning up N concurrent Claude Code subagents now has a standard way to handle inter-agent questions. No more ad-hoc email-like prompting or sequential handoffs.

**For frameworks:** AutoGen, MetaGPT, Langroid, and future frameworks can adopt SOX adapters. The discipline and enforcer become reusable assets rather than bespoke per-framework integrations.

**For the research community:** The protocol is published, so researchers can benchmark discipline effectiveness (e.g., comparing the default reconciliation recipe against alternatives) on standard scenarios. The conformance harness is Docker-based and language-agnostic, so new ports don't require changes to the spec or test suite.

**For operators:** Backing stores are pluggable. The default SQLite is zero-ops for single-machine projects. Swapping in NATS (v0.1) or Redis (v0.1) is a configuration change, not a code change.

---

## Prior art and positioning

The specification was informed by 40+ sources:

- **Actor-model foundations** (Hewitt, Erlang, Akka, Ray, AutoGen) validated the mailbox shape and concurrent-execution model.
- **Multi-agent frameworks** (MetaGPT, Langroid, Letta) showed the gap: primitives exist, discipline doesn't.
- **Protocol-layer work** (A2A, MCP, AGNTCY) positioned SOX as complementary — A2A handles cross-trust-boundary task calls; SOX handles intra-trust-domain peer messaging.
- **Messaging systems** (NATS, Kafka, MQTT) informed the backing-store interface so SOX can run on any durable queue.

The discipline document draws on:

- **Speculative execution** in CPU branch prediction and optimistic concurrency control (CRDTs, operational transform).
- **Prompt engineering** patterns (work under uncertainty, flag assumptions, integrate context).
- **Software engineering** (separation of concerns, composition).

See [docs/RESEARCH.md](../RESEARCH.md) for the full bibliography.

---

## Known limitations (deliberate non-goals for v0)

1. **No push-based interrupts.** Messages are pull-only. The enforcer can inject reminders, but the agent decides when to drain. This preserves agent autonomy and avoids preemption complexity.
2. **No authoritative ordering or causal consistency.** Best-effort per-channel ordering. If A and B send simultaneously on the same channel, order is undefined (backing-store dependent).
3. **No authentication or authorization.** This is an intra-trust-domain protocol. Agents share a backing store; that's the trust boundary.
4. **No observability tooling.** Planned for v0.1+.
5. **Only one runtime adapter in v0 (Claude Code).** OpenAI Agents SDK and LangGraph adapters are v0.1 priorities.
6. **Only three backing stores in v0.** NATS and Redis are v0.1.
7. **No pattern library for reconciliation.** v0 documents one recipe. v0.2+ will surface additional strategies for different agent types and task domains.

These are explicit deferral decisions, not oversights. See [docs/FUTURE.md](../FUTURE.md) for the rationale and roadmap.

---

## Testing and conformance

The Python implementation passes all seven conformance scenarios:

1. Send and receive a single message.
2. Multiple agents subscribe to one channel.
3. Agent A sends a question, continues, integrates a late answer.
4. Enforcer injects a reminder after N tool calls without a recv.
5. Enforcer blocks agent exit if the inbox is non-empty.
6. Filesystem-backed messages survive session restart.
7. Subscription with glob patterns (e.g., `ticket:ENGI-*`).

The conformance suite is language-agnostic and Docker-based. Any new port (TypeScript, Rust, Go, etc.) must pass the same seven scenarios before merge.

---

## Next steps

1. **Install and try it locally** — [docs/USAGE.md](../USAGE.md) has a 10-minute quickstart.
2. **Read the design rationale** — [docs/DESIGN.md](../DESIGN.md) covers the problem, architecture, and trade-offs.
3. **Contribute a language port** — TypeScript and Rust are explicitly open. See [packages/typescript/README.md](../../packages/typescript/README.md) and [packages/rust/README.md](../../packages/rust/README.md) for getting started.
4. **Write a custom backing store or runtime adapter** — The port contracts are prose-only and language-agnostic. Mirror `packages/python/` in your language.

---

## Community

Questions? Open an issue. Want to contribute? Read [CONTRIBUTING.md](../../CONTRIBUTING.md).

The protocol is published under the MIT license. The reference implementation is production-ready. We're excited to see what you build with it.

---

## Changelog

See [CHANGELOG.md](../../CHANGELOG.md) for v0.0.1 details.
