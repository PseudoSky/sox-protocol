# SOX Protocol — Research bibliography

Annotated bibliography of every source consulted while designing SOX Protocol v0. Organised by topic. Each entry notes how it influenced the design.

---

## 1. Closest mainstream multi-agent runtime: AutoGen 0.4+

Microsoft's AutoGen rewrote onto an actor-model foundation in version 0.4, providing async messaging, topic-based pub/sub, and a gRPC-based distributed runtime. SOX's MCP-server architecture and the design of Layer 2 (the asyncio listener buffering messages locally) is most directly informed by AutoGen's actor/mailbox shape — translated through MCP rather than gRPC.

- [AutoGen 0.4 announcement (Microsoft Research)](https://www.microsoft.com/en-us/research/articles/autogen-v0-4-reimagining-the-foundation-of-agentic-ai-for-scale-extensibility-and-robustness/) — the rationale for moving to actor model from the original v0.2 turn-taking design.
- [AutoGen Topic and Subscription](https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/core-concepts/topic-and-subscription.html) — pub/sub primitives.
- [AutoGen Concurrent Agents design pattern](https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/design-patterns/concurrent-agents.html) — explicit concurrency primitives.
- [AutoGen Distributed Agent Runtime](https://microsoft.github.io/autogen/dev/user-guide/core-user-guide/framework/distributed-agent-runtime.html) — gRPC host servicer + workers; protobuf cross-language.
- [AutoGen architecture (core concepts)](https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/core-concepts/architecture.html) — core/AgentChat layer split.
- [Topic and Subscription example scenarios](https://microsoft.github.io/autogen/dev/user-guide/core-user-guide/cookbook/topic-subscription-scenarios.html) — practical usage patterns.

**How it informed SOX:** the topic + subscription model is directly analogous to SOX channels. SOX's cadence enforcer fills the gap that AutoGen leaves to the developer (when to drain mailbox, how to reconcile late replies).

---

## 2. Closest academic match: MetaGPT shared message pool

MetaGPT's shared-message-pool + role-subscription pattern is the published prior art closest to SOX's group-channels-with-deferred-receive shape. Key contribution: the explicit "act once prerequisites have landed" semantics — a half-step short of speculative-then-reconcile.

- [MetaGPT: Meta Programming for a Multi-Agent Collaborative Framework (arXiv)](https://arxiv.org/html/2308.00352v6) — Hong et al., 2023.
- [MetaGPT agent communication docs](https://docs.deepwisdom.ai/main/en/guide/in_depth_guides/agent_communication.html) — the shared message pool described in implementation terms.
- [MetaGPT GitHub docs source](https://github.com/geekan/MetaGPT-docs/blob/main/src/en/guide/in_depth_guides/agent_communication.md)
- [What is MetaGPT? (IBM Think)](https://www.ibm.com/think/topics/metagpt) — vendor-neutral overview.
- [MetaGPT in Action: Multi-Agent Collaboration](https://bizthots.wordpress.com/metagpt-in-action-multi-agent-collaboration/)
- [MetaGPT Multi Agent Framework Explained 2026](https://aiinovationhub.com/metagpt-multi-agent-framework-explained/)
- [MetaGPT alphaXiv overview](https://www.alphaxiv.org/overview/2308.00352)
- [MetaGPT-style Software Team Agents: Foundations, Architecture, Applications, and Performance Trends](https://atoms.dev/insights/metagpt-style-software-team-agents-foundations-architecture-applications-and-performance-trends/7e48a158cab643e4b8ea7157286a92f2)
- [Multi-agent PRD automation with MetaGPT, Ollama, and DeepSeek (IBM)](https://www.ibm.com/think/tutorials/multi-agent-prd-ai-automation-metagpt-ollama-deepseek)

**How it informed SOX:** the shared-pool architecture validates the "single backing store rather than peer connections" decision (DESIGN §5.2). MetaGPT's "wait for prerequisites" semantics is the boundary SOX deliberately steps past with the speculative-then-reconcile recipe.

---

## 3. Protocol-layer prior art

### 3.1 A2A (Agent2Agent Protocol)

Originated at Google, now maintained by the Linux Foundation. Defines an inter-agent task-handling protocol with sync, streaming, and async (push notification) modes. Task-scoped (client → remote agent) rather than peer-to-peer N:N.

- [A2A specification](https://a2a-protocol.org/latest/specification/)
- [A2A streaming and async operations](https://a2a-protocol.org/latest/topics/streaming-and-async/) — the push-notification webhook pattern.
- [A2A specification v0.2.5](https://a2a-protocol.org/v0.2.5/specification/)
- [A2A specification draft v1.0](https://a2a-protocol.org/dev/specification/)
- [A2A GitHub repo](https://github.com/a2aproject/A2A)
- [Announcing A2A (Google Developers Blog)](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)
- [What Is A2A? (IBM Think)](https://www.ibm.com/think/topics/agent2agent-protocol)
- [A2A 2026 Standard (Programming Helper Tech)](https://www.programming-helper.com/tech/agent-to-agent-protocol-2026-google-a2a-standard)
- [2025 Complete Guide: A2A Advanced](https://a2aprotocol.ai/blog/2025-part2-full-guide-a2a-protocol)

**How it informed SOX:** A2A demonstrates that async push-notification semantics is a recognised need in inter-agent protocols. SOX is complementary — A2A handles cross-trust-boundary task calls; SOX handles intra-trust-domain peer messaging. A future bridge is documented in [FUTURE.md §5](./FUTURE.md#5-cross-organisation-messaging-via-a2a-bridge).

### 3.2 MCP (Model Context Protocol)

Anthropic-originated, now industry-standard tool-exposure protocol. Wrong shape for peer messaging (client → server, request-response), but the integration surface SOX uses to expose its tools.

- [Claude Code MCP docs](https://code.claude.com/docs/en/mcp)
- [MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP discussion: long-lived sessions](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/102)
- [FastMCP × Claude Code integration](https://gofastmcp.com/integrations/claude-code) — recommended SDK for v0.
- [Install and Configure MCP Servers in Claude Code (systemprompt.io)](https://systemprompt.io/guides/claude-code-mcp-servers-extensions)
- [Claude Code MCP Servers: How to Connect (Builder.io)](https://www.builder.io/blog/claude-code-mcp-servers)
- [Claude Desktop App with HTTP-with-SSE-transport (MCP discussion)](https://github.com/orgs/modelcontextprotocol/discussions/16)
- [Open Claude Code MCP Client & Server Management (DeepWiki)](https://deepwiki.com/xtherk/open-claude-code/8.1-mcp-client-and-server-management)

**How it informed SOX:** MCP is the integration surface for Layer 2. The decision to put the asyncio listener inside the MCP server (rather than expecting agents to run their own) follows from MCP's client-initiated model.

### 3.3 ACP / ANP / interoperability survey

Comparative survey of inter-agent protocols. Covers MCP, ACP (IBM/BeeAI), A2A, and ANP.

- [A Survey of Agent Interoperability Protocols (arXiv 2505.02279)](https://arxiv.org/html/2505.02279v1)

**How it informed SOX:** confirmed that no surveyed protocol covers the SOX-specific shape (intra-domain peer N:N with non-blocking + deferred reconciliation).

### 3.4 AGNTCY messaging IETF draft

IETF draft on messaging substrates for agentic AI. Compares AMQP, MQTT, NATS, AMQP-over-WebSockets, Kafka, and the AGNTCY-coined SLIM transport across dimensions specific to GenAI agents.

- [draft-mpsb-agntcy-messaging-00 (IETF)](https://www.ietf.org/archive/id/draft-mpsb-agntcy-messaging-00.html)

**How it informed SOX:** SOX takes no position on which substrate is best. The backing-store interface (CONTRACTS §6) was designed so any of these can plug in. NATS chosen as the v0.1 priority based on the draft's analysis.

---

## 4. Substrates: actor model and messaging systems

### 4.1 Actor model foundations

- [LLMs as Actors for Agentic Apps (DZone)](https://dzone.com/articles/actor-model-agentic-llm-apps) — explicit equivalence: LLM = actor, prompt = message.
- [The Akka Actor Model: A Foundation for Concurrent AI Agents](https://pradeepl.com/blog/agentic-ai/akka-actor-model-agentic-ai/) — Akka principles applied to LLM agents.
- [Introduction to Actors (Akka core docs)](https://doc.akka.io/libraries/akka-core/current/typed/actors.html)
- [Understanding the Actor Design Pattern (DEV / Medium)](https://dev.to/micromax/understanding-the-actor-design-pattern-a-practical-guide-to-build-actor-systems-with-akka-in-java-p52)
- [Understanding the Actor Model (MentorCruise)](https://mentorcruise.com/blog/understanding-the-actor-model/)
- [5.4 Actor-based Concurrency (Berb diploma thesis)](https://berb.github.io/diploma-thesis/original/054_actors.html)
- [actor-model-blog Documentation (László Hegedüs)](https://app.readthedocs.org/projects/actor-model-blog/downloads/pdf/latest/)
- [Introduction to Actor Model (Ada Beat)](https://adabeat.com/fp/introduction-to-actor-model/)
- [Actor Model: Explained & Examples (StudySmarter)](https://www.studysmarter.co.uk/explanations/computer-science/computer-programming/actor-model/)

**How it informed SOX:** the mailbox semantics and bounded-queue shape come from the actor-model literature. Hewitt's 1973 model is the canonical reference. SOX's "agent has a mailbox at the MCP server" is an actor mailbox with an LLM-shaped consumer.

### 4.2 Messaging systems

- [NATS.io homepage](https://nats.io/) — high-performance pub/sub.
- [Subject-Based Messaging (NATS docs)](https://docs.nats.io/nats-concepts/subjects) — subject hierarchy maps onto SOX channel naming.
- [Large Language Model Based Multi-Agent System Augmented Complex Event Processing Pipeline for IoMT (arXiv)](https://arxiv.org/html/2501.00906v1) — research-grade integration of AutoGen + Kafka.

**How it informed SOX:** NATS subjects directly inspired the SOX channel naming convention (`ticket:ENGI-0042`, glob `ticket:*`). NATS prioritised as the v0.1 backing-store target.

---

## 5. Library-shaped frameworks (informative comparisons)

### 5.1 Langroid

- [Langroid GitHub](https://github.com/langroid/langroid) — actor-inspired Python framework, hierarchical task delegation.
- [Langroid architecture overview (blog)](https://langroid.github.io/langroid/blog/2024/08/15/overview-of-langroids-multi-agent-architecture-prelim/)

**How it informed SOX:** Langroid demonstrates the "actor-inspired but task-tree, not peer N:N" pattern. SOX's design rejects the hierarchical-only constraint.

### 5.2 Letta (formerly MemGPT)

- [Letta GitHub](https://github.com/letta-ai/letta)
- [Letta v1 agent blog](https://www.letta.com/blog/letta-v1-agent)
- [Letta AI agents stack](https://www.letta.com/blog/ai-agents-stack)
- [Letta MemGPT concepts](https://docs.letta.com/concepts/memgpt/)
- [Letta OpenAI-compatible providers](https://docs.letta.com/guides/server/providers/openai-proxy/)
- [Letta voice overview](https://docs.letta.com/guides/voice/overview/)

**How it informed SOX:** Letta's "DB-row-as-agent + worker-loads-on-request" model is orthogonal to SOX (SOX is about messaging, not agent statefulness) but important context for how stateful-agent platforms address persistence.

### 5.3 Other frameworks surveyed

- [OpenAI Agents SDK (docs)](https://openai.github.io/openai-agents-python/)
- [OpenAI Agents SDK lifecycle hooks](https://openai.github.io/openai-agents-python/agents/#lifecycle-events-hooks) — basis for v0.1 OpenAI SDK adapter.
- [OpenAI Agents SDK running agents](https://openai.github.io/openai-agents-python/running_agents/)
- [OpenAI Responses API agents guide](https://developers.openai.com/api/docs/guides/agents)
- [LangGraph agent server docs](https://docs.langchain.com/langsmith/agent-server)
- [LangGraph DeepWiki](https://deepwiki.com/langchain-ai/langgraph/8-langgraph-platform)
- [langgraph-api PyPI](https://pypi.org/project/langgraph-api/)
- [LangGraph homepage](https://www.langchain.com/langgraph)
- [LangGraph create-react-agent how-to](https://langchain-ai.github.io/langgraph/how-tos/create-react-agent-hitl/) — pre/post-model hooks, basis for v0.1 LangGraph adapter.
- [CrewAI hierarchical process](https://docs.crewai.com/en/learn/hierarchical-process)
- [CrewAI Flows](https://docs.crewai.com/en/concepts/flows)
- [Why CrewAI's Manager-Worker Architecture Fails (Towards Data Science)](https://towardsdatascience.com/why-crewais-manager-worker-architecture-fails-and-how-to-fix-it/)
- [Delegation ping-pong: breaking infinite handoff loops in CrewAI (azguards)](https://azguards.com/technical/the-delegation-ping-pong-breaking-infinite-handoff-loops-in-crewai-hierarchical-topologies/)
- [Mastra workflows suspend and resume](https://mastra.ai/docs/workflows/suspend-and-resume)
- [Mastra workflow snapshots reference](https://mastra.ai/en/reference/workflows/snapshots)
- [Pydantic AI homepage](https://ai.pydantic.dev/)
- [Agno GitHub](https://github.com/agno-agi/agno)
- [Agno homepage](https://www.agno.com/)
- [Google ADK docs](https://google.github.io/adk-docs)
- [What is Google's Agent Development Kit? (The New Stack)](https://thenewstack.io/what-is-googles-agent-development-kit-an-architectural-tour/)
- [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Microsoft Agent Framework GitHub](https://github.com/microsoft/agent-framework)
- [SmythOS Agent Runtime architecture](https://smythos.com/docs/agent-runtime/architecture/)

**How it informed SOX:** the survey of these frameworks established that turn-taking and handoff topology are universal in mainstream tooling, leaving the peer-non-blocking-with-reconciliation niche uncovered.

---

## 6. Durable execution engines (informative)

- [Inngest AgentKit GitHub](https://github.com/inngest/agent-kit)
- [Inngest AgentKit Networks](https://agentkit.inngest.com/concepts/networks)
- [Inngest useAgent realtime hook](https://www.inngest.com/blog/agentkit-useagent-realtime-hook)
- [Restack enterprise](https://www.restack.io/enterprise)
- [Build Resilient Agentic AI with Temporal](https://temporal.io/blog/build-resilient-agentic-ai-with-temporal)
- [Of Course You Can Build Dynamic AI Agents with Temporal](https://temporal.io/blog/of-course-you-can-build-dynamic-ai-agents-with-temporal)
- [Durable Workflow Platforms for AI Agents and LLM Workloads (Render)](https://render.com/articles/durable-workflow-platforms-ai-agents-llm-workloads)

**How it informed SOX:** durable execution engines (Temporal, Inngest, Restack) are orthogonal to SOX. SOX is messaging; they are workflow execution. The two compose: a Temporal workflow can use SOX channels to coordinate with peers without losing Temporal's replay properties.

---

## 7. Claude Code internals (load-bearing for adapter design)

- [Claude Code MCP docs (official)](https://code.claude.com/docs/en/mcp)
- [Claude Code hooks (official)](https://docs.claude.com/en/docs/claude-code/hooks) — hook events, JSON injection protocol.
- [Understanding Claude Code's Full Stack: MCP, Skills, Subagents, and Hooks (alexop.dev)](https://alexop.dev/posts/understanding-claude-code-full-stack/)
- [Enhancing Claude Code with MCP Servers and Subagents (DEV)](https://dev.to/oikon/enhancing-claude-code-with-mcp-servers-and-subagents-29dd)
- [task-master issue #1643: stdio MCP per-process memory](https://github.com/eyaltoledano/claude-task-master/issues/1643) — confirmed stdio MCP is one-process-per-client; load-bearing for the SOX architecture decision in DESIGN §5.1.
- [Claude Code Agent Monitor (project wiki)](https://hoangsonww.github.io/Claude-Code-Agent-Monitor/)

**How it informed SOX:** the stdio-MCP-is-per-process behaviour is *the* reason SOX requires a shared backing store rather than expecting MCP servers to share in-memory state. The hooks documentation defines what the Claude Code adapter's EnforcerBinding can and cannot do.

---

## 8. Adjacent domains (referenced in DESIGN/FUTURE)

### 8.1 Speculative execution and reconciliation

- Hennessy & Patterson, *Computer Architecture: A Quantitative Approach* — speculative execution / branch prediction primary reference.
- Shapiro, Preguiça, Baquero, Zawirski, "Conflict-Free Replicated Data Types" (Inria 2011) — CRDT theory.
- Ellis & Gibbs, "Concurrency control in groupware systems" (SIGMOD 1989) — Operational Transformation.

**How it informed SOX:** these are the analogues for the speculative-then-reconcile pattern. SOX's discipline document recipe is informed by the conceptual moves in these areas (predict-then-correct; merge-late-write; transform-then-replay).

### 8.2 Lamport / vector / hybrid clocks (referenced in FUTURE §2.2)

- Lamport, "Time, Clocks, and the Ordering of Events in a Distributed System" (CACM 1978).
- Kulkarni, Demirbas, Madappa, Avva, Leone, "Logical Physical Clocks" (HLC, OPODIS 2014).

---

## 9. Multi-agent collaboration / general framework analysis

- [WMAC 2026 (AAAI 2026 Bridge Program on Advancing LLM-Based Multi-Agent Collaboration)](https://multiagents.org/2026/) — academic workshop scope.
- [Top 8 LLM Frameworks for Building AI Agents in 2026 (Second Talent)](https://www.secondtalent.com/resources/top-llm-frameworks-for-building-ai-agents/)
- [AI agent frameworks that actually work for cross-functional teams in 2026 (monday.com)](https://monday.com/blog/ai-agents/ai-agent-frameworks/)
- [Top 7 LLM Frameworks 2026 (Redwerk)](https://redwerk.com/blog/top-llm-frameworks/)
- [awesome-ai-agents-2026](https://github.com/caramaschiHG/awesome-ai-agents-2026) — landscape index.
- [VoltAgent awesome AI agent papers 2026](https://github.com/VoltAgent/awesome-ai-agent-papers)

---

## 10. Prior workflow-memory research artefacts (this project's memory store)

The 2026-04-28 focused survey that scoped this work, plus the broader 2026-04-24 landscape survey, are persisted in this project's `~/.claude/plugins/workflow/memory/research/` and informed every section of DESIGN.md.

- [2026-04-28 async peer channels and mailboxes (focused survey)](../../../../../../.claude/plugins/workflow/memory/research/agent-runtime-platforms/2026-04-28-async-peer-channels-and-mailboxes.md)
- [2026-04-24 stateful agent-runtime platforms landscape survey](../../../../../../.claude/plugins/workflow/memory/research/agent-runtime-platforms/2026-04-24-landscape-survey.md)
- [2026-04-24 chat-completions agent addressability](../../../../../../.claude/plugins/workflow/memory/research/agent-runtime-platforms/2026-04-24-chat-completions-agent-addressability.md)
- [2026-04-24 Anthropic-compat peer surface and namespace encoding](../../../../../../.claude/plugins/workflow/memory/research/agent-runtime-platforms/2026-04-24-anthropic-compat-and-namespace-encoding.md)
- [2026-04-27 agent-spec portability matrix](../../../../../../.claude/plugins/workflow/memory/research/agent-runtime-platforms/2026-04-27-agent-spec-portability-matrix.md)

---

## 11. Methodology note

This bibliography combines:

- 5 consolidated WebSearch queries (one per topic group: actor-model frameworks, AutoGen-specific, pub/sub substrates, A2A/protocols, MetaGPT/academic).
- 1 targeted WebSearch + 1 WebFetch on Claude Code MCP lifecycle (stdio vs HTTP shared-state, load-bearing for §5.1 of DESIGN).
- 5 prior in-project research findings persisted to global memory (`agent-runtime-platforms/`).

No invocation read the SOX project's source code; the design is inferred from public framework documentation, the user's stated requirements, and the prior memory store. This is consistent with the workflow-researcher anti-skew constraint.

The trimmed-pass methodology (5 queries per direction rather than tier-by-tier exhaustive search) was chosen for token economy. Where deeper investigation would benefit the design, [DESIGN.md §7](./DESIGN.md#7-open-problems) and [FUTURE.md](./FUTURE.md) explicitly flag it as unresolved or deferred.
