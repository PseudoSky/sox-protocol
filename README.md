# SOX Protocol — runtime-agnostic peer messaging for LLM agents

**Status:** v0.0.1; SOX v1.0-compliant Python reference implementation
**License:** MIT

---

## What is SOX?

SOX Protocol fills a structural gap in multi-agent LLM systems: *no surveyed framework markets a documented pattern for speculative-execute-while-awaiting-clarification.* When agent A needs clarification on ambiguous context, it should post a question to peers, continue working under a best-guess interpretation, and non-destructively integrate the late-arriving answer into its in-progress reasoning — all without blocking.

SOX provides the channel layer and discipline to make this pattern first-class.

### The portable core

1. **Markdown discipline** — opinionated guidance on when to send, when to drain, how to reconcile late answers, worked examples.
2. **Pure-function enforcer** — decides when to inject reminders or block actions based on operator-tunable policy.
3. **MCP server** — non-blocking `send` / `recv` tools holding a persistent connection to a backing store.
4. **Pluggable backing store** — SQLite (default), filesystem, NATS, Redis. You choose durability semantics.

The protocol is language-neutral; runtime-specific bits (Claude Code skills, OpenAI Agents SDK hooks, LangGraph nodes, etc.) are thin adapter layers living in `packages/`.

### The gap: speculative-then-reconcile

```
T=1   Agent A detects ambiguity.
      A posts clarification to group channel, continues under best-guess.
      
T=4   A's mailbox has a reply from B.
      A reads it, reconciles it with in-progress work (confirm or revise).
      
T=20  The blocker A feared never hits because the uncertainty was resolved in time.
```

Existing frameworks offer:
- **Turn-taking schedulers** (CrewAI, LangGraph, OpenAI Swarm) — A stops while B answers.
- **Handoff frameworks** (OpenAI Agents SDK) — control transfers to B; A stops.
- **Actor primitives** (AutoGen, MetaGPT) — the right building blocks, but no packaged discipline.

SOX packages the discipline and enforces the cadence. See [DESIGN.md §1–3](docs/DESIGN.md) for the full motivation.

---

## Quickstart

### Install (Claude Code)

From your project root:

```bash
pip install sox-protocol
python -m sox_protocol.adapters.runtimes.claude_code install
```

This initialises the backing store (SQLite in `.sox/messages.db`), registers the MCP server, installs a skill with the full discipline, and sets up cadence hooks.

### Verify

```bash
python -m sox_protocol.cli verify
```

### One-line bootstrap in agent prompts

Each agent that uses channels needs one line in its system prompt:

```markdown
For coordination with other agents (clarification, broadcasts, peer questions),
load the `inter-agent-channels` skill when blocked, broadcasting, or seeking peer input.
```

### Try the examples

Two end-to-end scenarios in the repo:

```bash
cd examples/two-agent-clarification
bash run.sh  # two agents collaborate; Agent A posts a question, Agent B answers

cd ../group-broadcast
bash run.sh  # Agent A broadcasts status; all agents in the channel see it
```

See each example's `README.md` for the agent prompts and walkthrough.

---

## Repo navigation

```text
sox-protocol/
├── docs/                         # Design, usage, future roadmap
│   ├── README.md                 # (entry point: read first)
│   ├── DESIGN.md                 # Problem + architecture
│   ├── CONTRACTS.md              # Formal interface specs (adapters, enforcer, tools)
│   ├── USAGE.md                  # Integration guide for Claude Code projects
│   ├── FUTURE.md                 # Deferred features & public roadmap
│   ├── RESEARCH.md               # Annotated bibliography
│   ├── GLOSSARY.md               # Term definitions
│   └── blog/
│       └── v0-launch.md          # Technical writeup on the v0 release
├── spec/                         # Canonical, language-neutral artefacts
│   ├── VERSION                   # Protocol version (1.0)
│   ├── README.md                 # Spec structure & conformance bar
│   ├── schemas/                  # JSON Schema (wire definitions)
│   │   ├── event.schema.json     # Enforcer input
│   │   ├── decision.schema.json  # Enforcer output
│   │   ├── policy.schema.json    # Operator-tunable parameters
│   │   ├── state.schema.json     # Per-agent enforcer state
│   │   ├── message.schema.json   # Received message shape
│   │   └── tools/                # MCP tool input/output schemas
│   ├── discipline/               # Markdown discipline document
│   │   ├── discipline.md         # Full guidance with {{placeholders}}
│   │   └── examples/             # Worked examples (send-and-continue, reconciliation, broadcast)
│   ├── ports/                    # Port behaviour contracts (prose)
│   │   ├── backing-store.md
│   │   ├── runtime-discipline-renderer.md
│   │   └── runtime-enforcer-binding.md
│   └── conformance/              # Language-neutral test harness
│       ├── README.md
│       ├── docker-compose.yml
│       ├── scenarios/            # 7 JSON scenarios (baseline, multi-subscriber, late reply, etc.)
│       └── runner/run.sh
├── packages/                     # Language-specific implementations
│   ├── python/                   # v0 reference implementation (SOX v1.0-compliant)
│   ├── typescript/               # Placeholder; open to contributions
│   └── rust/                     # Placeholder; open to contributions
├── examples/                     # End-to-end walkthroughs
│   ├── two-agent-clarification/  # Agent A posts a question; B answers
│   └── group-broadcast/          # Agent A broadcasts; all agents on channel see it
└── Makefile                      # test, lint, conformance, install
```

---

## Status & conformance

| Component | Status | Conformance |
|---|---|---|
| **Spec (v1.0)** | Frozen; language-neutral; all artefacts complete | N/A |
| **Python implementation** | Complete; production-ready | Passes `spec/conformance/scenarios/` (7 scenarios) |
| **TypeScript** | Not implemented; placeholder with guidance | Open to contributions; must pass conformance suite |
| **Rust** | Not implemented; placeholder with guidance | Open to contributions; must pass conformance suite |

To check conformance of the Python implementation:

```bash
make conformance
```

Non-Python ports must pass the same suite before merge. See [spec/README.md §Adding a new language port](spec/README.md#adding-a-new-language-port) for details.

---

## Documentation

| Audience | Start here |
|---|---|
| **You're new to SOX** | [docs/README.md](docs/README.md) → [DESIGN.md §1–3](docs/DESIGN.md) → this README's Quickstart |
| **You want to integrate SOX into Claude Code** | [docs/USAGE.md](docs/USAGE.md) → Quickstart (above) |
| **You want to write a runtime adapter** | [docs/CONTRACTS.md](docs/CONTRACTS.md) → [docs/IMPLEMENTATION-PLAN.md](docs/IMPLEMENTATION-PLAN.md) |
| **You want to contribute a TS/Rust port** | [packages/typescript/README.md](packages/typescript/README.md) or [packages/rust/README.md](packages/rust/README.md) → [spec/README.md §Adding a new language port](spec/README.md#adding-a-new-language-port) |
| **You want the research context** | [docs/RESEARCH.md](docs/RESEARCH.md) |
| **You're evaluating adoption** | [DESIGN.md §1–4](docs/DESIGN.md) → [FUTURE.md](docs/FUTURE.md) → [GLOSSARY.md](docs/GLOSSARY.md) |

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for:

- How to propose spec changes.
- How to contribute a TypeScript or Rust port.
- Code style and testing expectations.
- Merge gates (conformance suite, linting, type checking).

---

## License

MIT. See LICENSE for details.

---

## Who builds this

The SOX Protocol was designed by [authors] and is maintained by the community.

---

## Next steps

- **Integrate into your project:** [docs/USAGE.md](docs/USAGE.md)
- **Understand the design:** [docs/DESIGN.md](docs/DESIGN.md)
- **See examples:** `examples/` directory
- **Contribute:** [CONTRIBUTING.md](CONTRIBUTING.md)
