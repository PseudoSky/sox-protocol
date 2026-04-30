# Phase template

A SOX-style phase file. One file per phase. Self-contained — an executor agent reads only this file plus the inputs it cites.

Filename convention: `phases/<NN>-<kebab-slug>.md` where `NN` is a zero-padded ordinal (`01`, `02`, …). Ordinal is for sort order only; dependencies are explicit in the `prereqs:` field.

The orchestrator reads `STATE.md` to pick the next phase, then loads only the chosen phase file. **This file is immutable once committed.** All mutable state lives in `STATE.md`.

## Phase boundary rule (important)

**A phase boundary is also an agent-handoff boundary.** Split phases when a different specialist takes over (e.g. `api-designer` for spec docs → `python-pro` for implementation → `test-automator` for harnesses → `content-marketer` for prose). Do NOT split phases on logical sub-step boundaries that the same specialist handles end-to-end — that forces context reload without any specialist transition and shrinks the agent's coherent reasoning window.

Reference: `docs/BUILD-STATE.md` — M0 (`api-designer` writes specs and schemas), M1–M3/M5 (`python-pro` writes Python), M4 (interactive prompt engineering, no delegation), M6/M7 (`test-automator` writes test harnesses and demos), M8 (`content-marketer` writes publication prose). Each phase is the chunk of work that fits in one specialist's hands.

Heuristics:
- One specialist, one phase. Multiple deliverables are fine if they're the same kind of thinking.
- If you find yourself naming the same `agent:` for two adjacent phases with no intervening artifact-handoff, collapse them.
- Optional review-gate phases (e.g. `code-reviewer` between `python-pro` impl and `test-automator` tests) are legitimate phase boundaries because the reviewer is a different specialist with a different goal.

---

```markdown
---
phase_id: <NN>-<kebab-slug>           # matches filename
title: <human title>
agent: <subagent_type for Agent tool> # e.g. python-pro, api-designer, test-automator
profile: <meta|spec|code-python|code-typescript|code-with-spec|planning|test-harness|docs|review|release>
estimated_effort: <e.g. 2 hours, 1 day>
prereqs: [<phase_id>, ...]            # phase_ids that must be DONE first; [] if none
unblocks: [<phase_id>, ...]           # phase_ids promoted from BLOCKED → READY when this completes
parallelizable_with: [<phase_id>, ...] # informational; orchestrator may choose to serialize
writes: [<glob>, ...]                 # directory/glob patterns this phase MAY write to. Used for parallel-dispatch conflict detection. MUST be broad enough to cover anything the agent or upstream planner might emit. See Authoring section below.
reads:  [<glob>, ...]                 # paths the executor reads. Informational; helps detect read-after-write hazards across parallel batches.
context_size: <small | medium | large> # rough hint to the orchestrator about model selection
---

# <NN> — <Title>

## Objective

One paragraph. What this phase accomplishes and why it sits where it does in the chain.

## Inputs

Files, artifacts, prior-phase outputs the executor must read before starting. Use absolute paths or paths relative to repo root. Cite specific sections where relevant ("docs/DESIGN.md §4").

- `<path>` — <why this is needed>
- `<path>` — <why this is needed>

## Prompt (verbatim — do not paraphrase when dispatching)

The orchestrator passes this block verbatim to the agent named in `agent:`. Do not edit, summarize, or "improve" it during dispatch.

```text
<the actual prompt to the agent>

<repeat the objective here in agent-facing terms>

<list every concrete deliverable>

<list every hard constraint>

<list the acceptance criteria the agent should self-check before reporting done>

<final instruction: report a one-paragraph summary plus list of files written>
```

## Exit criteria

Verifiable checks the orchestrator runs after the agent reports done. Each must be a concrete command or file-existence check, not a subjective judgment. The phase advances to DONE only if every check passes.

**Universal checks for this profile** are inherited from `.workflow/templates/UNIVERSAL-CONSTRAINTS.md`. The phase author MUST include the profile's required checks below (verbatim or adapted to the engagement's specific paths). Phase author MAY add engagement-specific checks; MAY NOT remove a universal check without justified exemption in the Notes section.

Universal (from profile):
- [ ] `<copy from UNIVERSAL-CONSTRAINTS.md for this profile>`
- [ ] `<copy from UNIVERSAL-CONSTRAINTS.md for this profile>`

Engagement-specific:
- [ ] `<concrete check>` — e.g. `test -f spec/protocol.md`
- [ ] `<concrete check>` — e.g. `cd packages/python && pytest tests/identity/ -q`

## On verification failure

Default behavior: mark phase REVIEW, commit, surface to user. Do not auto-advance.

Optional phase-specific recovery hints (e.g. "if `lint-imports` fails, the agent likely cross-imported from adapters into core — re-spawn with that feedback").

## Outputs

Files this phase produces. Used by downstream phases as inputs.

- `<path>` — <what it contains>
- `<path>` — <what it contains>

## Next state

When this phase reaches DONE, promote these phases from BLOCKED to READY in `STATE.md`:

- `<phase_id>`
- `<phase_id>`

If `unblocks: []`, this is a leaf phase.

## Notes

Free-form. Risks, caveats, links to ADRs, references to upstream specs. Agent does not need to read this section unless the prompt cites it.
```

---

## Why this format

- **Verbatim prompt block** — versioned artifact. Once a prompt produces working output, it shouldn't drift on re-dispatch.
- **Concrete exit criteria** — agent self-reports are not sufficient evidence. Orchestrator runs commands.
- **Explicit prereqs / unblocks** — dependency graph derivable from phase files alone, no central manifest needed beyond STATE.md.
- **Inputs section** — bounded reading surface. Agent loads only what it needs; context preserved.
- **Phase file is immutable** — re-running a phase loads the same prompt. State changes (status, attempt count) live in STATE.md only.

## Risk tier (computed from declared outputs)

A phase's risk tier is derived at dispatch time from output cardinality and profile (per `ORCHESTRATOR-CONTRACT.md §Completion check protocol`):

| Tier | Criteria |
|---|---|
| LOW | profile in {meta, review, planning, release}, OR ≤ 3 declared outputs in the `## Outputs` section |
| MEDIUM | profile in {docs, spec, test-harness, code-python, code-typescript} AND 4–8 declared outputs |
| HIGH | profile in {code-with-spec, code-python, code-typescript, test-harness, spec} AND ≥9 declared outputs |

Phase authors should be aware: HIGH-risk phases will have an extra dispatch envelope warning the agent to use incremental discipline and signal partial-completion if budget runs short. If a phase is consistently HIGH and consistently truncates across agent runs, that's evidence the phase prompt should be split during a deliberate phase-file authoring revision.

The author's responsibility: declare every output the agent will produce in `## Outputs` (plus the `writes:` envelope for parallelism). The orchestrator computes the risk tier from that declaration. Under-declaring outputs to game tier is self-defeating — the completion check will surface missing files and trigger resume.

## `writes:` is the envelope, not the prediction

`writes:` declares the **maximum surface** an agent could legitimately touch — the *envelope*. It is NOT a prediction of the specific files the agent will write. Phase files are immutable, so `writes:` must be set once at authoring time and cover everything that could happen at dispatch time.

For planner-gated phases (`code-with-spec`, etc.), the actual write surface is narrower than the envelope: the upstream planner produces a specific list. The orchestrator narrows at runtime via the reservations protocol (see ORCHESTRATOR-CONTRACT.md). The phase file never changes.

## Reservations protocol (planner phases only)

A planner phase (`profile: planning`) MUST end its agent return with a fenced reservations block listing the specific paths the downstream implementer will write to:

```
RESERVATIONS:
- <path>
- <path>
- <path>
END_RESERVATIONS
```

Rules:
- One path per line. Plain string. No globs (planner output is concrete).
- The list MUST be byte-identical to the set of paths in `implementation-plan.json#/files/*/path`. The orchestrator verifies this as part of the phase's exit criteria.
- Markers `RESERVATIONS:` and `END_RESERVATIONS` are exact strings on their own lines. Easy to extract with `sed -n '/^RESERVATIONS:$/,/^END_RESERVATIONS$/p'`.

The orchestrator persists the parsed list at `<plan_dir>/reservations/<downstream_phase_id>.json` and uses it to narrow the downstream phase's effective `writes:` at dispatch time, enabling more parallel co-scheduling.

If the planner CAN'T determine the file list (e.g. fixture-generation phase where the count is dynamic), it returns an empty reservations block:

```
RESERVATIONS:
END_RESERVATIONS
```

Empty reservations mean the orchestrator falls back to the declared envelope for parallel-gating — no narrowing.

## Authoring `writes:` and `reads:` (parallel-dispatch contract)

These fields drive the orchestrator's parallel-batch conflict gate. Get them wrong and parallel phases will trample each other; get them too narrow and the orchestrator over-reports conflicts.

**Use broad directory globs, not specific file lists.** Many phases (especially `code-with-spec`) only learn the exact files they'll write at planner runtime. Declare the *envelope* the agent could legitimately write within, not the specific files.

Examples:

```yaml
# A code-with-spec implementer phase whose specific files come from implementation-plan.json:
writes: ["packages/python/src/sox_protocol/core/identity/**", "packages/python/tests/identity/**"]

# A docs phase that touches the README and several docs files:
writes: ["README.md", "docs/why-sox.md", "docs/example.md", "docs/roadmap.md", "docs/launch/**"]

# A defensive-publication housekeeping phase that adds SPDX headers everywhere:
writes: ["LICENSE", "NOTICE", "README.md", "CONTRIBUTING.md", "docs/ip/**", "packages/**/*.py", "packages/**/*.ts", "spec/**/*.md"]
```

Rules:

1. **Be broad enough that anything the agent or upstream planner could emit is covered.** Better to over-declare and serialize unnecessarily than to under-declare and corrupt history.
2. **Use `**` liberally.** A phase that creates `packages/python/src/sox_protocol/foo/bar.py` and `packages/python/src/sox_protocol/foo/baz.py` and tests should declare `packages/python/src/sox_protocol/foo/**` and `packages/python/tests/foo/**`, not enumerate.
3. **Include shared hotspots explicitly.** `README.md`, `CONTRIBUTING.md`, `.github/workflows/*.yml`, `tools/conformance_runner.py` are conflict hotspots — list them by name when touched.
4. **STATE.md and the phase's own engagement directory are implicit.** The orchestrator owns mutations to `<plan_dir>/STATE.md` and `<plan_dir>/reviews/**`; phases don't need to declare these.
5. **`reads:` is informational.** A read-after-write hazard (phase A reads what phase B is writing) is a soft warning, not a hard block. Hard block is reserved for `writes:` ∩ `writes:` ≠ ∅.
