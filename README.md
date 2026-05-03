# SOX Protocol — runtime-agnostic peer messaging for LLM agents

**Status:** v0.0.1; SOX v1.0-compliant Python reference implementation
**License:** [![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0) Apache 2.0

> **Patent grant:** SOX Protocol is licensed under Apache 2.0, which includes an express patent grant (§3) from every contributor. This means contributors and users are protected from patent assertions on the protocol primitives they help build or adopt. See [docs/ip/](docs/ip/) for the full IP strategy, OIN application tracker, and Software Heritage archival record.

---

## Demo — `sox chat` TUI

![SOX Protocol two-agent demo](docs/media/demo.gif)

> Two agents collaborating over SOX channels in real time: threaded replies, DMs,
> ACK/NACK signals, and presence — all in the `sox chat` terminal UI.
> Run `python3 examples/two-agents-talking/demo.py` to see the scripted conversation.
> Regenerate the recording: `vhs examples/two-agents-talking/demo.tape`
> (see [docs/media/demo.cast](docs/media/demo.cast) for the asciinema-compatible recording).

---

## What is in `spec/`?

`spec/` is the canonical, language-neutral specification for SOX Protocol. It contains everything needed to implement SOX in any language, independent of the Python reference implementation:

- **`spec/protocol.md`** — top-level overview: four core operations, message envelope shape, novelty claim, links to all sub-specs.
- **`spec/primitives/`** — one file per concept: channels, groups, DMs, threads, presence, ACK/NACK, pending state, sequence numbers, trace IDs.
- **`spec/ports/`** — behaviour contracts (not language-specific) for BackingStore, Transport, Identity, Middleware, DisciplineRenderer, and EnforcerBinding.
- **`spec/state-machines/`** — message lifecycle (sent → stored → buffered → delivered → acked/replied/nacked) and agent presence states.
- **`spec/envelopes/`** — JSON Schema 2020-12 for reserved body types: `sox-ack`, `sox-nack`, `sox-error`, `sox-invite`.
- **`spec/operations/`** — JSON Schema 2020-12 for every tool's input and output: `send`, `recv`, `subscribe`, `list_channels`.
- **`spec/schemas/`** — JSON Schema 2020-12 for enforcer internals: Event, Decision, State, Policy, Message.
- **`spec/discipline/`** — canonical markdown discipline with `{{placeholder}}` tokens; adapters substitute at install time.
- **`spec/conformance/`** — Docker-based, language-neutral test harness; passing it makes an implementation "SOX v1.0-compliant."

`packages/python/` is one conformant reference implementation. `packages/typescript/` and `packages/rust/` are open for contributions. See [docs/adr/0001-protocol-vs-implementation-split.md](docs/adr/0001-protocol-vs-implementation-split.md) for the rationale behind this split.

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

### Try the scripted examples

Two end-to-end scenarios in the repo (no Claude API key required):

```bash
make demo           # two-agent clarification + reconcile
make demo-broadcast # three-agent status broadcast
```

### Try it live: two Claude shells collaborating

This demo runs two real Claude Code sessions side-by-side. Each agent
reads a different half of your codebase and they coordinate findings
via SOX channels — you watch the messages arrive in each terminal.

**Prerequisites:** SOX installed in your project (`pip install sox-protocol &&
python -m sox_protocol.adapters.runtimes.claude_code install`), then restart
Claude Code so the MCP server is picked up.

**Step 1 — open two terminals, both in your project root**

**Step 2 — watch the message stream in a third terminal (optional but satisfying)**

```bash
watch -n2 'sqlite3 .sox/messages.db \
  "select datetime(sent_at, \"unixepoch\", \"localtime\"), sender, \
   json_extract(body, \"$.type\"), \
   substr(coalesce(json_extract(body, \"$.subject\"), json_extract(body, \"$.text\")), 1, 60) \
   from messages order by sent_at"'
```

**Step 3 — terminal 1: launch Claude as `product-agent`**

```bash
SOX_AGENT_ID=product-agent claude
```

Paste this prompt:

```
You are a product analyst doing a first-pass review of this codebase.
Your job: understand what this project does, who it's for, and what
the most valuable next feature would be.

Read the README, any docs/ folder, existing tests (to understand
what's already built), and any FUTURE or ROADMAP files if they exist.
Do NOT read implementation source yet — that's your peer's job.

Your peer is "engineer-agent" on channel "ticket:REVIEW-001". They
are reading the implementation in parallel.

COMMUNICATION RULES:
- Start by subscribing to ticket:REVIEW-001.
- WHENEVER YOU DRAIN: print "📬 INBOX DRAIN" followed by every
  message received, quoted exactly:
    [from: <sender>] <type> — <subject>
    "<full answer or context field>"
  If empty, print "📭 inbox empty".
- When you send a question, print:
    📤 SENT TO PEER: <subject> — <question>
- After each received message, write one sentence on how it changes
  your thinking before continuing.

As you form hypotheses — "I think X would be valuable, but I don't
know if the architecture supports it" — send a clarification_request
and keep going. Don't wait. Drain at each major checkpoint.

When done, send a final status_update. Do a last drain and incorporate
any answers into your conclusion.

Deliver: a one-page feature proposal with a confidence rating on each
assumption, noting which were confirmed or denied by engineer-agent.
```

**Step 4 — terminal 2: launch Claude as `engineer-agent`**

```bash
SOX_AGENT_ID=engineer-agent claude
```

Paste this prompt:

```
You are a senior engineer doing a first-pass review of this codebase.
Your job: understand the architecture, the quality of the
implementation, and what would be easy vs hard to change.

Read the source code — structure, key modules, tests, any CI config.
Do NOT read docs or README yet — that's your peer's job.

Your peer is "product-agent" on channel "ticket:REVIEW-001". They
are reading the docs and forming a feature proposal in parallel.

COMMUNICATION RULES:
- Start by subscribing to ticket:REVIEW-001.
- WHENEVER YOU DRAIN: print "📬 INBOX DRAIN" followed by every
  message received, quoted exactly:
    [from: <sender>] <type> — <subject>
    "<full question or context field>"
  If empty, print "📭 inbox empty".
- When you reply to a question, print:
    📤 REPLIED TO PEER: <subject> — <your answer in one sentence>
- After each received message, write one sentence on how it affects
  your code review before continuing.

Drain at each major checkpoint. When a clarification_request arrives,
answer with a clarification_reply (same correlation_id) and keep going.

When done, send a status_update with your architectural assessment.

Deliver: a short technical brief — key architectural facts, one risk
area, and your verdict on the feature proposal once you've seen it.
```

**What you'll see:** product-agent prints `📭 inbox empty` on early drains while
engineer-agent is still reading code. Later drains print `📬 INBOX DRAIN` with
engineer-agent's answers arriving mid-analysis. Neither agent ever stalled —
that's the speculative-then-reconcile pattern working as designed.

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
| **You want to run the live Claude E2E test** | [docs/development/live-tests.md](docs/development/live-tests.md) |

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for:

- How to propose spec changes.
- How to contribute a TypeScript or Rust port.
- Code style and testing expectations.
- Merge gates (conformance suite, linting, type checking).

---

## License

Apache 2.0. See [LICENSE](LICENSE) for details. The Apache 2.0 license includes an express patent grant — see [docs/ip/](docs/ip/) for the IP strategy rationale.

---

## Who builds this

The SOX Protocol was designed by [authors] and is maintained by the community.

---

## Next steps

- **Integrate into your project:** [docs/USAGE.md](docs/USAGE.md)
- **Understand the design:** [docs/DESIGN.md](docs/DESIGN.md)
- **See examples:** `examples/` directory
- **Contribute:** [CONTRIBUTING.md](CONTRIBUTING.md)
