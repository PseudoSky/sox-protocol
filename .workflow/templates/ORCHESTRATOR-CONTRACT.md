# Orchestrator contract

What an orchestrator (Claude Code session reading an engagement's `STATE.md`) MUST do on every state transition. Lifted from `docs/BUILD-STATE.md` and generalized.

## Pre-flight (once per orchestrator session)

Before entering the main loop, verify:

1. **Working directory.** `git rev-parse --show-toplevel` ends in `sox-protocol`. If not, stop.
2. **Working tree clean.** `git status --porcelain` is empty. If not, stop and prompt user to commit/stash. The orchestrator commits after every transition; a dirty tree creates ambiguity about authorship.
3. **Tool probes.** Probe for `git`, `python3`, `pytest`, `mypy`, `npx ajv`, `lint-imports`, `jq`, plus any phase-specific tools the engagement's planned phases will need. Missing tools are not fatal until that phase runs; report what's missing in the preamble.
4. **Orchestrator-mode hook opt-out.** Set `SOX_ORCHESTRATOR_MODE=1` in the orchestrator's shell environment so SOX cadence-enforcer hooks don't re-inject inbox reminders during bash exit-criterion runs.

## Main loop (serial mode — default)

1. **Read STATE.md.** Pick the lowest-ordinal `READY` phase. If none and all DONE, declare success. If none but BLOCKED phases exist, that's an orphan-blockage bug; stop.
2. **Mark phase IN_PROGRESS** in STATE.md. Append transition row. Commit:
   ```
   chore(<slug>): <phase_id> in progress
   ```
3. **Load only the chosen phase file** (`phases/<phase_id>.md`). Do NOT load other phase files unless the chosen phase's `Inputs` section cites them.
4. **Dispatch the named agent** with the verbatim prompt block. Capture the agent's runtime ID for the commit trailer.
5. **Completion check (BEFORE running exit criteria).** Verify that every file the agent should have produced is on disk. See [Completion check protocol](#completion-check-protocol) below. If incomplete, resume the agent via SendMessage with the missing-output list. Only proceed to step 6 once completion is confirmed.
6. **On agent return, run every Exit Criteria checkbox via Bash.** Capture pass/fail.
7. **Branch:**
   - **All pass:** mark phase DONE, promote phases listed in `next state` from BLOCKED → READY, append transition, `git add -A`, commit:
     ```
     feat(<slug>:<phase_id>): <one-line summary>

     <bullet list of deliverables>

     Phase: <slug>/<phase_id>
     Agent: <subagent_type> (id: <runtime_agent_id>)
     Orchestrator: workflow-architect (or current orchestrator)
     Spec-version: <git-rev of spec/ at dispatch time>   # code phases only
     ```
   - **Any fail:** mark phase REVIEW, increment `attempts` in STATE.md, append transition, commit:
     ```
     chore(<slug>): <phase_id> failed verification

     Failed checks:
     - <checkbox text>
     - <checkbox text>

     Phase: <slug>/<phase_id>
     Agent: <subagent_type> (id: <runtime_agent_id>)
     ```
     Stop and surface the agent's report + failed-check output to the user. Do not advance.
8. **Loop.**

## Parallel mode (opt-in)

The orchestrator MAY dispatch multiple `READY` phases in one tool-call batch when their `writes:` globs are pairwise disjoint. This is the primary parallelism mechanism — expected to deliver most of the wall-clock speedup with minimal infrastructure.

### Batch-selection algorithm

1. Read STATE.md from every engagement under `.workflow/plans/`.
2. Collect every phase whose `prereqs:` are satisfied (status `READY`).
3. Build a candidate set ordered by (a) engagement priority if known, (b) lowest-ordinal-within-engagement, (c) `critical-path` engagements first (engagements whose `unblocks:` chains lead to launch-blocking work).
4. Greedily admit candidates into the batch:
   - For each candidate phase P, compute the union of `writes:` globs across all already-admitted phases.
   - If P.writes intersects that union (using glob expansion: `**` matches any depth, `*` matches one segment), reject P from this batch and leave it for a future iteration.
   - If P.reads intersects another admitted phase's writes, **soft warn** in the preamble (read-after-write hazard) but admit anyway — the agent reads at dispatch time, before the writer has committed.
   - Stop admitting once the batch reaches the **max-parallel cap** (default 4; configurable via `WORKFLOW_MAX_PARALLEL` env or per-engagement frontmatter).
5. If the batch contains < 2 candidates, fall back to serial mode for this iteration.

### Glob-intersection rule

Two glob sets `A` and `B` *intersect* iff there exists at least one path matched by both. The orchestrator approximates this using directory-prefix comparison plus `**` expansion. If unsure, treat as intersection (fail-safe toward serialization).

Examples:

| A | B | Intersect? |
|---|---|---|
| `packages/python/src/sox_protocol/core/identity/**` | `packages/python/src/sox_protocol/core/middleware/**` | No |
| `packages/python/src/sox_protocol/cli/**` | `packages/python/src/sox_protocol/cli/**` | Yes (block) |
| `README.md` | `docs/launch/**` | No |
| `README.md` | `README.md` | Yes (block) |
| `packages/**/*.py` | `packages/python/tests/identity/**` | Yes (block — first glob covers second) |
| `tools/conformance_runner.py` | `tools/conformance_runner_ts/**` | No |

### Parallel-mode dispatch

1. **Mark every batch member IN_PROGRESS** in their respective STATE.md files. Commit one merge-style commit:
   ```
   chore(orchestrator): begin parallel batch [<slug1>:<phase1>, <slug2>:<phase2>, ...]
   ```
2. **Dispatch all batch members in a single assistant message.** Issue one `Agent` tool call per phase in the same message — Claude Code runs them concurrently. Pass `isolation: "worktree"` only if the batch is operator-flagged or includes a HIGH-tier phase (see §Worktree isolation policy below). Otherwise share the working tree (default).
3. **Await all returns.** Do not advance until every dispatched phase has reported.
4. **Completion check** per phase (see §Completion check protocol). Resume any agent whose declared outputs are missing. Cap at 5 resumes per phase before treating that phase as REVIEW.
5. **Merge resolution** — see §Merge resolution below. If non-worktree: integrity validation. If worktree: sequential merge. Halt batch on conflict.
6. **Run all exit criteria sequentially.** Per phase (still standing after merge resolution), run that phase's checkbox commands. Capture pass/fail per phase.
7. **Atomic STATE.md mutation.** Update every batch member's STATE.md in one orchestrator turn. Commit one summary commit:
   ```
   feat(orchestrator): parallel batch complete [<slug1>:<phase1>=DONE, <slug2>:<phase2>=DONE, ...]

   Phase: orchestrator/parallel-batch
   Agent: workflow-architect (or current orchestrator)
   Members:
     - <slug>:<phase_id> agent=<subagent_type> id=<runtime_id> result=<DONE|REVIEW>
     - ...
   Spec-version: <git-rev of spec/>   # if any code-* phase in batch
   ```
8. **Per-phase result-handling.** Each phase's individual outcome (DONE or REVIEW) is recorded in its own STATE.md. A REVIEW result on one phase does not block other DONE phases in the batch. Surface failures to the user as a list.

### Worktree isolation policy

Most parallel batches share one working tree. The writes-glob conflict gate makes that safe. Worktree isolation is opt-in for two cases:

1. **Operator-flagged**: user invokes with `--isolated` or sets `WORKFLOW_PARALLEL_ISOLATION=worktree`.
2. **Heuristic**: batch contains any HIGH-tier phase (≥9 declared outputs, code-* profile) AND another phase in the batch declares writes under a shared parent directory ≤ 2 levels deep.

Otherwise default to shared-tree.

When isolating: create one worktree per batch member at `.workflow/worktrees/<batch_ts>-<phase_id>/`, on a feature branch `parallel/<batch_ts>-<phase_id>` rooted at the current `HEAD`. Each Agent tool call gets `isolation: "worktree"` (Claude Code handles the cwd switch). After merge resolution, prune worktrees with `git worktree remove`.

### Merge resolution

What the orchestrator does between agent returns and exit-criteria execution. Two paths.

#### Non-worktree path (shared tree) — integrity validation

After all agents return and completion check passes, the orchestrator validates that every modified file belongs to some phase's writes envelope:

```bash
# Files modified by the batch (all agents shared HEAD)
modified=$(git diff --name-only HEAD)

# For each phase, compute its claimed envelope
#   code-with-spec phases: reservations[phase_id].files
#   other phases: writes globs from frontmatter, expanded against the working tree
# Build claimed = union of every phase's envelope.

unclaimed = modified - claimed
if unclaimed != ∅:
  HALT_BATCH; record violation; mark every phase REVIEW; surface to user
```

This catches: (a) reservations-narrowing bugs in the orchestrator, (b) agents writing outside their declared envelope, (c) overlapping writes the conflict gate didn't catch (e.g. globs that intersected in practice but not in the static check).

If integrity passes, exit-criteria run on the merged tree as normal.

#### Worktree path — sequential merge

After all agents return + completion check passes:

```bash
# Each phase committed its work to parallel/<batch_ts>-<phase_id>
git checkout main

merge_log=()
for branch in $(git branch --list "parallel/<batch_ts>-*"); do
  if git merge --no-ff "$branch" -m "merge: $branch into main"; then
    merge_log+=("$branch: clean")
  else
    git merge --abort
    HALT_BATCH; record conflict on this branch; surface to user
  fi
done
```

On any conflict: `git merge --abort` reverts the in-progress merge. Already-merged phases stay on main. Halt the batch and surface:

```
Parallel batch halted on merge conflict.
- Successfully merged: <list>
- Conflict on: <branch>, conflicting paths: <list>
- Outstanding (not yet merged): <list>

Options:
1. Resolve manually: cd to the worktree, fix, git commit, then re-invoke orchestrator with `Resume parallel batch <batch_ts>`
2. Mark this batch's remaining phases REVIEW and run them serially next session
3. Discard the conflicting phase's branch and re-dispatch it standalone
```

The user picks. Orchestrator does NOT auto-resolve merge conflicts.

After all merges succeed, run integrity validation (same check as the non-worktree path) on the merged tree. Then exit criteria.

### Why integrity validation runs in BOTH paths

Worktree merge succeeding is necessary but not sufficient. Two agents can each write to disjoint files within their declared envelopes AND each successfully merge to main, BUT one of them wrote to a file that wasn't in the union of their envelopes (e.g. an agent that touched `package.json` when no phase declared it). The integrity check is the same — only the failure mode differs (worktree halts mid-merge; shared-tree halts before commit).

### Recovery from a halted batch

A halted batch leaves the working tree in a partially-applied state (shared-tree) or on `main` with some merges applied (worktree). The orchestrator records the halt in `.workflow/parallel-batch-<batch_ts>.json`:

```json
{
  "batch_ts": "<ISO>",
  "phases": ["<slug>:<phase_id>", ...],
  "isolation": "shared|worktree",
  "halted_at": "merge|integrity|completion",
  "reason": "<paths>",
  "successful_phases": [...],
  "halted_phase": "...",
  "outstanding_phases": [...]
}
```

`Resume parallel batch <batch_ts>` is a recognized invocation pattern (see `tools/orchestrator_prompt.md §Invocation patterns`). It reads the halt-record, applies any user resolutions, retries the remaining phases.

### Max-parallel cap

Default: **4**. Rationale: tool-batch ergonomics (Claude Code handles ~4-6 concurrent Agent calls cleanly), API rate constraints, and reviewer cognitive load on the resulting batch commit.

Override via env: `WORKFLOW_MAX_PARALLEL=8 claude "Run .workflow/..."`.
Override per-engagement: add `max_parallel: <n>` to the engagement's STATE.md frontmatter (constrains batches that include that engagement's phases).

### Reservations protocol (runtime narrowing)

When the orchestrator dispatches a `profile: planning` phase, it captures the **RESERVATIONS block** from the agent's return.

#### Capture

After the planner agent returns, the orchestrator extracts the block bounded by the markers `RESERVATIONS:` and `END_RESERVATIONS`. Each non-empty line under `RESERVATIONS:` (after stripping leading `- `) is a reserved file path.

```bash
# Pseudocode for extraction:
agent_return | sed -n '/^RESERVATIONS:$/,/^END_RESERVATIONS$/p' | grep '^- ' | sed 's/^- //'
```

The orchestrator persists the parsed list at `<plan_dir>/reservations/<downstream_phase_id>.json`:

```json
{
  "phase": "03-implement",
  "produced_by": "02-plan",
  "produced_at": "<ISO>",
  "produced_by_agent_id": "<runtime_id>",
  "files": [
    "packages/python/src/sox_protocol/core/identity/registry.py",
    "packages/python/src/sox_protocol/core/identity/middleware.py",
    "..."
  ]
}
```

The orchestrator also verifies the reservations match `implementation-plan.json#/files/*/path` as a planner-phase exit criterion. If they diverge, the planner phase enters REVIEW and surfaces to the user.

#### Runtime narrowing

When the orchestrator evaluates a phase P for parallel dispatch, it computes the **effective_writes**:

```
if P has reservations at <plan_dir>/reservations/<P.phase_id>.json:
    effective_writes(P) = intersection(P.writes, reservations[P.phase_id].files)
else:
    effective_writes(P) = P.writes
```

`effective_writes(P)` is what the conflict gate uses (instead of `P.writes`) when checking pairwise disjointness across batch candidates.

This means: a phase whose declared envelope conflicts with another candidate's envelope MAY still parallelize once its planner has emitted reservations narrow enough that the actual write surfaces are disjoint.

#### Phase files remain immutable

Reservations live at `<plan_dir>/reservations/`, NOT in the phase file's frontmatter. Phase files never change post-authoring. Re-runs from prior commits behave identically. Reservations are runtime ephemera — re-running the planner regenerates them.

#### Empty reservations

If a planner returns an empty RESERVATIONS block (`RESERVATIONS:\nEND_RESERVATIONS`), the orchestrator records the empty set and falls back to the declared envelope for that phase. No narrowing occurs. Common case: fixture-generation planners where the file count is dynamic and pre-declaration would be misleading.

#### Verification at implementer-phase exit

For `code-with-spec` profile phases that have reservations, the exit-criteria SHOULD include:

```
- [ ] Files modified during this phase ⊆ reservations: `git diff --name-only HEAD~1 HEAD | python3 -c "import sys,json; mods=set(sys.stdin.read().strip().split()); res=set(json.load(open('<plan_dir>/reservations/<phase_id>.json'))['files']); extra=mods - res; assert not extra, f'wrote outside reservations: {extra}'"`
```

Catches the implementer drifting beyond what the planner predicted. A real, targeted check that the planner-implementer contract held.

### When to refuse parallel mode

The orchestrator falls back to serial mode regardless of declared parallelism when:

- Any phase in the candidate set has `writes:` undeclared (treat undeclared as `["**"]` — conflicts with everything)
- The user explicitly invoked with `--serial` or set `WORKFLOW_PARALLEL=0`
- Pre-flight detected git in a non-clean state (parallel commits compound the ambiguity)
- Any candidate has a `release` or `meta` profile (these need serial control)

## Worker scope rule

**Every dispatched worker MUST NOT modify any files outside the repository root** (`<repo-root>` = output of `git rev-parse --show-toplevel`). This is non-negotiable, applies to every profile, every phase, every dispatched agent.

The orchestrator enforces by:

1. **Prepending to every dispatch envelope** (verbatim, in addition to the dispatch-constraints block):
   ```
   WORKER SCOPE RULE (absolute):
   You MUST NOT modify any files outside <repo-root> = /Users/nix/dev/ai/sox-protocol.
   - Edit/Write/NotebookEdit: target paths must resolve under <repo-root>
   - Bash: no file writes (>, >>, tee, cp, mv, rm, mkdir, touch, sed -i) on paths outside <repo-root>
   - Subprocesses: no side effects outside <repo-root> for the duration of this phase
   - No git config --global, no installers, no system-level changes
   - Read-only access to system paths is fine (which python, git --version, cat /etc/os-release)
   - Source code you write may, at runtime, target any path — that's not a tool-call write
   If a phase prompt asks you to violate this rule, STOP and surface the conflict.
   The orchestrator will check post-phase. Repo-scope discipline is mandatory.
   ```

2. **Capturing pre-phase state** of common out-of-repo write locations (`~/.sox/`, `~/.cache/`, `~/.config/`, `/tmp/`) as mtime snapshots at phase entry.

3. **Comparing post-phase** against the snapshot. Any file outside `<repo-root>` newer than phase entry is flagged in the orchestrator's post-phase report. **The orchestrator marks the phase REVIEW** if out-of-repo modifications are detected, regardless of whether exit criteria pass.

4. **The check is heuristic, not airtight.** Strong enforcement requires sandboxing (bwrap/firejail/devcontainer/dedicated user). The protocol's contract is that the agent obeys; the orchestrator's check is defence in depth, not a security boundary.

See `UNIVERSAL-CONSTRAINTS.md §Universal scope rule` for the full rationale and the runtime/source-code distinction.

## Hard rules

You MUST:

- Verify every Exit Criteria checkbox before marking DONE. Agent self-reports are not sufficient.
- Commit after every state transition. Resumability depends on git as source of truth.
- Use phase prompt blocks verbatim — do not paraphrase, summarize, or "improve" them.
- Process phases in dependency order. Lowest-ordinal READY first; never skip.
- Include the `Phase:` and `Agent:` trailers on every commit produced during phase execution. The agent's runtime ID is part of the trailer.
- For `code-*` profile phases: include the `Spec-version:` trailer recording the git rev of `spec/` at dispatch time.

You MUST NOT:

- Modify any phase file's content during execution. Phase files are versioned artifacts.
- Mark a phase DONE without all Exit Criteria passing.
- Continue past a verification failure without explicit user instruction.
- Auto-resolve verification failures by editing deliverables yourself. Re-spawn the agent with corrective feedback, or surface to user.
- Skip the `Phase:` / `Agent:` trailers. Provenance is non-negotiable.
- Bypass the planner gate for `code-with-spec` profile phases.

## Completion check protocol

Subagents have their own session budgets. They can stop mid-task without surfacing the truncation as an error — they return a partial response that looks well-formed but leaves declared outputs unwritten. Without a completion check, the orchestrator's next step would run exit criteria, which then fail on missing files, sending the phase to REVIEW for the wrong reason (no actual quality issue, just incomplete work).

The orchestrator runs this check **between agent return and exit-criteria execution**.

### What to verify

For each phase, the orchestrator computes the **expected outputs set**:

1. **Code-with-spec phases** that have a planner prereq: read `<plan_dir>/reservations/<phase_id>.json`. The `files` list is the authoritative expected set.
2. **All other phases**: parse the phase file's `## Outputs` section. Every bullet is an expected path or glob. Resolve globs against the working tree to a concrete file list.

Then check disk:

```python
expected = set(expected_outputs(phase))
present  = set(p for p in expected if path_exists(p))
missing  = expected - present
```

If `missing` is empty → proceed to exit-criteria step.
If `missing` is non-empty → trigger resume.

### Resume protocol

When `missing` is non-empty, the orchestrator dispatches **SendMessage** to the same agent (using the agent runtime ID captured at initial dispatch) with this message:

```text
Resume — completion check found <N> declared outputs missing on disk:

<list of missing paths, one per line>

Apply each missing deliverable per the original phase prompt. The original
hard constraints still apply (100% coverage, mypy --strict, etc.).

If you stopped mid-task because you ran out of token budget, prefer to
finish the smallest remaining file group first, then signal stop with a
PARTIAL_COMPLETION block (see Partial-completion protocol). The orchestrator
will resume you again.

After completing the missing outputs, REPORT (≤ 100 words) what you wrote
and whether anything is still outstanding.
```

The orchestrator records this resume in `STATE.md` transitions but does NOT increment `attempts:` (resume is not a verification failure, it's a continuation). Cap at **5 resumes** before treating as REVIEW.

### Partial-completion protocol (agent side)

For phases with high output cardinality (see Risk tiers below), the dispatch envelope instructs the agent to signal partial-completion if it approaches its budget:

```text
PARTIAL_COMPLETION:
- completed_files:
  - <path>
  - <path>
- remaining_files:
  - <path>
  - <path>
- resume_hint: <one sentence: where the next agent should pick up>
END_PARTIAL_COMPLETION
```

The orchestrator parses this block, persists it at `<plan_dir>/partial/<phase_id>.json`, and uses it as input to the resume SendMessage so the resumed agent has explicit pickup context.

### Risk tiers

A phase's risk tier is computed from declared output cardinality and profile:

| Tier | Criteria | Dispatch envelope action |
|---|---|---|
| LOW | profile in {meta, review, planning, release}, OR ≤ 3 declared outputs | Standard envelope; no partial-completion instruction |
| MEDIUM | profile in {docs, spec, test-harness, code-python, code-typescript} AND 4–8 declared outputs | Standard envelope + partial-completion instruction |
| HIGH | profile in {code-with-spec, code-python, code-typescript, test-harness, spec} AND ≥9 declared outputs | Standard envelope + partial-completion instruction + incremental-commit hint ("write one logical file group, verify it imports/compiles, move to next") |

Risk tier is computed automatically by the orchestrator at dispatch time. The orchestrator surfaces the tier in its preamble:

```
[PRE-FLIGHT] spec-extraction/01-extract rated HIGH
  (declared outputs: 25, profile: spec)
  Will use partial-completion + incremental-commit dispatch envelope
  Will run completion check after agent return
```

### When to give up on resume

After **5 consecutive resumes** that still leave outputs missing, the orchestrator treats the phase as REVIEW (not a verification failure of the agent's work, but a scope-too-large failure of the phase contract). Surface to user with:

```
Phase <slug>/<phase_id> exceeded resume limit (5 attempts, still missing N outputs).
The phase prompt may be too broad for one agent's budget. Options:
1. Edit the phase file to narrow scope (deliberate authoring action; immutability exception)
2. Split into multiple phases (requires planner re-run + state-machine restructure)
3. Continue manually
```

This is the rare case where phase immutability bends. The user decides.

## REVIEW-state recovery

When Exit Criteria fail, the phase is marked REVIEW, attempts is incremented, the orchestrator commits a `chore(<slug>): <phase_id> failed verification` commit, and surfaces failures to the user. The phase file remains immutable. Recovery happens via a feedback artifact, not phase-file edits.

### Recovery protocol

1. **User writes feedback** at `<plan_dir>/phases/<phase_id>.feedback-<N>.md` where `<N>` is the retry attempt number (1, 2, 3). Format:

   ```markdown
   # Feedback for <phase_id> attempt <N>

   ## Failed checks
   - <verbatim from orchestrator's failure report>

   ## Diagnosis
   <user's analysis of root cause>

   ## Corrective instructions
   <specific changes the agent should make on rerun>
   ```

2. **Orchestrator re-dispatches** the phase. The dispatched prompt is the **verbatim phase prompt block** PLUS a prefix injected by the orchestrator:

   ```
   This is a re-dispatch following exit-criteria failure (attempt <N+1>). READ the feedback at <feedback_path> first. Apply its corrective instructions before producing your deliverables. The original prompt and all hard constraints still apply unless the feedback explicitly overrides one.
   ```

3. **Increment `attempts:`** in STATE.md. Cap at **3 retries** before halting and demanding user intervention rather than continuing automated retry.

4. **Phase file remains immutable.** If the failure indicates the phase prompt itself is wrong (typo in exit criterion, mis-cited spec section), the user fixes the phase file as a separate commit OUTSIDE the recovery loop. That edit is a deliberate phase-contract change, treated as a new authoring action — restart the engagement's affected branch.

### Dev/review cascade on rerun

When an implementer phase (e.g. `03-implement`) fails review and is re-dispatched, any **already-DONE downstream review phase** (e.g. `04-review`) becomes stale because it audited the previous implementer output.

Cascade rule:

1. When a phase transitions OUT of DONE back to IN_PROGRESS (re-dispatch), every phase whose `prereqs:` includes the rerunning phase moves from DONE back to READY (or to BLOCKED if other prereqs aren't satisfied). New STATE value: `STALE` may be used as an interim indicator before promotion to READY, at the orchestrator's discretion.
2. The downstream phase is re-dispatched with its original verbatim prompt (the review prompt naturally re-reads the new implementer output via its `Inputs:` section).
3. Reservations follow the same rule: if a planner phase reruns, downstream `<plan_dir>/reservations/<phase_id>.json` is invalidated and must be regenerated from the new run.
4. Each cascaded re-dispatch increments its own `attempts:` counter independently.

This guarantees a green DONE chain at engagement-completion time means *every* phase audited the *current* artifacts, not historical ones.

## Architect-question resolution flow

Architect questions surfaced during `bucket-classification` (or any other engagement) require a decision before downstream engagements that depend on them can proceed. Resolution is **proactively** orchestrator-dispatched, not reactive.

### Proactive scan (runs at the start of every orchestrator invocation)

Before entering the main loop (serial or parallel), the orchestrator:

1. **Reads the architect-question queue** from `.workflow/plans/bucket-classification/result.md` (the canonical consolidated list) and `.workflow/plans/bucket-classification/classified.json#/architect_questions`.
2. **Cross-references each question with engagement ADR phases.** Some questions map to a specific engagement's ADR phase (e.g. Q1 "credential primitive" → `identity-primitive/01-adr`; Q3 "middleware vs hooks" → `hooks-middleware/01-adr`). These are **delegated** — the ADR phase will resolve them as part of its normal work; the orchestrator marks them `delegated_to: <slug>/<phase_id>` in a tracking file at `.workflow/decisions/INDEX.md` and does NOT pre-resolve them.
3. **Identifies orphan questions** — questions with no corresponding ADR phase in any engagement (e.g. backpressure advisory-vs-enforced, idempotency TTL, replay access control, seq global-vs-per-channel for federation). These are the orchestrator's responsibility.
4. **For each orphan question**, the orchestrator dispatches `workflow:workflow-architect` with: the question text, its source-section context, the relevant engagement objectives, any prior research memory, the broader vision document. The architect returns a decision OR an escalation-to-user with explicit candidate options.
5. **Records the decision** at `docs/decisions/<question-slug>.md` (lightweight ADR-style: status, context, decision, consequences). Updates `.workflow/decisions/INDEX.md` with status (`resolved | escalated | delegated`).
6. **Then enters the main loop.** Phases that depend on resolved questions can now advance with the decision available as input.

For questions that genuinely require human judgment (brand naming, budget commitments, scope cuts), the architect surfaces them to the user with candidate options laid out; the user decides; the orchestrator records the decision.

### Question-ADR mapping table (canonical)

This mapping is computed by the orchestrator from each engagement's ADR phase frontmatter. Phase authors signal "this ADR resolves architect question N" by including the question text or a stable question slug in the ADR phase's `Inputs` section or `## Notes`. The orchestrator's scan picks this up.

### Reactive fallback

If a READY phase is gated by an unresolved orphan question that the proactive scan missed (e.g. a new question was added to the queue mid-run), the orchestrator falls back to the reactive flow: dispatch architect, record, unblock. This is a safety net, not the main path.

### Hard rule

**The user does not run architect-question resolution by hand.** The orchestrator handles it. If the user finds themselves writing `docs/decisions/<question>.md` manually, that's a contract violation — the orchestrator should have caught it. The invocation patterns `Run .workflow/`, `Run .workflow/plans/<slug>/STATE.md`, and `Resolve architect questions` all trigger the proactive scan as their first step.

### `Resolve architect questions` invocation

For when the user wants to resolve the queue without advancing any phases (e.g. before a long parallel run, to make sure no decisions surface mid-batch):

```
Resolve architect questions [from <plan_dir>/result.md]
```

This runs the proactive scan + architect dispatches, then exits without entering the main loop. Useful as a "stage-the-decisions" step.

This means: **the consolidated architect-question queue from `bucket-classification` is not a dead-end document — it is the input list for orchestrator-dispatched architect runs that happen automatically at the start of every subsequent invocation.**

## Dispatch constraints (token budget)

The orchestrator does NOT read full subagent outputs (only structured markers: RESERVATIONS block, agent runtime ID, exit-criterion-relevant report sentences). It MUST, however, communicate response-shape constraints to subagents up-front, so the subagent writes within budgets the orchestrator can handle.

Every dispatch prompt is prefixed with a constraints envelope:

```
DISPATCH CONSTRAINTS:
- Response token target: <N> tokens (e.g. 2000 for review phases, 4000 for code phases, 6000 for spec phases)
- The orchestrator parses your response for: RESERVATIONS block (planner only), runtime stats requested in REPORT, exit-criterion-relevant facts. It does NOT consume free-form prose beyond your REPORT line.
- Prefer dense structured output. Skip narrative explanations unless the phase prompt requested them.
- If you must exceed the budget to satisfy the prompt, prioritize: (1) making the deliverable files correct, (2) the RESERVATIONS block (planners), (3) the REPORT line, (4) supporting prose. Truncate (4) first.
```

Default budgets by profile:

| Profile | Response token target |
|---|---|
| meta | 1500 |
| review | 1500 |
| planning | 3000 |
| docs | 4000 |
| spec | 5000 |
| code-python | 3500 |
| code-typescript | 3500 |
| code-with-spec | 3500 |
| test-harness | 3500 |
| release | 2000 |

Per-phase override via `response_token_target:` in phase frontmatter when a phase legitimately needs more (e.g. an unusually broad spec extraction).

## Termination conditions

| Condition | Action |
|---|---|
| **Success** — all phases DONE | Print success message; suggest tagging if engagement was a release. |
| **Verification failure** — exit criteria failed | Print phase id, failed checks, agent report. Options: re-spawn with feedback, fix manually then mark DONE, skip criterion (not recommended). |
| **Agent error** — agent crashed | Mark phase IN_PROGRESS (revert from anything else); commit; print error verbatim. Re-invokeable. |
| **Pre-flight failure** | Print which check failed; do not enter main loop. |
| **Orphan blockage** — no READY but BLOCKED exist | Print BLOCKED phases and unmet prereqs. Bug; stop. |
| **User interrupt** | Stop cleanly; latest committed state is recoverable. |

## Optional review gates

Between code phases, an optional review-gate phase using `code-reviewer` or `qa-expert` may be inserted. The gate is a real phase boundary (different specialist) and must declare `profile: review` in its frontmatter. Phase prompt template:

```text
agent: code-reviewer
prompt: Review the changes from <phase_id> of <engagement>. Read <phase>.md for the deliverables and the spec at spec/<relevant>.md for the contract. Focus on: (a) spec-fidelity, (b) test coverage gaps, (c) architecture-rule violations (core/ MUST NOT import adapters/), (d) any deviation from <implementation-plan.json>. Report: pass/fail with specific file:line citations.
```
