# SOX Protocol — v0 Implementation Plan

This document is a milestone-ordered plan for building the v0 reference implementation. It assumes the design in [DESIGN.md](./DESIGN.md) and the contracts in [CONTRACTS.md](./CONTRACTS.md).

---

## 1. Repo layout

The SOX project is a monorepo with two top-level concerns: the **spec** (`spec/` — the language-neutral protocol artefacts) and **packages** (`packages/<lang>/` — language-specific implementations that consume the spec). v0 implements `packages/python/`; `packages/typescript/` and `packages/rust/` are placeholder directories whose READMEs document the conformance bar and invite contributions.

```text
sox-protocol/
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── docs/                                # the v0 design documents
│   ├── README.md
│   ├── DESIGN.md
│   ├── IMPLEMENTATION-PLAN.md           # this file
│   ├── USAGE.md
│   ├── CONTRACTS.md
│   ├── FUTURE.md
│   ├── RESEARCH.md
│   └── GLOSSARY.md
│
├── spec/                                # CANONICAL: the protocol itself; language-neutral
│   ├── README.md                        # how the spec is structured
│   ├── VERSION                          # 1.0
│   ├── schemas/                         # JSON Schema files
│   │   ├── event.schema.json
│   │   ├── decision.schema.json
│   │   ├── policy.schema.json
│   │   ├── state.schema.json
│   │   ├── message.schema.json
│   │   └── tools/
│   │       ├── send.input.schema.json
│   │       ├── send.output.schema.json
│   │       ├── recv.input.schema.json
│   │       ├── recv.output.schema.json
│   │       ├── subscribe.input.schema.json
│   │       ├── subscribe.output.schema.json
│   │       └── list-channels.output.schema.json
│   ├── discipline/                      # consumed by every runtime adapter
│   │   ├── discipline.md                # canonical, with {{placeholder}} tokens
│   │   └── examples/
│   │       ├── send-and-continue.md
│   │       ├── reconciliation.md
│   │       └── group-broadcast.md
│   ├── ports/                           # port behaviour contracts in prose
│   │   ├── backing-store.md             # atomicity, ordering, delivery semantics
│   │   ├── runtime-discipline-renderer.md
│   │   └── runtime-enforcer-binding.md
│   └── conformance/                     # language-neutral test harness
│       ├── README.md
│       ├── docker-compose.yml           # spins up MCP server under test
│       ├── scenarios/                   # JSON scenario files
│       │   ├── 01-send-and-recv.json
│       │   ├── 02-group-broadcast.json
│       │   ├── 03-subscription-glob.json
│       │   ├── 04-concurrent-writers.json
│       │   ├── 05-per-channel-ordering.json
│       │   ├── 06-listener-buffering.json
│       │   └── 07-recv-atomicity.json
│       └── runner/
│           └── run.sh                   # bash + jq harness; invokes MCP client
│
├── packages/
│   ├── python/                          # v0 REFERENCE IMPLEMENTATION
│   │   ├── README.md
│   │   ├── pyproject.toml
│   │   ├── src/sox_protocol/
│   │   │   ├── core/                    # never imports adapters/
│   │   │   │   ├── enforcer/
│   │   │   │   │   ├── decide.py        # pure function: Event → Decision
│   │   │   │   │   ├── policy.py
│   │   │   │   │   ├── state.py
│   │   │   │   │   └── events.py        # Python dataclasses generated from spec/schemas/
│   │   │   │   ├── mcp_server/
│   │   │   │   │   ├── server.py        # FastMCP; stdio + HTTP
│   │   │   │   │   ├── listener.py      # background asyncio task
│   │   │   │   │   └── tools.py
│   │   │   │   └── ports/               # Python BINDINGS of port specs
│   │   │   │       └── backing_store.py # ABC; behaviour spec'd in spec/ports/backing-store.md
│   │   │   └── adapters/
│   │   │       ├── runtimes/
│   │   │       │   └── claude_code/
│   │   │       │       ├── install.py
│   │   │       │       ├── skill/SKILL.md.template
│   │   │       │       └── hooks/
│   │   │       │           ├── post_tool_use.sh
│   │   │       │           └── stop.sh
│   │   │       └── backing_stores/
│   │   │           ├── sqlite/
│   │   │           ├── filesystem/
│   │   │           └── memory/
│   │   └── tests/
│   │       ├── unit/
│   │       ├── conformance/             # runs spec/conformance/scenarios/ against this impl
│   │       │   └── run_python_impl.py
│   │       ├── integration/
│   │       └── adapters/
│   │           ├── runtimes/
│   │           └── backing_stores/
│   │
│   ├── typescript/                      # NOT IMPLEMENTED — open to contributions
│   │   └── README.md                    # documents conformance bar; mirrors python/ layout
│   │
│   └── rust/                            # NOT IMPLEMENTED — open to contributions
│       └── README.md
│
├── examples/                            # runnable cross-package demos
│   ├── two-agent-clarification/
│   └── group-broadcast/
│
└── .github/
    └── workflows/
        ├── spec-lint.yml                # validates schemas + discipline anchors
        ├── python-ci.yml                # tests + conformance for packages/python/
        └── conformance-badge.yml        # generates per-package conformance badge
```

### 1.1 Dependency direction

Strict rules:

- **`packages/<lang>/core/` MUST NOT import from `packages/<lang>/adapters/`.** Hexagonal core; adapters depend on ports; core depends on no adapter. Enforced by import-linter (Python) or equivalent in each language.
- **`packages/<lang>/` MAY consume from `spec/`** at build/install time (read JSON Schema for codegen, read discipline.md for templating, etc.). The reverse is forbidden: `spec/` is language-neutral and MUST NOT depend on any package.
- **The conformance suite (`spec/conformance/`)** runs against the MCP wire interface only. It does not link against any package's source.

These rules give a clean three-tier topology: spec → package core → package adapters. Tests live outside the topology and can import any of it.

### 1.2 How the spec is consumed

Each language package consumes the spec in three ways:

1. **Build-time codegen** from `spec/schemas/*.schema.json` to language-native types (Python dataclasses via `datamodel-code-generator`; TypeScript types via `json-schema-to-typescript`; Rust types via `schemars` or hand-written + tested for equivalence).
2. **Install-time templating** from `spec/discipline/discipline.md` — the runtime adapter's installer reads the canonical discipline and substitutes `{{placeholder}}` tokens with concrete tool names.
3. **Runtime conformance** — at CI time, the package's conformance runner spins up its MCP server and runs `spec/conformance/scenarios/*.json` against it.

For the Python package specifically, the spec content is bundled into the wheel via `MANIFEST.in` so `pip install sox-protocol` ships a copy of the spec inside the package. The package never falls out of sync with the spec because the build pipeline regenerates types from `spec/schemas/` on every release.

---

## 2. Tech-stack choices

| Choice | Decision | Rationale |
|---|---|---|
| Language (core) | Python 3.11+ | Most LLM tooling lives in Python; MCP server SDKs (FastMCP, official MCP Python SDK) are mature |
| MCP framework | [FastMCP](https://gofastmcp.com/) | Lightweight, supports stdio + HTTP, handles tool registration cleanly |
| Async runtime | `asyncio` | Standard library; FastMCP integrates natively |
| Backing store (default) | SQLite (WAL mode) via `aiosqlite` | Zero-deps, durable, concurrent-safe, easy to inspect |
| Test framework | `pytest` + `pytest-asyncio` | Standard |
| Schema | `pydantic` v2 | Used by FastMCP and most modern Python LLM tooling |
| Build / packaging | `uv` or `pip` + `pyproject.toml` | PEP 621 compliant |
| Lint / format | `ruff` | One tool, fast |
| Type-checking | `mypy --strict` for `core/`; relaxed for adapters | Core is pure logic; strict types pay off |

---

## 3. Milestones

Each milestone has clear acceptance criteria. Milestones are sequential where dependencies require it; parallelisable work is noted.

### Milestone 0 — Spec frozen

**Goal:** publish the canonical, language-neutral protocol artefacts in `spec/`. All subsequent milestones consume from here.

**Deliverables:**

- `spec/VERSION` = `1.0`.
- `spec/schemas/` — JSON Schema files for `Event`, `Decision`, `Policy`, `State`, `Message`, and the four MCP tool inputs/outputs.
- `spec/discipline/discipline.md` with the stable section anchors per [CONTRACTS §2](./CONTRACTS.md#2-discipline-document-structure) and `{{placeholder}}` tool-name tokens. (Worked examples in `spec/discipline/examples/` land at Milestone 4.)
- `spec/ports/backing-store.md` — port behaviour contract in prose (atomicity, ordering, delivery semantics — no language binding).
- `spec/ports/runtime-discipline-renderer.md`, `spec/ports/runtime-enforcer-binding.md` — same shape for the runtime-side ports.
- `spec/README.md` documenting how `spec/` is consumed by packages.
- CI workflow `spec-lint.yml` validating schemas (`ajv`), discipline anchors (custom linter), and that no path under `spec/` references any package directory.

**Acceptance:**

- All schemas validate as JSON Schema 2020-12.
- Discipline document passes the anchor linter.
- `spec-lint.yml` passes on a fresh checkout.
- No path under `spec/` references `packages/`.

---

### Milestone 1 — Python core enforcer

**Goal:** the pure-function cadence enforcer in `packages/python/`.

**Deliverables:**

- `packages/python/src/sox_protocol/core/enforcer/events.py` — `Event` and `Decision` dataclasses generated from `spec/schemas/event.schema.json` and `spec/schemas/decision.schema.json` via `datamodel-code-generator` (committed, with regen in the build pipeline).
- `packages/python/src/sox_protocol/core/enforcer/policy.py` — `Policy` dataclass per `spec/schemas/policy.schema.json`, with sensible defaults (e.g. `reminder_threshold_tool_calls = 5`, `force_drain_on_stop = True`).
- `packages/python/src/sox_protocol/core/enforcer/state.py` — SQLite-backed per-agent counters per `spec/schemas/state.schema.json`.
- `packages/python/src/sox_protocol/core/enforcer/decide.py` — `decide(event: Event, state: State, policy: Policy) -> Decision`.
- `packages/python/tests/unit/test_decide.py` — exhaustive test of policy edge cases.
- Import-linter rule enforcing `core/` does not import from `adapters/`.

**Acceptance:**

- 100% line coverage on `decide.py`.
- Test matrix covers: cold-start, threshold-crossed, stop-without-drain, send-and-stall pattern.
- `mypy --strict` passes on `packages/python/src/sox_protocol/core/`.
- Import-linter rule green.

**Parallelisable with:** Milestone 2.

---

### Milestone 2 — Python BackingStore port binding + reference adapters (SQLite, filesystem, memory)

**Goal:** the Python *binding* of the `BackingStore` port (port spec lives in `spec/ports/backing-store.md`), plus three reference backing-store adapters in the Python package.

**Deliverables:**

- `packages/python/src/sox_protocol/core/ports/backing_store.py` — `BackingStore` ABC. The ABC is the *Python binding* of the port; behaviour requirements (atomicity, ordering, delivery) are normative in `spec/ports/backing-store.md`. The Python ABC must not introduce additional semantics.
- `packages/python/src/sox_protocol/adapters/backing_stores/sqlite/store.py` — async SQLite implementation (WAL mode, `aiosqlite`). v0 default.
- `packages/python/src/sox_protocol/adapters/backing_stores/sqlite/schema.sql` — SQL schema (see below).
- `packages/python/src/sox_protocol/adapters/backing_stores/filesystem/store.py` — directory-per-channel, fswatch-based listener.
- `packages/python/src/sox_protocol/adapters/backing_stores/memory/store.py` — in-memory; for tests only.
- Schema (`adapters/backing_stores/sqlite/schema.sql`):

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    sender TEXT NOT NULL,
    body TEXT NOT NULL,           -- JSON
    correlation_id TEXT,
    sent_at REAL NOT NULL,
    delivered_to TEXT             -- JSON array of agent_ids that have drained
);
CREATE INDEX idx_messages_channel ON messages(channel);

CREATE TABLE subscriptions (
    agent_id TEXT NOT NULL,
    channel_pattern TEXT NOT NULL,
    PRIMARY KEY (agent_id, channel_pattern)
);
```

- `packages/python/tests/adapters/backing_stores/test_port_contract.py` — parametrised port-binding test suite covering: round-trip, concurrent writers, subscription matching (including glob), delivery tracking, watch-loop correctness. Runs against `SqliteStore`, `FilesystemStore`, `MemoryStore` via `pytest.mark.parametrize`.
- `packages/python/tests/adapters/backing_stores/test_sqlite_specific.py` — backend-specific behaviours (WAL mode, vacuum semantics, schema-migration smoke).
- `packages/python/tests/adapters/backing_stores/test_filesystem_specific.py` — fswatch behaviour, directory-locking edge cases.

**Acceptance:**

- `test_port_contract.py` passes against all three reference adapters — proving they all bind the same port.
- Stress test with 10 concurrent writers + 10 concurrent readers passes for 1000 messages without loss or duplication on `SqliteStore`.

**Parallelisable with:** Milestone 1.

**Note:** the *language-neutral* conformance suite at `spec/conformance/scenarios/` (Milestone 6 below) tests at the MCP wire level, not the Python ABC level. The Python port-contract tests above test the Python binding's conformance to the port spec; they are complementary.

---

### Milestone 3 — Python MCP server

**Goal:** the long-lived MCP server in the Python package with background listener and tool surface.

**Deliverables:**

- `packages/python/src/sox_protocol/core/mcp_server/server.py` — FastMCP server registering the four tools. Tool input/output schemas validated against `spec/schemas/tools/*.schema.json` at startup (fail-fast on schema drift).
- `packages/python/src/sox_protocol/core/mcp_server/listener.py` — `asyncio.create_task` at startup; subscribes to backing store via `BackingStore.watch`; buffers messages locally per subscribed channel.
- `packages/python/src/sox_protocol/core/mcp_server/tools.py` — the four tools. Behaviour matches `spec/schemas/tools/*.schema.json` and the contracts in [CONTRACTS.md §5](./CONTRACTS.md#5-mcp-tool-surface).
- Configuration via env vars: `SOX_BACKING_STORE` (`sqlite://...` / `file://...` / `memory://`), `SOX_AGENT_ID`.
- Both stdio and HTTP transports supported (FastMCP gives both; default to stdio).

**Acceptance:**

- `packages/python/tests/integration/test_mcp_server_e2e.py` — spawns server in subprocess, sends and receives messages via MCP client, verifies outputs match `spec/schemas/`.
- Two MCP server instances connected to one shared SQLite backing store correctly fan messages to subscribers.
- Background listener buffers ≥100 messages without loss while no `recv` call is pending.

**Depends on:** Milestones 1 & 2.

---

### Milestone 4 — Discipline document and worked examples (in `spec/`)

**Goal:** the canonical markdown content consumed by every runtime adapter across every language package.

**Deliverables:**

- `spec/discipline/discipline.md` with the stable section anchors from CONTRACTS §2 (the headings were stubbed at Milestone 0; this milestone fleshes out the prose).
- `spec/discipline/examples/send-and-continue.md` — worked example: ambiguity detected → send → continue under best-guess → drain → reconcile.
- `spec/discipline/examples/reconciliation.md` — worked example: late reply contradicts best-guess → revise assumption → emit diff.
- `spec/discipline/examples/group-broadcast.md` — worked example: status broadcast to a ticket channel.

**Acceptance:**

- The discipline-anchor linter (from Milestone 0) confirms all required headings present, in order.
- Discipline content uses only `{{placeholder}}` tokens, never concrete tool names.
- Each example is runnable as a literal scenario on the Python reference Claude Code adapter (validated at Milestone 5).

**Parallelisable with:** Milestones 1–3 (writing prose is independent of code).

---

### Milestone 5 — Python Claude Code runtime adapter

**Goal:** the reference runtime adapter, wiring the Python core into Claude Code.

**Deliverables:**

- `packages/python/src/sox_protocol/adapters/runtimes/claude_code/install.py` — installs the SOX skill into a target Claude Code project:
  - Reads the bundled `spec/discipline/discipline.md` (shipped inside the wheel via `MANIFEST.in`).
  - Renders into `skill/SKILL.md.template` with frontmatter (`name: inter-agent-channels`, `description: ...`).
  - Substitutes tool-name placeholders (`{{send_tool}}` → `mcp__sox__channels__send`, etc.).
  - Writes to `<project>/.claude/skills/inter-agent-channels/SKILL.md`.
  - Writes hook scripts to `<project>/tools/sox-hooks/`.
  - Updates `<project>/.claude/settings.json` with hook registrations and MCP server config.
- `packages/python/src/sox_protocol/adapters/runtimes/claude_code/hooks/post_tool_use.sh` — reads stdin (Claude Code hook input JSON), invokes `python -m sox_protocol.enforcer cli`, prints any returned `Decision` as Claude Code-shaped JSON.
- `packages/python/src/sox_protocol/adapters/runtimes/claude_code/hooks/stop.sh` — same shape but invoked on stop events; can return a `block` decision to force inbox drain before agent exits.
- A bootstrap snippet inserted into target agents' system prompts (one line: *"Inter-agent coordination is available; load the inter-agent-channels skill when blocked, broadcasting, or asking peers for clarification."*).

**Acceptance:**

- `packages/python/tests/adapters/runtimes/test_claude_code_install.py` — installs into a fresh Claude Code project fixture; verifies skill, hooks, settings, and MCP config are all present and well-formed.
- A live Claude Code session in the fixture can send and receive a message between two subagents using the installed adapter.

**Depends on:** Milestones 1–4.

---

### Milestone 6 — Language-neutral conformance harness (in `spec/`)

**Goal:** the verification authority for SOX-compliance. Any language implementation that passes this is SOX v1.0-compliant; that's how the protocol is enforced.

**Deliverables:**

- `spec/conformance/README.md` — how to run the harness against an implementation.
- `spec/conformance/docker-compose.yml` — compose file that takes an `IMPLEMENTATION_IMAGE` env var; spins up the implementation's MCP server and a generic MCP client.
- `spec/conformance/scenarios/` — JSON scenario files. Each scenario specifies: required env vars, a sequence of MCP tool calls with arguments, and expected outputs (or output predicates). v0 ships at minimum:
  - `01-send-and-recv.json` — single sender, single receiver, exact round-trip.
  - `02-group-broadcast.json` — one sender, three receivers on the same channel.
  - `03-subscription-glob.json` — glob patterns deliver matching messages only.
  - `04-concurrent-writers.json` — N concurrent senders, no loss / duplication.
  - `05-per-channel-ordering.json` — within-channel send-time order preserved.
  - `06-listener-buffering.json` — message arrives before recv; first recv drains it (latency property of the listener).
  - `07-recv-atomicity.json` — recv'd messages not redelivered to the same agent.
- `spec/conformance/runner/run.sh` — bash + jq harness. Iterates scenarios, executes each against the running MCP server, validates outputs against `spec/schemas/` and per-scenario expected outputs.
- `packages/python/tests/conformance/run_python_impl.py` — thin wrapper that spawns the Python MCP server and invokes `spec/conformance/runner/run.sh` against it.

**Acceptance:**

- All scenarios pass against the Python reference implementation in CI (`python-ci.yml`).
- A `conformance-badge.yml` workflow generates a per-package badge (`packages/python/` → "SOX v1.0 ✓"; placeholder packages have no badge until they pass).
- The `spec/conformance/` directory imports nothing from `packages/`. Re-validated by `spec-lint.yml`.

**Depends on:** Milestones 0, 3.

**Why this is its own milestone:** the conformance suite is the load-bearing piece for the language-agnostic claim. It must exist before any other-language port is meaningful, and it must be authored against the spec without leaking Python assumptions. Building it as part of `spec/` rather than under `packages/python/tests/` is what makes it usable by future TS / Rust ports without modification.

---

### Milestone 7 — End-to-end demo & integration tests

**Goal:** prove the design on real workloads.

**Deliverables:**

- `examples/two-agent-clarification/` — two Claude Code subagents collaborating on a task; one asks a clarification, the other answers, the first reconciles.
- `examples/group-broadcast/` — three subagents in a ticket channel; one broadcasts a status update, two acknowledge.
- `packages/python/tests/integration/test_two_agent_exchange.py` — automated version of the first demo, runnable in CI.

**Acceptance:**

- Demo runs reproducibly on a fresh checkout with `make demo`.
- Integration test passes in CI on Linux + macOS, Python 3.11 and 3.12.

**Depends on:** Milestone 5.

---

### Milestone 8 — Documentation polish, placeholder packages, & v0 publication

**Goal:** publishable artefact.

**Deliverables:**

- All docs in `docs/` reviewed for accuracy against the implementation.
- `README.md` at repo root with quickstart, monorepo navigation, and conformance-bar callout for non-Python ports.
- `packages/typescript/README.md` and `packages/rust/README.md` — placeholder READMEs documenting:
  - status: not implemented at v0; open to contributions.
  - conformance bar: pass `spec/conformance/scenarios/` against the implementation's MCP server.
  - suggested architecture: mirror `packages/python/` layout (core/{enforcer, mcp_server, ports} + adapters/{runtimes, backing_stores}).
  - contribution process: open issue claiming the package; submit PR; merge gates on conformance suite passing.
- `CONTRIBUTING.md` at repo root explaining the spec/package separation and the contribution process for both spec changes (PR against `spec/` with `spec-lint.yml` passing and at least one implementation updated to match) and language ports.
- `CHANGELOG.md` with v0.0.1 entry.
- A short blog post or technical writeup linked from the README (one to three pages summarising the gap and the solution).
- Git tag `v0.0.1`.

**Acceptance:**

- A reader unfamiliar with the project can install, run the demo, and write a custom send/receive in under 30 minutes following only the published docs.
- The placeholder READMEs are sufficient for a TS or Rust developer to start a port without further guidance from the maintainer.

---

## 4. Out of scope for v0

Tracked in [FUTURE.md](./FUTURE.md). Highlights:

- OpenAI Agents SDK adapter, LangGraph adapter, AutoGen interop.
- NATS / Redis backing stores.
- HTTP MCP transport as default (v0 ships HTTP-capable but defaults to stdio).
- Push-style preemptive interrupts.
- Authoritative ordering / vector clocks.
- Authentication / authorisation / encryption.
- Cross-organisation A2A bridge.

---

## 5. Testing strategy

Three layers of tests, each with a different verification authority:

### 5.1 Language-neutral conformance suite (`spec/conformance/`)

- The verification authority for **SOX-compliance**. Defined as JSON scenarios; runs against any implementation's MCP server via Docker.
- Authored against the spec without language assumptions.
- Each language package has a thin runner under `packages/<lang>/tests/conformance/` that spawns its MCP server and invokes `spec/conformance/runner/run.sh`.
- Passing this is what makes any future TS / Rust / other implementation SOX v1.0-compliant.

### 5.2 Per-package unit tests (`packages/<lang>/tests/unit/`)

- Verify implementation correctness of internal logic (the cadence enforcer, MCP tool handlers, etc.).
- Python: pure-function `decide()` tests cover the policy state-space exhaustively (~100% coverage); MCP tool tests use FastMCP's in-process test client.

### 5.3 Per-package port-binding tests (`packages/<lang>/tests/adapters/backing_stores/test_port_contract.py`)

- Verify that this package's *binding* of the `BackingStore` port satisfies the port-spec behaviours from `spec/ports/backing-store.md`.
- Parametrised across every adapter the package ships (Python: `MemoryStore`, `SqliteStore`, `FilesystemStore`).
- Distinct from the language-neutral conformance suite: this tests at the language ABC level; the conformance suite tests at the MCP wire level. Both must pass.

### 5.4 Per-package integration tests (`packages/<lang>/tests/integration/`)

- Subprocess-launch the MCP server with a SQLite store; connect with an MCP client; run send/recv scenarios.
- Two MCP servers + one shared store: verify fan-out, no duplication, no loss.

### 5.5 Per-package adapter-specific tests (`packages/<lang>/tests/adapters/`)

- `tests/adapters/runtimes/` — runtime-adapter-specific behaviours (e.g., Claude Code install fixture).
- `tests/adapters/backing_stores/` — backend-specific behaviours not covered by the port-contract tests (e.g., SQLite WAL mode, filesystem fswatch edge cases).

### 5.4 Live tests

The `claude-agents` SOX system in this repository will exercise the protocol end-to-end on real Claude subagent workloads. This is the canonical "live test" per the [project's mock-vs-live policy](../../../../CLAUDE.md). v0 publication includes a section in USAGE.md describing how operators can run their own live tests.

---

## 6. Versioning policy

- Schemas in CONTRACTS.md carry a `version` field. Bumps follow semver-for-protocols:
  - **Patch** (1.0 → 1.0.1): clarifications, no wire change.
  - **Minor** (1.0 → 1.1): backward-compatible additions (new optional fields, new tools).
  - **Major** (1.0 → 2.0): breaking change to wire / behaviour.
- Adapters declare which protocol version they target.
- The MCP server announces its protocol version in `channels__list_channels()` response metadata so adapters can detect mismatches.

---

## 7. Estimated effort

Rough order-of-magnitude estimates for a single experienced developer:

| Milestone | Effort |
|---|---|
| M0 — Spec frozen (`spec/` scaffolding, schemas, port docs, lint workflows) | 2–4 days |
| M1 — Python core enforcer | 2–3 days |
| M2 — Python `BackingStore` binding + 3 adapters | 2–3 days |
| M3 — Python MCP server | 3–5 days |
| M4 — Discipline doc + worked examples (in `spec/`) | 2–4 days (heavily iteration-dependent) |
| M5 — Python Claude Code runtime adapter | 3–5 days |
| M6 — Language-neutral conformance harness | 3–5 days |
| M7 — Demos & integration | 2–4 days |
| M8 — Docs polish + placeholder package READMEs + publication | 2–3 days |
| **Total** | **~4–6 weeks** for v0.0.1 |

The estimate is roughly +1 week vs the previous single-package plan. The added cost is concentrated in M0 (authoring the spec as language-neutral artefacts rather than Python types) and M6 (the conformance harness as its own first-class deliverable). Both are load-bearing for the language-agnostic claim and avoid retroactive rework when a TS or Rust port lands.

Effort is concentrated in three non-coding areas: (a) the discipline document, which is genuinely a prompt-engineering iteration loop; (b) the conformance scenarios, which require careful coverage analysis to avoid Python-isms leaking in; (c) the demos, which surface design issues that ripple back to earlier milestones.
