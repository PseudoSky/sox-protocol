# Planner output contract

Use this contract when dispatching `workflow:workflow-planner` (or any planner) for a SOX-style engagement. It overrides the planner's default `migration.md` output with the separated-phase + central-state format.

## What to include in the planner prompt (prefix or trailing block)

```text
OUTPUT FORMAT OVERRIDE — SOX phase-state-machine style.

Do NOT produce a single migration.md with all phases inline. Instead, produce:

1. STATE.md at the engagement root (<plan_dir>/STATE.md), conforming to .workflow/templates/STATE.md.
   - Frontmatter: slug, target, created, last_event, orchestrator_protocol: v1
   - Status table with every phase you defined
   - Currently next action: the lowest-ordinal phase with no prereqs, marked READY
   - Transitions section initialized with one row per phase: `<ISO> <phase_id> — initialized`
   - Termination targets reflecting the engagement's success criteria

2. One file per phase at <plan_dir>/phases/<NN>-<kebab>.md, conforming to .workflow/templates/PHASE.md.
   - Frontmatter: phase_id, title, agent, estimated_effort, prereqs, unblocks, parallelizable_with, context_size
   - Objective: one paragraph
   - Inputs: explicit file paths the executor needs to read
   - Prompt: a verbatim, self-contained prompt block the orchestrator will pass to the named agent. The agent will not see this conversation, will not see the engagement's status.md, will not see other phase files unless cited in Inputs. Brief the agent like a colleague who just walked into the room.
   - Exit criteria: every checkbox must be a concrete bash-executable check or file-existence test, not a subjective judgment
   - Outputs: files this phase produces (must match the agent's deliverables in the prompt)
   - Next state: phase_ids to promote from BLOCKED → READY when this phase reaches DONE

HARD RULES:
- The phase prompt block is the contract with the executor. Make it self-sufficient.
- Every exit criterion must be verifiable by an orchestrator running shell commands. No "review the work and decide" criteria.
- Prereqs and unblocks form the dependency DAG. Validate before emitting that the DAG is acyclic and that every unblocked phase is actually a defined phase_id.
- Use the engagement's existing status.md (<plan_dir>/status.md) as the source-of-truth for objective, acceptance criteria, inputs, outputs, suggested executor. Decompose its acceptance criteria into phase-level criteria; do not invent new scope.
- The Currently-next-action in STATE.md must be set so an orchestrator picking up the engagement knows immediately what to do.
- After writing, do not also write a migration.md — STATE.md plus phases/*.md is the complete output.

PHASE BOUNDARY RULE (critical):
A phase boundary is an AGENT-HANDOFF boundary. Split phases when a different specialist takes over (api-designer → python-pro → test-automator → content-marketer). Do NOT split on logical sub-step boundaries that one specialist handles end-to-end. Reference: docs/BUILD-STATE.md uses one phase per specialist (M0=api-designer, M1-M3/M5=python-pro, M4=interactive, M6-M7=test-automator, M8=content-marketer). If two adjacent phases have the same `agent:` value with no intervening artifact-handoff, collapse them.

REFERENCE: docs/BUILD-STATE.md in the SOX Protocol repo is the canonical example of this pattern (single-file form). The new format splits it into STATE.md + phases/ but keeps the same discipline: verbatim prompts, concrete exit criteria, explicit dependencies.
```

## Why we override rather than modify the planner spec globally

Modifying the planner agent's spec affects every project using the workflow plugin. This contract is SOX-specific (until/unless we promote it). Until the format is proven across multiple engagements, an in-prompt override is the lower-risk path. If the format proves itself, follow up with a `workflow-agent-builder` UPDATE to make it the planner's default.

## When to bypass the planner entirely

For small engagements (≤ 3 phases, no fan-out, prompts already implied by status.md), it is cheaper to generate the phase files directly than to dispatch the planner. The planner earns its keep when:

- The engagement has 4+ phases with non-trivial dependencies
- The work breakdown isn't obvious from status.md
- Phase prompts need to encode complex prior-art context the planner is positioned to research

For straightforward engagements (e.g. bucket-classification, defensive-publication), generate phase files directly using the templates.
