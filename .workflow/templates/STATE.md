# State file template

The single source of truth for engagement progress. Mutable. Append-only history table; mutable status table.

Filename: `STATE.md` at the engagement root (`.workflow/plans/<slug>/STATE.md`).

---

```markdown
---
slug: <slug>
target: <one-line target state>      # what "done" means for this engagement
created: <ISO date>
last_event: <ISO timestamp>          # touched on every status transition
orchestrator_protocol: v1            # bumped if the state-file format changes
---

# <slug> — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-<slug> | <title> | `READY` | python-pro | 0 | 2026-04-29T00:00:00Z |
| 02-<slug> | <title> | `BLOCKED` | api-designer | 0 | 2026-04-29T00:00:00Z |
| 03-<slug> | <title> | `BLOCKED` | test-automator | 0 | 2026-04-29T00:00:00Z |

## Status legend

```
BLOCKED     → prerequisites not yet DONE
READY       → all prerequisites DONE; next eligible to pick up
IN_PROGRESS → an agent is currently executing
REVIEW      → agent reported done; exit criteria failed verification
DONE        → exit criteria verified
ABANDONED   → consciously dropped; reason in transitions
```

## Currently next action

`<phase_id>` is `READY`. Spawn `<agent>` with the prompt from `phases/<phase_id>.md`.

(If multiple phases READY, orchestrator picks lowest ordinal unless parallelism is configured.)

## Transitions (append-only)

Most recent first. Format: `<ISO> <phase_id> <from> → <to> — <one-line note or commit hash>`.

- 2026-04-29T00:00:00Z 01-<slug> — initialized

## Open blockers

Phase-specific blockers that prevent progress. Resolve and remove.

- (none)

## Resolved blockers

Archive of resolved blockers for postmortem.

- (none)

## Termination targets

The engagement is `complete` when all of:

- [ ] All non-abandoned phases are DONE
- [ ] <engagement-specific success criterion>
- [ ] <engagement-specific success criterion>
```

---

## Orchestrator contract

The full contract lives in `.workflow/templates/ORCHESTRATOR-CONTRACT.md`. Summary:

1. **Read STATE.md first.** Pick the lowest-ordinal `READY` phase. If none, terminate.
2. **Load only that phase file** (`phases/<phase_id>.md`). Do not load other phase files unless the current phase's `Inputs` section cites them.
3. **Mark phase IN_PROGRESS** in STATE.md, append transition, commit `chore(<slug>): <phase_id> in progress`.
4. **Dispatch** the named agent with the verbatim prompt block. Capture the agent's runtime ID.
5. **On agent return, run the universal + engagement-specific exit criteria.** Bash-execute every checkbox.
6. **On all-pass:** mutate STATE.md: phase → DONE, promote phases listed in `next state`, append a transition row, update `last_event`. Commit:
   ```
   feat(<slug>:<phase_id>): <one-line summary>

   <bullet list>

   Phase: <slug>/<phase_id>
   Agent: <subagent_type> (id: <runtime_agent_id>)
   Orchestrator: workflow-architect (or current orchestrator)
   Spec-version: <git-rev of spec/>   # code-* profiles only
   ```
7. **On any-fail:** mutate STATE.md: phase → REVIEW, increment attempts, append transition. Commit:
   ```
   chore(<slug>): <phase_id> failed verification

   Failed checks:
   - <check>

   Phase: <slug>/<phase_id>
   Agent: <subagent_type> (id: <runtime_agent_id>)
   ```
   Stop and surface to user.
8. **Never edit phase files** during execution. They are versioned artifacts.

## Commit-trailer requirements (non-negotiable)

Every commit produced during phase execution MUST include:

- `Phase: <slug>/<phase_id>` — provenance to phase contract
- `Agent: <subagent_type> (id: <runtime_agent_id>)` — provenance to executing agent
- `Orchestrator: <orchestrator-name>[ (run: <run_id>)]` — provenance to orchestrator session
- `Spec-version: <git-rev>` — only for `code-python`, `code-typescript`, `code-with-spec` profiles. Recorded at dispatch time so spec-vs-impl drift is detectable.

## Why this split

- **STATE.md is small** — orchestrator loads it cheaply on every loop iteration. Phase files (potentially long prompts + criteria) load only when needed.
- **State changes are localized** — every commit that advances state touches only STATE.md, making history readable.
- **Phase files immutable** — replays produce identical agent prompts. Reproducibility.
- **Resumable** — interrupt at any point; `last_event` plus the status table tells the next orchestrator session exactly where to pick up.
