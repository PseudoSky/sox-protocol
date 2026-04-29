# SOX Protocol — runtime-agnostic peer messaging for LLM agents

**Version:** v0 (pre-implementation design)
**Status:** Idea / specification. No reference implementation yet.
**License:** TBD

## Repo shape (when published)

The SOX project is a monorepo. The protocol itself is language-neutral; reference implementations live in language-specific packages.

```text
sox-protocol/
├── docs/                   # the design documents in this folder
├── spec/                   # canonical, language-neutral protocol artefacts
│   ├── schemas/            # JSON Schema for Event, Decision, Policy, State, Message, MCP tools
│   ├── discipline/         # markdown discipline + worked examples
│   ├── ports/              # port behaviour contracts (BackingStore, DisciplineRenderer, EnforcerBinding)
│   └── conformance/        # language-neutral test harness (Docker + JSON scenarios)
└── packages/
    ├── python/             # v0 reference implementation
    ├── typescript/         # placeholder; open to contributions
    └── rust/               # placeholder; open to contributions
```

The spec in `spec/` is the protocol. Implementations consume from it. Other-language packages (`packages/typescript/`, `packages/rust/`) are placeholder directories at v0; the conformance bar for any language port is *passing `spec/conformance/scenarios/` against the implementation's MCP server*. See [FUTURE.md §0](./FUTURE.md) for contribution guidance.

## What this is

A runtime-agnostic channel layer for multi-agent LLM systems. It lets independently-running agents:

- post messages to other agents or to named group rooms,
- continue working without blocking on a reply,
- drain late-arriving replies from a local mailbox between LLM steps,
- reconcile late answers into in-progress reasoning via a documented pattern.

The runtime-specific bits (Claude Code skills, Claude Code hooks, OpenAI Agents SDK lifecycle callbacks, LangGraph nodes, etc.) are isolated to thin adapter layers. The portable core is four pieces:

1. A **markdown discipline document** with stable section anchors that any runtime can render into its prompt-construction surface.
2. A **pure-function cadence enforcer** that decides when to inject reminders or block actions.
3. An **MCP server** that holds a persistent connection to a backing store and surfaces non-blocking `send` / `recv` tools.
4. A **backing store** (SQLite, filesystem, NATS, Redis — pluggable) that holds messages between sender and receiver.

## The gap this fills

Surveyed multi-agent LLM frameworks (see [RESEARCH.md](./RESEARCH.md)) fall into one of three camps:

- **Turn-taking schedulers** (CrewAI, LangGraph, OpenAI Swarm) — one agent speaks while others wait. Cannot model "A keeps working while waiting for B."
- **Handoff frameworks** (OpenAI Agents SDK handoffs, CrewAI hierarchical) — control transfers; sender stops. Cannot model concurrent peer execution.
- **Actor-model frameworks** (AutoGen 0.4+, MetaGPT) — primitives exist but the *discipline* of using them well (when to send, how to reconcile late answers, how to avoid send-and-wait anti-patterns) is not packaged.

No surveyed framework markets a documented pattern for *speculative-execute-while-awaiting-clarification* — i.e., an agent works on a best-guess interpretation, sends a clarification request, continues, and integrates a late answer non-destructively when it arrives. This is the structural gap SOX Protocol fills.

## Documents in this folder

| File | Purpose |
|---|---|
| [DESIGN.md](./DESIGN.md) | Problem statement, related-work survey, full architecture, design decisions and trade-offs, non-goals |
| [IMPLEMENTATION-PLAN.md](./IMPLEMENTATION-PLAN.md) | Milestone-ordered v0 build plan, repo layout, tech-stack choices, testing strategy |
| [USAGE.md](./USAGE.md) | How to integrate SOX into a Claude Code project, configuration reference, use cases, anti-patterns |
| [CONTRACTS.md](./CONTRACTS.md) | Formal interface specs: discipline section anchors, enforcer Event/Decision schemas, MCP tool surface, backing-store interface, adapter conformance checklist |
| [FUTURE.md](./FUTURE.md) | Explicitly deferred features and the rationale for each deferral |
| [RESEARCH.md](./RESEARCH.md) | Annotated bibliography of every source consulted, organised by topic |
| [GLOSSARY.md](./GLOSSARY.md) | Definitions of terms (agent, channel, mailbox, discipline, enforcer, adapter, etc.) |

## Reading order

- New here for an overview: README → DESIGN §1–3 → USAGE Quickstart.
- Implementing the core: DESIGN → CONTRACTS → IMPLEMENTATION-PLAN.
- Writing an adapter for a new runtime: CONTRACTS → IMPLEMENTATION-PLAN §Adapters → USAGE.
- Evaluating whether to adopt: DESIGN §1–4 → FUTURE → RESEARCH.

## Provenance

This protocol was extracted from design conversations during the SOX (supervisor) system in the [`claude-agents`](https://github.com/) repository. The naming convention (`sox-protocol`) reflects its origin; the protocol itself is independent of the SOX supervisor and is intended to be useful to any multi-agent LLM project.
