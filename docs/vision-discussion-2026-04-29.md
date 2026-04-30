# SOX Protocol — vision discussion (2026-04-29)

Captured conversation between maintainer and Claude on direction for the project.

---

## TODO assessment (input)

The maintainer asked for an assessment of `TODO.md`. Summary of feedback given:

### What's working
- **Top priority is correctly identified.** Agent identity verification at #1 is right — everything below it (ACLs, audit logs, namespacing, rate limits) is structurally meaningless if `SOX_AGENT_ID` is a self-asserted env var.
- **Layering instinct is sound.** The recurring "backing store vs. middleware vs. tool-level" question shows up in auth, rate limiting, schema validation, namespacing, tracing. A hooks/middleware layer is the unlock for half the backlog.
- **Spec-first discipline.** Transport adapter, backing store port, federation model, version negotiation framed as port/spec problems rather than implementation problems.
- **Observability has teeth.** Static token floor + runtime envelope annotation + synthetic benchmark is unusually rigorous.

### Concerns flagged
1. **Identity vs. middleware ordering is chicken-and-egg.** Resolve credential primitive (shared secret vs. keypair vs. JWT) before investing in middleware framework — otherwise the middleware port is designed around the wrong identity contract.
2. **Threading + DMs + groups overlap heavily.** Three half-coherent abstractions risk. Worth a unifying "addressable destinations" design pass.
3. **`list_pending` is doing a lot.** It's the central data structure of the enforcer story — deserves its own design doc, not a scatter across 6 sections.
4. **Federation/v1 scope is unanswered and dangerous.** Affects identity, namespacing, ordering (`seq` global vs. per-channel), replay. Decide in/out of v1 before locking the spec.
5. **Self-send exclusion** is currently a correctness bug, not a feature — should be next-up, not mid-list.
6. **No cost/effort signal.** ~230 items at flat priority is unsustainable. Group by milestone (v0.2, v1, post-v1).

### Recommended sequencing
1. Resolve identity primitive Q → ship per-agent credential registry.
2. Self-send exclusion + `since` parameter (correctness wins, unblock demo).
3. Pick hooks vs. middleware — implement auth as the first plugin to validate the abstraction.
4. Federation in/out decision before any schema work that would need retrofitting.
5. Reference agent + bootstrap helper before SDK polish.
6. Defer chat UI and CLI until protocol surface is stable.

---

## Maintainer's vision (input)

> I want it to be a tool that other people will use and install
> I want to publish something about it
> I want to insulate the core idea as much as possible from 3rd party technologies, this is why I brought up the transport adapter and am trying to model auth as a consumer decision with the middleware and or hook adapter interface.
> I want the core feature to shine - agents talk to each other in real time, you can talk to groups of agents etc I have never heard of that before
> I want the package to be thoroughly tested & the documentation to be exciting

---

## Reflected vision

**Product positioning:** SOX is a *protocol* (not a framework, not a service) for real-time multi-agent communication. The novel claim is **live agent-to-agent and agent-to-group messaging** — not request/response orchestration, not a queue, not RAG. Agents talk like people in a chat room, and groups are first-class.

**Architectural posture:** The core is *technology-agnostic by design*. Transport, auth, storage, identity — all pluggable via ports. Consumers bring their own opinions. The spec is the product; the Python implementation is the reference.

**Quality bar:** Thoroughly tested (you want users, so trust matters). Exciting docs (you want adoption, so the first 5 minutes have to land).

---

## Sharpening questions and pushback

### 1. "Insulate from 3rd party tech" needs a line

MCP is currently in the core — every agent is assumed to be an MCP client. That's a 3rd-party technology. Is MCP part of the core protocol, or is it one transport binding among several (raw stdio, HTTP, WebSocket, gRPC)?

For true insulation: the core spec describes message envelopes and channel semantics, and MCP is *an adapter*. Bigger refactor than the current transport adapter TODO suggests, but the honest version of the stated goal.

### 2. The novel claim needs a sharper articulation

"Agents talk to each other in real time" is true but undersells it. What's actually new:

- **vs. LangGraph / CrewAI / AutoGen:** those orchestrate agents in a DAG or supervisor pattern. SOX is *peer-to-peer with no orchestrator.* Agents subscribe to channels and react.
- **vs. message queues (Redis pub/sub, NATS):** those are dumb pipes. SOX has *agent-aware semantics* — pending state, ACK/NACK, threading, the enforcer stop-block. The protocol knows what an agent is.
- **vs. MCP:** MCP is tool-calling (agent → tool). SOX is agent-to-agent. Orthogonal.

**Suggested pitch:** *"Group chat for agents. Channels, threads, presence, DMs — but the participants are LLMs, and the protocol enforces conversational discipline."*

The chat UI in TODO isn't a nice-to-have; it's the *demo that makes the idea click in 30 seconds.*

### 3. "Thoroughly tested" needs a structure, not just an aspiration

Three layers for a protocol project:

- **Spec conformance suite** — language-agnostic test fixtures (JSON in, JSON out) any implementation must pass. Without this, "Rust implementation" is a fork, not a port.
- **Reference implementation tests** — Python adapters (SQLite store, stdio transport) tested against the conformance suite + their own unit/integration tests.
- **End-to-end demo tests** — two-agent demo and reference agent run as integration tests in CI.

This is the work that makes "third parties can implement SOX" real and lets you confidently say "v1.0 stable" later.

### 4. "Exciting documentation" — concrete patterns

- **60-second demo at top of README.** Animated terminal recording of two agents having a conversation, or screenshot of chat UI. No prose above it.
- **"Why SOX?" page that names competitors directly.** Adoption requires answering "why not LangGraph?" in one screen.
- **Worked example as the second page.** Not "here's the API" — "here's two agents collaborating on a task, end-to-end, 40 lines."
- **Spec doc separate from implementation doc.** Reinforces "protocol, not framework" posture.
- **Public roadmap.** Curated public version of TODO.md signals momentum.

### 5. The middleware/hooks decision now blocks marketing, not just code

Publishing before deciding ships a v0 that doesn't yet show the extensibility story — which is half the pitch. Resolve that architect-Q before launch.

---

## Implied launch critical path

If the goal is *publishable, adoptable, novel-feeling*:

1. **Identity primitive decided** (blocks everything else)
2. **Hooks vs. middleware decided + one auth plugin shipped** (proves extensibility)
3. **Spec separated from implementation** in repo structure (`spec/` is the product, `packages/python` is one impl)
4. **Conformance test suite scaffolded** (even with 5 tests, the *structure* signals seriousness)
5. **Reference agent + bootstrap helper** (this is what users copy-paste)
6. **Chat UI MVP** — the demo that sells the idea. TUI is enough for v1; web app post-launch.
7. **README + "Why SOX" + worked example** written by someone who can write
8. **Launch** — HN, Anthropic Discord, Claude Code community first

**The chat UI matters more than the TODO ranking suggests.** A 30-second video of agents talking in a TUI is the entire pitch. Without it readers have to imagine the magic.

---

## Open questions back to maintainer

- Is MCP a transport binding or part of the core? (Determines size of spec/implementation split.)
- Honest target audience for v1 — Claude Code skill authors, or any LLM developer? (Affects whether SDKs ship at launch or post-launch.)
- Personal project with a brand, or neutral protocol to hand to a foundation later? (Affects naming, governance language, license choice.)
- Timeline — weeks or months to publish?
