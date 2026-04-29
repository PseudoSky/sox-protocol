# SOX Protocol — Build State Machine

This document drives the v0 build. It pairs each milestone from [IMPLEMENTATION-PLAN.md](./IMPLEMENTATION-PLAN.md) with a chosen agent and a copy-paste-ready prompt. The operator advances state by running the indicated agent, verifying the exit criteria, and ticking the next phase from `BLOCKED` to `READY`.

---

## How to invoke

This document supports two modes.

### Auto mode (recommended)

From the repo root, in your shell:

```bash
claude "Run docs/BUILD-STATE.md"
```

Or open Claude Code interactively and say:

```text
Run docs/BUILD-STATE.md
```

When Claude reads this document, the **Orchestration Instructions** section below activates. Claude becomes the build orchestrator: it picks the next `READY` phase, spawns the named agent with the corresponding prompt, verifies exit criteria, updates the status table, commits, and loops. Execution continues until one of the [termination conditions](#termination-conditions) is met.

To resume a partially-completed build, simply re-run the same invocation. The state lives in this file and in git, so resumption is automatic.

### Manual mode

1. **Find the phase with status `READY`.** If multiple are `READY` they can run in parallel; pick one to start.
2. **Spawn the agent** named in `agent:` with the prompt in `M<N> prompt`. Most prompts are designed for `Agent` tool invocation; M4 is interactive.
3. **Verify exit criteria.** Each phase has explicit acceptance under `M<N> exit criteria`.
4. **Update the status table.** Mark the phase `DONE`; promote any phases listed under `M<N> next state` from `BLOCKED` to `READY`.
5. **Commit** the updated `BUILD-STATE.md` plus any phase outputs.

### State protocol

```text
BLOCKED     → prerequisites not yet DONE
READY       → all prerequisites DONE; can be picked up next
IN_PROGRESS → agent is currently executing this phase
REVIEW      → agent reported done; exit criteria failed verification
DONE        → exit criteria verified; unblocks downstream phases
```

---

## Orchestration Instructions (auto mode)

**If you are Claude reading this document because the user invoked `claude "Run docs/BUILD-STATE.md"` or said "Run docs/BUILD-STATE.md", you are the build orchestrator.** Your job is to drive the state machine to completion. Read this entire section before doing anything.

### Pre-flight

Before entering the main loop, verify:

1. **Working directory.** Run `git rev-parse --show-toplevel` via Bash. The result should end in `sox-protocol`. If not, stop and tell the user to `cd` to the correct repo root.
2. **This file exists** at `docs/BUILD-STATE.md`. (If you are reading it, this is already true.)
3. **Working tree is clean.** Run `git status --porcelain`. If output is non-empty, stop and prompt the user to commit or stash before continuing — the orchestrator commits after each phase, and a dirty tree creates ambiguity about authorship.
4. **Required tools available.** Probe for `git`, `ajv` (or `npx ajv`), `python3`, `pytest`, `mypy`, `docker`, `jq`. Missing tools that a downstream phase needs are not fatal until that phase runs; report what's missing in your status preamble so the user knows.

### Main loop

Repeat until a termination condition is met:

1. **Read the status table** in the [Status overview](#status-overview) section.
2. **Pick the next phase to execute:**
   - Find phases with status `READY`.
   - If multiple are `READY`, pick the lowest M-number.
   - If none are `READY` and M8 is `DONE`, declare success (see [termination conditions](#termination-conditions)).
   - If none are `READY` but some are `BLOCKED`, that's an orphan-blockage bug; stop and report.
3. **Mark the phase `IN_PROGRESS`** in the status table; commit with message `chore(state): M<N> in progress`.
4. **Execute the phase:**
   - **For delegated phases** (M0–M3, M5–M8): use the `Agent` tool. Set `subagent_type` to the value from the phase header. Set `description` to `Phase M<N>: <short title>`. Set `prompt` to the verbatim contents of the `M<N> prompt` code block. Wait for the agent to return.
   - **For M4** (interactive, no agent): print the `M4 starter prompt` block to the user; mark M4 `IN_PROGRESS`; commit; trigger the [interactive-pause termination](#termination-conditions). The user resumes by completing M4 manually, marking it `DONE`, and re-invoking the orchestrator.
5. **Verify exit criteria.** For each checkbox under `M<N> exit criteria`:
   - Translate the checkbox text into a concrete verification command using your judgment. Examples:
     - "All schemas validate as JSON Schema 2020-12" → `npx ajv compile -s 'spec/schemas/**/*.json' --spec=draft2020`
     - "100% line coverage on decide.py" → `cd packages/python && pytest tests/unit/test_decide.py --cov=src/sox_protocol/core/enforcer/decide --cov-fail-under=100`
     - "mypy --strict passes" → `cd packages/python && mypy --strict src/sox_protocol/core/`
     - "Import-linter green" → `cd packages/python && lint-imports`
     - "<file> exists" → `test -f <file>`
   - Run each via Bash. Capture pass/fail.
6. **Branch on verification result:**
   - **All pass:** mark the phase `DONE` in the status table; promote phases listed in the phase's `M<N> next state` from `BLOCKED` to `READY`; stage all new/changed files (`git add -A`); commit with `feat(M<N>): <one-line summary of deliverables>`. Loop back to step 1.
   - **Any fail:** mark the phase `REVIEW`; commit with `chore(state): M<N> failed verification`; trigger the [verification-failure termination](#termination-conditions). Do not advance.
7. **Loop.**

### Termination conditions

Stop and report when one of these occurs:

| Condition | Action |
|---|---|
| **Success** — M8 is `DONE` | Print: "All phases complete. v0.0.1 ready for tagging. Run `git tag v0.0.1 && git push --tags` to release." |
| **Verification failure** — phase exit criteria failed | Print: phase number, the specific checklist items that failed, the verification command output, and the agent's final report verbatim. Tell the user the options: re-spawn the agent with feedback, fix manually then mark `DONE`, or skip the criterion (not recommended). |
| **Agent error** — the agent crashed or returned an error | Mark phase `IN_PROGRESS` (revert from anything else); commit; print the error verbatim; tell the user the orchestrator can be re-invoked to retry. |
| **Interactive pause** — M4 is next | Print the M4 starter prompt; tell the user to drive it interactively, mark M4 `DONE` when finished, then re-invoke the orchestrator. |
| **Pre-flight failure** — repo state is wrong | Print which check failed; do not enter the main loop. |
| **Orphan blockage** — no `READY` phase but `BLOCKED` phases exist | Print the BLOCKED phases and their unmet prerequisites. Probably indicates a bug in the doc or the user's edits to the status table; stop. |
| **User interrupt** — any signal from the user | Stop cleanly; the latest committed state is recoverable. |

### Parallelism

The v0 orchestrator runs phases serially in M-number order, even when phases are documented as parallelisable (M1+M2, M5+M6). Serial execution simplifies state-table updates and commit sequencing. Operators who want true parallelism can fork worktrees and run separate orchestrator sessions per worktree.

### Hard rules for the orchestrator

You MUST:

- Verify every exit-criterion checkbox before marking a phase `DONE`. The agent's self-report is not sufficient.
- Commit after every state transition. Resumability depends on git being the source of truth.
- Use the prompt blocks verbatim — do not paraphrase, summarise, or "improve" them.
- Process phases in M-number order. Do not skip.

You MUST NOT:

- Modify any phase's `M<N> prompt` block. They are versioned artefacts.
- Mark a phase `DONE` without exit criteria passing.
- Continue after a verification failure without explicit user instruction.
- Auto-resolve verification failures by editing the deliverables yourself. Re-spawn the agent with corrective feedback, or surface to the user.

### Pre-loop status preamble

Before entering the main loop, print a single status block:

```text
SOX Protocol orchestrator engaged.
Repo: <path from git rev-parse>
Working tree: <clean | dirty>
Tools: git=<v> python=<v> ajv=<v> docker=<v> ...
Phase status: M0=READY M1=BLOCKED M2=BLOCKED M3=BLOCKED M4=BLOCKED M5=BLOCKED M6=BLOCKED M7=BLOCKED M8=BLOCKED
Next action: spawn `api-designer` for M0.
```

This gives the user one place to confirm everything looks right before any work happens.

---

### Optional review gates

Between code phases (M1, M2, M3, M5), an optional `code-reviewer` pass is recommended before marking `DONE`. Prompt template:

```text
agent: code-reviewer
prompt: Review the changes from Milestone <N> of the SOX Protocol build. Read docs/IMPLEMENTATION-PLAN.md §3 Milestone <N> for the deliverables and acceptance criteria. Focus on: (a) schema fidelity (does the implementation match spec/schemas/?), (b) port-spec fidelity (does the implementation match the prose contracts in spec/ports/?), (c) test coverage gaps, (d) the dependency-direction rule from §1.1 (core/ MUST NOT import from adapters/). Report: pass/fail with specific file:line citations for any issues.
```

Optional QA review at M7:

```text
agent: qa-expert
prompt: Audit the SOX Protocol v0 build for shippable quality. Read docs/IMPLEMENTATION-PLAN.md §5 (testing strategy). Check: conformance-suite scenario coverage adequate? integration tests stable? unit-test gaps? live demo reproducible from a fresh checkout? Report under 300 words with specific gap citations.
```

---

## Status overview

Update this table as phases complete.

| Phase | Title | Status | Agent | Parallel with |
|---|---|---|---|---|
| M0 | Spec frozen | `DONE` | `api-designer` | — |
| M1 | Python core enforcer | `DONE` | `python-pro` | M2, M4 |
| M2 | BackingStore binding + adapters | `DONE` | `python-pro` | M1, M4 |
| M3 | Python MCP server | `DONE` | `python-pro` | M4 |
| M4 | Discipline doc + worked examples | `DONE` | *interactive (no delegation)* | M1, M2, M3 |
| M5 | Python Claude Code adapter | `DONE` | `python-pro` | — |
| M6 | Language-neutral conformance harness | `DONE` | `test-automator` | — |
| M7 | End-to-end demos & integration | `DONE` | `test-automator` | — |
| M8 | Docs polish, placeholders, publication | `IN_PROGRESS` | `content-marketer` | — |

**Currently next action:** M7 is `DONE`. M8 is `READY`. Next: spawn `content-marketer` for M8.

---

## Phase M0 — Spec frozen

- **Status:** `DONE`
- **Prereqs:** none
- **Unblocks on DONE:** M1, M2, M4
- **Agent:** `api-designer`
- **Estimated effort:** 2–4 days
- **Reference:** [IMPLEMENTATION-PLAN.md §3 Milestone 0](./IMPLEMENTATION-PLAN.md#milestone-0--spec-frozen)

### M0 prompt

```text
You are bootstrapping the canonical, language-neutral spec for SOX Protocol — a runtime-agnostic peer-messaging protocol for LLM agents. The full design lives in docs/DESIGN.md and docs/CONTRACTS.md; the implementation plan is in docs/IMPLEMENTATION-PLAN.md.

Your task is Milestone 0 ("Spec frozen") from docs/IMPLEMENTATION-PLAN.md §3. Read that section plus docs/CONTRACTS.md before starting.

Concrete deliverables, all under spec/:

1. spec/VERSION — single line: "1.0".
2. spec/README.md — how spec/ is structured; how implementations consume it (codegen + templating + conformance per IMPLEMENTATION-PLAN.md §1.2).
3. spec/schemas/ — JSON Schema 2020-12 files. Each has $schema, $id, title, type, required, properties, additionalProperties: false where appropriate, and an examples block. Files:
   - event.schema.json (per CONTRACTS.md §3.1)
   - decision.schema.json (§3.3)
   - policy.schema.json (§4)
   - state.schema.json (§3.2)
   - message.schema.json (per the recv-output message-array element in §5.2)
   - tools/send.input.schema.json, send.output.schema.json (§5.1)
   - tools/recv.input.schema.json, recv.output.schema.json (§5.2)
   - tools/subscribe.input.schema.json, subscribe.output.schema.json (§5.3)
   - tools/list-channels.output.schema.json (§5.4)
4. spec/discipline/discipline.md — STRUCTURE ONLY at this milestone. Required H1 plus the eight required H2 anchors from CONTRACTS.md §2.1. Each section body is a TODO marker; full prose lands at M4. Use {{placeholder}} tokens in any structural examples.
5. spec/ports/backing-store.md — port behaviour contract in prose. Authoritative on: required methods (send, recv, subscribe, list_channels, watch); atomicity (CONTRACTS.md §6.1); delivery semantics (§6.2, at-least-once minimum); ordering (§6.3, per-channel send-time order); watch-loop semantics (yields each new matching message exactly once per subscribed agent). LANGUAGE-NEUTRAL — no Python ABCs, no Rust traits. Behaviour requirements only.
6. spec/ports/runtime-discipline-renderer.md — port contract per CONTRACTS.md §7.1.
7. spec/ports/runtime-enforcer-binding.md — port contract per CONTRACTS.md §7.2.
8. scripts/lint-discipline.sh — bash + standard tools. Validates: required H1+H2 anchors present in order; no concrete tool names appear outside {{placeholder}} forms.
9. .github/workflows/spec-lint.yml — runs ajv against every schema (JSON Schema 2020-12 mode); runs scripts/lint-discipline.sh; greps under spec/ for "packages/" and fails if found.

HARD CONSTRAINTS:
- Do not touch packages/. Do not write Python. Do not write the conformance harness (that's M6).
- Do not invent schema fields not described in CONTRACTS.md. If a field is ambiguous in the doc, file a TODO comment in the schema noting the ambiguity rather than guessing.

ACCEPTANCE:
- All schemas validate as JSON Schema 2020-12.
- spec-lint.yml passes locally (act -j spec-lint or equivalent) and on CI.
- spec/ contains no reference to packages/.

Report: a one-paragraph summary plus the file tree under spec/ and the first ~10 lines of each schema for verification.
```

### M0 exit criteria

- [ ] All schemas listed above exist and validate against JSON Schema 2020-12 (run `npx ajv` or equivalent locally).
- [ ] `spec/discipline/discipline.md` has the H1 + eight H2 anchors in the order from CONTRACTS.md §2.1.
- [ ] `spec/ports/*.md` exist with prose contracts, no language-specific code.
- [ ] `scripts/lint-discipline.sh` passes against the placeholder discipline.
- [ ] `.github/workflows/spec-lint.yml` passes in CI.
- [ ] No file under `spec/` matches `grep -r packages/ spec/`.

### M0 next state

Mark M0 = `DONE`. Promote M1, M2, M4 from `BLOCKED` to `READY`.

---

## Phase M1 — Python core enforcer

- **Status:** `DONE`
- **Prereqs:** M0
- **Unblocks on DONE:** M3, M5
- **Agent:** `python-pro`
- **Parallelisable with:** M2, M4
- **Estimated effort:** 2–3 days
- **Reference:** [IMPLEMENTATION-PLAN.md §3 Milestone 1](./IMPLEMENTATION-PLAN.md#milestone-1--python-core-enforcer)

### M1 prompt

```text
You are implementing Milestone 1 ("Python core enforcer") of SOX Protocol. Read docs/IMPLEMENTATION-PLAN.md §3 Milestone 1 for complete deliverables and acceptance, docs/DESIGN.md §4 for architectural context, and docs/CONTRACTS.md §3 and §4 for Event/Decision/Policy/State semantics. The cadence-enforcer state machine is in CONTRACTS.md §3.4 — implement that flowchart literally.

Phase M0 (spec frozen) must be complete. Verify by checking that spec/schemas/{event,decision,policy,state}.schema.json all exist.

Concrete tasks:

1. Bootstrap packages/python/ with pyproject.toml targeting Python 3.11+. Use src/ layout (src/sox_protocol/...). Dependencies: aiosqlite, pydantic v2 (for runtime validation against spec schemas).
2. Generate Python types from spec/schemas/ using datamodel-code-generator. Output to packages/python/src/sox_protocol/core/enforcer/events.py with a header comment "GENERATED FROM spec/schemas/ — DO NOT EDIT BY HAND". Add a Make target `make codegen` that regenerates them.
3. packages/python/src/sox_protocol/core/enforcer/policy.py — Policy dataclass per spec/schemas/policy.schema.json with the defaults from docs/CONTRACTS.md §4 (reminder_threshold_tool_calls=5, reminder_threshold_turns=3, force_drain_on_stop=True, send_followed_by_idle_turns=3, suspect_send_and_wait=True).
4. packages/python/src/sox_protocol/core/enforcer/state.py — async SQLite-backed read-modify-write counters per spec/schemas/state.schema.json. State persisted at ${SOX_STATE_DIR}/state.db (default ~/.sox/state.db). Concurrent-safe (WAL mode).
5. packages/python/src/sox_protocol/core/enforcer/decide.py — pure function: def decide(event: Event, state: State, policy: Policy) -> Decision. Implement the flowchart in CONTRACTS.md §3.4: tool_used (recv resets counter; otherwise increment + threshold check), channel_send (record + send-and-stall detection), turn_started (increment turns + threshold), stop_requested (force-drain check). No I/O in decide() itself; state mutation lives in state.py.
6. packages/python/tests/unit/test_decide.py — exhaustive table-driven tests using pytest.mark.parametrize. Cover every branch in the flowchart, plus boundary conditions. Aim 100% line coverage on decide.py.
7. Set up import-linter with a rule: packages/python/src/sox_protocol/core/ MUST NOT import from packages/python/src/sox_protocol/adapters/. Add to packages/python/pyproject.toml under [tool.importlinter] and wire into CI (extend or add packages/python/.github/workflows/python-ci.yml).

HARD CONSTRAINTS:
- Do NOT implement the MCP server (M3), BackingStore adapters (M2), or any runtime adapter (M5).
- Do NOT modify spec/.
- core/enforcer/decide.py MUST be pure: no file I/O, no network, no clock reads. Pass the clock as part of Event.timestamp.

ACCEPTANCE:
- 100% line coverage on decide.py per pytest --cov.
- Test matrix covers: cold-start, tool-call-threshold-crossed, stop-without-drain, send-and-stall, recv resets counter, turn-threshold-crossed.
- `mypy --strict packages/python/src/sox_protocol/core/` passes.
- Import-linter green.

Report: pytest output + coverage summary + tree of files added under packages/python/.
```

### M1 exit criteria

- [ ] `packages/python/pyproject.toml` exists with the right deps and tool config.
- [ ] `events.py` is generated from `spec/schemas/`; regen via `make codegen` works.
- [ ] `decide.py` has 100% line coverage.
- [ ] `mypy --strict` passes on `core/`.
- [ ] Import-linter rule enforced in CI.
- [ ] (Optional review gate: `code-reviewer` pass.)

### M1 next state

Mark M1 = `DONE`. If M2 was running in parallel and is also `DONE`, promote M3 to `READY`.

---

## Phase M2 — Python BackingStore binding + reference adapters

- **Status:** `DONE`
- **Prereqs:** M0
- **Unblocks on DONE:** M3
- **Agent:** `python-pro`
- **Parallelisable with:** M1, M4
- **Estimated effort:** 2–3 days
- **Reference:** [IMPLEMENTATION-PLAN.md §3 Milestone 2](./IMPLEMENTATION-PLAN.md#milestone-2--python-backingstore-port-binding--reference-adapters-sqlite-filesystem-memory)

### M2 prompt

```text
You are implementing Milestone 2 ("Python BackingStore port binding + reference adapters") of SOX Protocol. Read docs/IMPLEMENTATION-PLAN.md §3 Milestone 2 for complete deliverables; docs/CONTRACTS.md §6 for the port semantics; spec/ports/backing-store.md (canonical) for behaviour requirements; docs/DESIGN.md §4 for architectural context.

Phase M0 must be complete. The Python package skeleton from M1 may already exist (parallelisable with M1).

Concrete tasks:

1. packages/python/src/sox_protocol/core/ports/backing_store.py — abstract base class binding the BackingStore port. Methods (all async): send, recv, subscribe, list_channels, watch (AsyncIterator). The ABC must NOT introduce semantics beyond what spec/ports/backing-store.md requires. Each method's docstring cites the relevant spec section.
2. packages/python/src/sox_protocol/adapters/backing_stores/sqlite/store.py — async SQLite implementation using aiosqlite, WAL mode. Schema in adapters/backing_stores/sqlite/schema.sql per IMPLEMENTATION-PLAN.md §3 Milestone 2 (messages and subscriptions tables).
3. packages/python/src/sox_protocol/adapters/backing_stores/filesystem/store.py — directory-per-channel implementation; file-per-message; uses watchdog (or asyncio + inotify on Linux) for the watch() loop.
4. packages/python/src/sox_protocol/adapters/backing_stores/memory/store.py — pure in-memory implementation for tests.
5. packages/python/tests/adapters/backing_stores/test_port_contract.py — parametrised port-binding tests. Use pytest.mark.parametrize over (SqliteStore, FilesystemStore, MemoryStore). Cover: round-trip; concurrent writers (10 senders, no loss); subscription matching including glob (ticket:ENGI-* matches ticket:ENGI-0042 but not project:foo); delivery tracking (recv'd messages not redelivered to same agent); per-channel send-time ordering; watch-loop yields exactly once per subscribed agent.
6. packages/python/tests/adapters/backing_stores/test_sqlite_specific.py — WAL-mode behaviour, vacuum, schema-migration smoke (apply schema twice = idempotent).
7. packages/python/tests/adapters/backing_stores/test_filesystem_specific.py — fswatch behaviour, directory-locking edge cases, file naming collision resistance.

HARD CONSTRAINTS:
- Do NOT implement the MCP server (M3), the cadence enforcer (M1), or any runtime adapter (M5).
- The ABC at core/ports/backing_store.py MUST NOT import from adapters/. Confirm via the import-linter rule from M1.
- Do NOT modify spec/.

ACCEPTANCE:
- test_port_contract.py passes against all three reference adapters identically.
- Stress test: 10 concurrent writers + 10 concurrent readers on SqliteStore; 1000 messages; no loss, no duplication, ordering preserved per channel.
- mypy --strict passes on core/ports/ and on each adapter.
- Import-linter green.

Report: pytest output for the parametrised conformance + per-backend tests; tree of files added.
```

### M2 exit criteria

- [ ] `BackingStore` ABC exists at the spec'd path.
- [ ] All three reference adapters pass the parametrised port-contract tests.
- [ ] SQLite stress test passes.
- [ ] Filesystem watch-loop tests pass on Linux + macOS.
- [ ] (Optional review gate: `code-reviewer` pass.)

### M2 next state

Mark M2 = `DONE`. If M1 also `DONE`, promote M3 to `READY`.

---

## Phase M3 — Python MCP server

- **Status:** `DONE`
- **Prereqs:** M1, M2
- **Unblocks on DONE:** M5, M6
- **Agent:** `python-pro`
- **Parallelisable with:** M4
- **Estimated effort:** 3–5 days
- **Reference:** [IMPLEMENTATION-PLAN.md §3 Milestone 3](./IMPLEMENTATION-PLAN.md#milestone-3--python-mcp-server)

### M3 prompt

```text
You are implementing Milestone 3 ("Python MCP server") of SOX Protocol. Read docs/IMPLEMENTATION-PLAN.md §3 Milestone 3 for complete deliverables; docs/CONTRACTS.md §5 for the four tool contracts; docs/DESIGN.md §5.1 for the design rationale (push at the network layer, pull at the LLM layer). Per spec/schemas/tools/, validate every tool input/output against the JSON Schema files.

Phase M1 (enforcer) and M2 (BackingStore + adapters) must both be DONE.

Concrete tasks:

1. packages/python/src/sox_protocol/core/mcp_server/server.py — FastMCP-based server. Reads SOX_BACKING_STORE env var (sqlite://path / file://path / memory://). Reads SOX_AGENT_ID. Validates tool input/output against spec/schemas/tools/*.schema.json at startup (fail-fast on schema drift between code and spec).
2. packages/python/src/sox_protocol/core/mcp_server/listener.py — asyncio.create_task at startup. Subscribes to BackingStore.watch() for the agent's mailbox. Buffers messages in an asyncio.Queue. The listener is the push-receive layer; it must not block tool calls.
3. packages/python/src/sox_protocol/core/mcp_server/tools.py — the four MCP tools registered with FastMCP:
   - channels__send: per CONTRACTS.md §5.1
   - channels__recv: per §5.2 (drains the local buffer, returns immediately even if empty; non-blocking)
   - channels__subscribe: per §5.3
   - channels__list_channels: per §5.4 (must include protocol_version: "1.0")
4. Both stdio and HTTP transports supported (FastMCP gives both); default to stdio. HTTP transport selection via SOX_MCP_TRANSPORT=http.
5. packages/python/tests/integration/test_mcp_server_e2e.py — spawns the server in a subprocess, connects with an MCP client (FastMCP's test client or mcp-python-sdk). Scenarios:
   - Single agent: send → recv round-trip with the same MCP server.
   - Two MCP server instances on one shared SQLite store: agent A on server-1 sends, agent B on server-2 receives.
   - Listener buffering: produce 100 messages directly into the SQLite store (bypassing send) before any recv call; then call recv; assert all 100 returned.
   - Schema validation: tool outputs validate against spec/schemas/tools/*.output.schema.json (use ajv or jsonschema python lib).

HARD CONSTRAINTS:
- channels__recv MUST be non-blocking. timeout=0 semantics. If no messages, return {"messages": [], "drained_at": <now>}.
- The listener MUST NOT lose messages while no recv is pending. Buffer is unbounded by default; document the memory implication.
- Do NOT implement the runtime adapter (M5) or the conformance harness (M6).

ACCEPTANCE:
- All four integration scenarios pass.
- Two-server fan-out test passes.
- Listener-buffering test passes (100 messages buffered, all returned on first recv).
- mypy --strict passes on core/mcp_server/.

Report: pytest output for integration; tree of files added.
```

### M3 exit criteria

- [ ] All four MCP tools registered and functional.
- [ ] Listener push-receive working; bench-test buffers ≥100 messages.
- [ ] Two-server-one-store fan-out works.
- [ ] Tool outputs validate against `spec/schemas/tools/`.
- [ ] (Optional review gate: `code-reviewer` pass.)

### M3 next state

Mark M3 = `DONE`. Promote M5, M6 to `READY`.

---

## Phase M4 — Discipline document and worked examples

- **Status:** `DONE`
- **Prereqs:** M0
- **Unblocks on DONE:** M5 (a runtime adapter renders the discipline)
- **Agent:** *no delegation — interactive with Claude directly*
- **Parallelisable with:** M1, M2, M3
- **Estimated effort:** 2–4 days (iteration-dependent)
- **Reference:** [IMPLEMENTATION-PLAN.md §3 Milestone 4](./IMPLEMENTATION-PLAN.md#milestone-4--discipline-document-and-worked-examples-in-spec)

### Why no delegation

The discipline is a *prompt-engineering artefact*. It tells an LLM agent how to use SOX channels effectively — when to send, how to drain, how to reconcile late answers. It is the artefact most likely to need iteration based on how a real model behaves under it. None of the available agents specialise in prompt engineering; delegation would produce plausible markdown that fails on contact with real agent runs. Drive this interactively with Claude in your editor session, iterating against actual agent behaviour from the M5 demo.

### Starter prompt (use interactively, not via the Agent tool)

```text
I'm authoring spec/discipline/discipline.md for SOX Protocol — the canonical opinionated discipline document loaded by every runtime adapter as a Claude Code skill (or equivalent). The structure is fixed by docs/CONTRACTS.md §2.1; only the body content is mine to write.

Required H2 anchors, in this order:
- ## When to send
- ## How to send
- ## Polling cadence
- ## The send-and-continue pattern
- ## The speculative-then-reconcile recipe
- ## Anti-patterns
- ## What not to use channels for

Constraints:
- Use {{send_tool}}, {{recv_tool}}, {{subscribe_tool}}, {{list_tool}} placeholders — never concrete tool names.
- Audience is an LLM agent reading this skill mid-task. Voice: imperative, second-person, action-oriented.
- Each section ≤ ~150 words. Worked examples go in spec/discipline/examples/, not inline.
- The "speculative-then-reconcile" section is the protocol's distinctive contribution; spend the most care here. The recipe must cover: recognise a candidate ambiguity; record the assumption; send; continue under best-guess; drain at next decision; on reply: confirm or revise. The "revise" path must address irreversibility — if work has committed, surface the rollback question rather than papering over it.

Also produce three worked examples in spec/discipline/examples/:
- send-and-continue.md — full T=1/T=4/T=20 narrative.
- reconciliation.md — late reply contradicts best-guess; documented revise-and-roll-forward.
- group-broadcast.md — status update to ticket channel; multiple readers; no reply expected.

Process I want to follow with you:
1. Draft each section. I'll critique.
2. Once happy, run a fake agent: I'll paste a synthetic in-progress task with an ambiguity; you respond as if you'd loaded the skill and were following its discipline. We iterate until the behaviour reads right.
3. Adjust the discipline based on what I see.

Start with "When to send" plus "Polling cadence" — those frame the rest.
```

### M4 exit criteria

- [ ] All eight required H2 sections (plus H1) populated in `spec/discipline/discipline.md`.
- [ ] Three worked examples in `spec/discipline/examples/`.
- [ ] `scripts/lint-discipline.sh` from M0 passes.
- [ ] Synthetic-agent walkthrough (interactive verification): ambiguity scenario → expected behaviour → matches the discipline's recipe.

### M4 next state

Mark M4 = `DONE`. Does not by itself unblock anything new (M5 only requires M3 + M4); but if M3 is also `DONE`, promote M5 to `READY`.

---

## Phase M5 — Python Claude Code runtime adapter

- **Status:** `DONE`
- **Prereqs:** M3, M4
- **Unblocks on DONE:** M7
- **Agent:** `python-pro`
- **Estimated effort:** 3–5 days
- **Reference:** [IMPLEMENTATION-PLAN.md §3 Milestone 5](./IMPLEMENTATION-PLAN.md#milestone-5--python-claude-code-runtime-adapter)

### M5 prompt

```text
You are implementing Milestone 5 ("Python Claude Code runtime adapter") of SOX Protocol. Read docs/IMPLEMENTATION-PLAN.md §3 Milestone 5 for complete deliverables, docs/CONTRACTS.md §7.1 and §7.2 for the runtime-adapter port contracts (DisciplineRenderer + EnforcerBinding), and docs/USAGE.md for the user-facing install behaviour.

Phases M3 (MCP server) and M4 (discipline doc + examples) must be DONE.

Concrete tasks:

1. packages/python/src/sox_protocol/adapters/runtimes/claude_code/install.py — `python -m sox_protocol.adapters.runtimes.claude_code install` invocation. Flow:
   a. Read spec/discipline/discipline.md (bundled into the wheel via MANIFEST.in — set this up in pyproject.toml).
   b. Render into adapters/runtimes/claude_code/skill/SKILL.md.template with frontmatter:
      - name: inter-agent-channels
      - description: per CONTRACTS.md §2 (load-when-blocked-or-broadcasting language)
   c. Substitute placeholders: {{send_tool}} → mcp__sox__channels__send (and the four others).
   d. Write to <project>/.claude/skills/inter-agent-channels/SKILL.md.
   e. Write hook scripts to <project>/tools/sox-hooks/ (post_tool_use.sh, stop.sh).
   f. Update <project>/.claude/settings.json: register hooks (PostToolUse, Stop, SubagentStop) + register the SOX MCP server (uses .sox/messages.db SQLite store by default).
   g. Insert/append the bootstrap snippet into target agents' system prompts. Detect agents via .claude/agents/*.md; skip those that already contain the bootstrap line.
   h. Idempotent: running install twice MUST NOT duplicate or break.

2. packages/python/src/sox_protocol/adapters/runtimes/claude_code/hooks/post_tool_use.sh — bash. Reads JSON from stdin (Claude Code hook input). Invokes `python -m sox_protocol.enforcer cli` passing the event. Prints any returned Decision as Claude Code-shaped JSON ({"hookSpecificOutput": {"additionalContext": "..."}} for inject; {"decision": "block", "reason": "..."} for block).

3. packages/python/src/sox_protocol/adapters/runtimes/claude_code/hooks/stop.sh — same shape; invoked on Stop and SubagentStop. Per CONTRACTS.md §3.5, returns block decision when force_drain_on_stop is true and inbox is non-empty.

4. packages/python/src/sox_protocol/adapters/runtimes/claude_code/skill/SKILL.md.template — frontmatter + body placeholder. The body is filled at install time with the rendered discipline.

5. packages/python/src/sox_protocol/cli.py — `python -m sox_protocol verify` command that reports config health: backing store reachable, MCP server registered in .claude/settings.json, hooks installed, skill present, all four MCP tools surfaced.

6. packages/python/tests/adapters/runtimes/test_claude_code_install.py — uses a tmp_path fixture to simulate a fresh Claude Code project. Run install. Assert: SKILL.md exists with proper frontmatter and substituted placeholders; hooks exist and are executable; settings.json updated correctly; running install again is idempotent.

HARD CONSTRAINTS:
- Idempotent install. No duplication, no breakage on re-run.
- Bootstrap line is exactly ONE line per the discipline-quote in CONTRACTS.md §2.
- Hooks must NOT crash the agent on enforcer errors; on exception, log to ${SOX_LOG_DIR}/decisions.jsonl and emit noop output.
- Do NOT modify spec/.

ACCEPTANCE:
- test_claude_code_install.py passes including the idempotent re-install assertion.
- Live test: in a real Claude Code project fixture, two subagents send and receive a message via the installed adapter (this proves the loop end-to-end before M7's full demo).

Report: pytest output; the rendered SKILL.md from a test install; the updated settings.json delta from a test install.
```

### M5 exit criteria

- [ ] `install.py` is idempotent.
- [ ] Hook scripts return correct Claude Code JSON shapes for `inject` / `block` / `noop`.
- [ ] `verify` command reports correctly on a healthy install.
- [ ] Live two-subagent message exchange works in the test fixture.
- [ ] (Optional review gate: `code-reviewer` pass.)

### M5 next state

Mark M5 = `DONE`. Promote M7 to `READY`.

---

## Phase M6 — Language-neutral conformance harness

- **Status:** `DONE`
- **Prereqs:** M3
- **Unblocks on DONE:** none directly (independent track; gates publication at M8)
- **Agent:** `test-automator`
- **Estimated effort:** 3–5 days
- **Reference:** [IMPLEMENTATION-PLAN.md §3 Milestone 6](./IMPLEMENTATION-PLAN.md#milestone-6--language-neutral-conformance-harness-in-spec)

### M6 prompt

```text
You are implementing Milestone 6 ("Language-neutral conformance harness") of SOX Protocol. Read docs/IMPLEMENTATION-PLAN.md §3 Milestone 6, docs/CONTRACTS.md §10 (conformance-suite shape and scenario coverage), and docs/DESIGN.md (architecture context) before starting. The conformance suite is the verification authority for SOX-compliance — the artefact future TS / Rust ports gate on.

Phase M3 must be DONE so there is a Python implementation to run scenarios against.

Concrete tasks:

1. spec/conformance/README.md — explains how operators run the suite against any implementation; documents the IMPLEMENTATION_IMAGE env var contract.

2. spec/conformance/docker-compose.yml — Compose file. Two services:
   - mcp-server-under-test: image from $IMPLEMENTATION_IMAGE; exposes MCP HTTP transport on a fixed port; mounts a tmpfs volume for backing-store state.
   - mcp-test-client: alpine + jq + a generic MCP client (e.g., `mcp` CLI or a tiny custom Go/Rust binary). Runs spec/conformance/runner/run.sh against the server.

3. spec/conformance/scenarios/ — JSON files per CONTRACTS.md §10.2. Each scenario:
   {
     "name": "...",
     "env": {...},
     "setup": [...] // optional pre-test MCP calls
     "steps": [
       {"tool": "channels__send", "args": {...}, "expect": {...}},
       ...
     ],
     "assertions": [
       {"type": "no_loss", "channel": "...", "min": 100},
       {"type": "ordering", "channel": "...", "by": "sent_at"},
       ...
     ]
   }
   Required scenarios (per CONTRACTS.md §10.2):
   - 01-send-and-recv.json
   - 02-group-broadcast.json
   - 03-subscription-glob.json
   - 04-concurrent-writers.json
   - 05-per-channel-ordering.json
   - 06-listener-buffering.json
   - 07-recv-atomicity.json

4. spec/conformance/runner/run.sh — bash + jq. Reads scenarios in lex order. For each: spins up server (compose up -d); waits for healthcheck; executes steps via MCP client; validates outputs against spec/schemas/ via ajv; checks assertions; reports per-scenario pass/fail; tears down (compose down -v). Exit non-zero on any failure.

5. packages/python/tests/conformance/run_python_impl.py — thin wrapper. Builds packages/python/ into a Docker image (Dockerfile under packages/python/), sets IMPLEMENTATION_IMAGE, invokes spec/conformance/runner/run.sh.

6. .github/workflows/python-ci.yml — extend (or create) so that conformance is run on every PR.

7. .github/workflows/conformance-badge.yml — generates per-package conformance badges (shields.io endpoint JSON committed to a gh-pages branch, or similar). At v0, only packages/python/ has a passing badge.

HARD CONSTRAINTS:
- spec/conformance/ MUST NOT import from packages/. Re-validate via spec-lint.yml from M0.
- The harness runs against the MCP wire protocol only — no language-specific calls.
- Scenarios MUST NOT bake in Python idioms (e.g., snake_case-vs-camelCase-only assumptions; numerical precision specific to Python floats).

ACCEPTANCE:
- All seven scenarios pass against the Python reference impl.
- Running run.sh against an intentionally-broken server (e.g., a stub that returns empty results) reports correct per-scenario failures.
- python-ci.yml runs the conformance suite on every PR.
- spec-lint.yml continues to pass (no packages/ references in spec/conformance/).

Report: per-scenario pass/fail output from a clean run; tree of files added under spec/conformance/.
```

### M6 exit criteria

- [ ] All seven required scenarios exist and pass against `packages/python/`.
- [ ] Negative test (intentionally broken server) reports correct failures.
- [ ] CI badge workflow generates a passing badge for `packages/python/`.
- [ ] No `packages/` references under `spec/conformance/`.
- [ ] (Optional review gate: `code-reviewer` pass on the harness scenarios for Python-ism leakage.)

### M6 next state

Mark M6 = `DONE`. M6 is independent; it does not directly unblock any phase, but it gates the v0.0.1 publication at M8 (publication requires the conformance badge).

---

## Phase M7 — End-to-end demos & integration tests

- **Status:** `DONE`
- **Prereqs:** M5
- **Unblocks on DONE:** M8
- **Agent:** `test-automator`
- **Estimated effort:** 2–4 days
- **Reference:** [IMPLEMENTATION-PLAN.md §3 Milestone 7](./IMPLEMENTATION-PLAN.md#milestone-7--end-to-end-demo--integration-tests)

### M7 prompt

```text
You are implementing Milestone 7 ("End-to-end demos & integration tests") of SOX Protocol. Read docs/IMPLEMENTATION-PLAN.md §3 Milestone 7, docs/USAGE.md §5 (the four primary use cases), and the worked examples in spec/discipline/examples/ produced at M4.

Phase M5 (Python Claude Code adapter) must be DONE.

Concrete tasks:

1. examples/two-agent-clarification/ — runnable Claude Code project demonstrating the speculative-then-reconcile pattern. Two subagents collaborating on a shared task (suggested: implementing a small REST endpoint where agent A is implementer, agent B is API-design reviewer). A detects an ambiguity, posts a clarification request to ticket:DEMO-001, continues with best-guess implementation, drains inbox at next decision, integrates B's reply. Folder contains:
   - README.md with run instructions (`make demo`).
   - .claude/agents/implementer.md and .claude/agents/reviewer.md with the bootstrap line.
   - .claude/settings.json (committed copy of what `install` produces — for reproducibility).
   - tasks/DEMO-001.md with the deliberately ambiguous task description.

2. examples/group-broadcast/ — three subagents on ticket:DEMO-002. One broadcasts a status update; the others acknowledge in their working state without replying. Same folder structure.

3. packages/python/tests/integration/test_two_agent_exchange.py — automated CI version of demo 1. Use Claude Code's test mode or a mock-Claude harness if needed; the test must be runnable without a real Claude API key (use recorded responses if necessary; document the recording approach).

4. Makefile targets at the repo root:
   - `make demo` — runs examples/two-agent-clarification/ end-to-end.
   - `make test-integration` — runs the integration test suite in CI mode.

5. Update docs/USAGE.md if the demos surface UX issues that warrant troubleshooting entries.

HARD CONSTRAINTS:
- The integration test MUST be reproducible in CI without network access to live LLM APIs (use recorded fixtures or stubbed Claude responses).
- Demos MUST be self-contained — no manual setup beyond `make demo`.

ACCEPTANCE:
- `make demo` succeeds on a fresh checkout (Linux + macOS, Python 3.11 + 3.12).
- `make test-integration` passes in CI.
- Running each demo manually produces the documented behaviour (clarification → continue → reconcile; broadcast → acknowledge).

Report: demo run transcripts; pytest output; any USAGE.md additions.
```

### M7 exit criteria

- [ ] Both demos run reproducibly via `make demo`.
- [ ] Integration tests pass in CI on Linux + macOS, Python 3.11 + 3.12.
- [ ] Demo behaviour matches the discipline's documented patterns (verify against `spec/discipline/examples/`).
- [ ] (Optional review gate: `qa-expert` audit before declaring DONE.)

### M7 next state

Mark M7 = `DONE`. Promote M8 to `READY`.

---

## Phase M8 — Documentation polish, placeholder packages, publication

- **Status:** `IN_PROGRESS`
- **Prereqs:** M6, M7
- **Unblocks on DONE:** v0.0.1 release
- **Agent:** `content-marketer`
- **Estimated effort:** 2–3 days
- **Reference:** [IMPLEMENTATION-PLAN.md §3 Milestone 8](./IMPLEMENTATION-PLAN.md#milestone-8--documentation-polish-placeholder-packages--v0-publication)

### M8 prompt

```text
You are implementing Milestone 8 ("Documentation polish, placeholder packages, & v0 publication") of SOX Protocol. Read docs/IMPLEMENTATION-PLAN.md §3 Milestone 8, docs/README.md (the design-docs entry point), and docs/DESIGN.md §1 (the gap statement that motivates publication).

Phases M6 and M7 must be DONE.

Audience for the publication content: open-source developers building agentic-AI systems, plus prospective contributors who might write the TypeScript or Rust ports.

Concrete deliverables:

1. README.md at repo root — the public face of the project. Sections:
   - One-paragraph hook (the gap from DESIGN §1 and what SOX adds).
   - Quickstart: `pip install sox-protocol; python -m sox_protocol.adapters.runtimes.claude_code install` plus a 5-line example.
   - Repo navigation: spec/, packages/, docs/, examples/.
   - Conformance bar callout for non-Python ports with link to spec/conformance/.
   - Status: v0.0.1; SOX v1.0-compliant Python implementation; TS/Rust open to contributions.
   - Links to docs/, spec/conformance/, FUTURE.md, CONTRIBUTING.md.

2. CONTRIBUTING.md at repo root — explains:
   - Spec changes: PR against spec/, must pass spec-lint.yml, must update at least one implementation OR document the breakage explicitly.
   - Language ports: open issue claiming the package; mirror packages/python/ layout; merge gates on conformance suite.
   - Code changes within an implementation: standard PR flow with the language's CI green.

3. packages/typescript/README.md — placeholder. Sections:
   - Status: not implemented; open to contributions.
   - Conformance bar: pass spec/conformance/scenarios/.
   - Suggested architecture: mirror packages/python/ (core/{enforcer, mcp_server, ports} + adapters/{runtimes, backing_stores}).
   - Suggested stack: TypeScript 5+; @modelcontextprotocol/sdk; better-sqlite3 (default backing store).
   - Contribution process: open an issue first to claim the package.
   - Conformance-badge link will appear here once it passes.

4. packages/rust/README.md — same shape as packages/typescript/README.md, suggested stack: rmcp (Rust MCP SDK); rusqlite (default backing store); tokio (async runtime).

5. CHANGELOG.md — v0.0.1 entry covering: spec frozen at 1.0; Python reference impl; SQLite/filesystem/memory backing-store adapters; Claude Code runtime adapter; conformance harness with 7 scenarios.

6. A 1500–2500-word technical writeup at docs/blog/v0-launch.md (or similar) framing:
   - The gap (turn-taking schedulers, handoff frameworks, actor-model frameworks without packaged discipline).
   - The thesis (peer messaging with the speculative-then-reconcile pattern as a first-class artefact).
   - The shape (spec + reference impl + conformance suite).
   - The invitation (ports welcomed; conformance bar fixed).
   Cite the relevant prior work from docs/RESEARCH.md.

7. Review existing docs in docs/ for any drift introduced by implementation discoveries. Update USAGE.md, FUTURE.md, GLOSSARY.md as needed. Don't rewrite — just patch.

8. Tag v0.0.1.

HARD CONSTRAINTS:
- Don't oversell. The protocol is genuinely useful; the discipline is genuinely opinionated; the conformance harness is genuinely the verification authority. Stay specific; avoid generic AI-tooling-marketing language.
- Don't claim TS/Rust ports exist. They don't.
- Don't change spec/ except for typo fixes.

ACCEPTANCE:
- A reader unfamiliar with the project can install, run a demo, and write a custom send/receive in under 30 minutes following only the README and docs/USAGE.md.
- Placeholder READMEs are sufficient for a TS or Rust developer to start a port without further guidance from the maintainer.
- All docs lint-clean (markdownlint).
- v0.0.1 git tag created; PyPI release pushed (or CHANGELOG noted as ready-for-push if PyPI account isn't yet set up).

Report: list of files added/modified; the README and CONTRIBUTING.md in full; a one-paragraph excerpt from the blog post.
```

### M8 exit criteria

- [ ] Top-level `README.md` and `CONTRIBUTING.md` exist and are accurate.
- [ ] `packages/typescript/README.md` and `packages/rust/README.md` document the conformance bar and architecture.
- [ ] `CHANGELOG.md` v0.0.1 entry committed.
- [ ] Blog post drafted.
- [ ] Markdownlint clean across all docs.
- [ ] `v0.0.1` git tag created.

### M8 next state

v0.0.1 published. Move forward to v0.1 work tracked in [FUTURE.md](./FUTURE.md). Reset this state machine for v0.1 milestones, or fork a new `BUILD-STATE-v0.1.md`.

---

## Quick reference: next-action lookup

| You just finished | Next phase to start |
|---|---|
| (nothing yet) | M0 |
| M0 | M1, M2, and M4 (parallel) |
| M1 only | (wait on M2) |
| M2 only | (wait on M1) |
| M1 + M2 | M3 |
| M3 | M5, M6 (parallel) |
| M4 | (wait on M3) |
| M3 + M4 | M5 |
| M5 | M7 |
| M6 + M7 | M8 |
| M8 | v0.0.1 published — reset state for v0.1 |

If at any point a phase fails its exit criteria, set its status to `IN_PROGRESS` and re-run the agent with feedback, *not* `BLOCKED`. `BLOCKED` is reserved for not-started-due-to-prereqs.
