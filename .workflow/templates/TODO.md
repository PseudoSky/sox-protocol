# Workflow infrastructure TODO

Open items in the orchestrator/contract templates surfaced by the holistic audit (2026-04-30). Distinct from the project's `TODO.md` at the repo root — these track workflow-system improvements, not SOX-protocol features.

Severity legend:

- 🔴 **CRITICAL** — will fail or produce wrong results on the next orchestrator run; fix before relying on the protocol
- 🟠 **HIGH** — silent inconsistencies or non-reproducibility; fix when convenient
- 🟡 **MEDIUM** — lint coverage gaps and contract holes; address as polish
- 🟢 **LOW** — quality-of-life and right-sizing

---

## 🔴 CRITICAL — blockers for the next orchestrator run

### TODO-WI-001 — ADR phases must declare which architect questions they resolve

**What:** No ADR phase frontmatter currently marks the architect question(s) it resolves. The proactive architect-question scan in `ORCHESTRATOR-CONTRACT.md §Architect-question resolution flow` requires this signal to compute the delegated/orphan partition.

**Why it matters:** On the next orchestrator run, the proactive scan will read 21 architect questions from `bucket-classification/result.md`, find no ADR mapping markers, and treat all 21 as orphans. It will dispatch ~21 `workflow:workflow-architect` calls before any phase work — wasting tokens and making `identity-primitive/01-adr` (which exists specifically to resolve Q1 credential-primitive) redundant.

**Fix:**

1. Add a frontmatter field to `templates/PHASE.md`:
   ```yaml
   resolves_architect_questions: [<question-slug>, ...]   # ADR phases only; empty/omitted otherwise
   ```
2. Backport into existing ADR phases:
   - `identity-primitive/01-adr` → `[credential-primitive]`
   - `hooks-middleware/01-adr` → `[middleware-vs-hooks]`
3. Update `tools/workflow_lint.py` to verify referenced slugs exist in `bucket-classification/classified.json#/architect_questions` (warn-only since bucket-classification must have run first).

**Effort:** 30 minutes.

---

### TODO-WI-002 — Schema for `.workflow/decisions/INDEX.md` undocumented

**What:** `ORCHESTRATOR-CONTRACT.md §Architect-question resolution flow` instructs the orchestrator to track delegation/resolution status in `.workflow/decisions/INDEX.md` but doesn't specify the file's shape.

**Why it matters:** First orchestrator run invents a format; second run may use a different format. Non-reproducible. `workflow_lint.py` can't validate it.

**Fix:** Document the schema in `ORCHESTRATOR-CONTRACT.md §Architect-question resolution flow`. Suggested:

```yaml
---
generated_by: workflow-orchestrator
generated_at: <ISO>
source_queue: .workflow/plans/bucket-classification/result.md
---

# Architect-question decisions

| # | Slug | Source section | Status | Resolution path |
|---|---|---|---|---|
| 1 | credential-primitive | agent identity verification | delegated | identity-primitive/01-adr |
| 5 | dm-semantics | direct messages | resolved | docs/decisions/dm-semantics.md |
| 8 | backpressure-policy | backpressure | escalated | (user input pending) |
```

Status values: `delegated` (an ADR will resolve), `resolved` (decision recorded at docs/decisions/<slug>.md), `escalated` (waiting for user), `obsolete` (question superseded by another decision).

**Effort:** 10 minutes.

---

### TODO-WI-003 — Schema for `docs/decisions/<slug>.md` undocumented

**What:** Lightweight ADR-style format mentioned but no template.

**Fix:** Document a 5-section template in `ORCHESTRATOR-CONTRACT.md`:

```markdown
# <Question text in title form>

- Slug: <kebab-slug>
- Source: <bucket-classification result.md Q-N> · `<source section>`
- Status: Resolved (<YYYY-MM-DD>)
- Decided by: <orchestrator | workflow-architect | user>

## Context
(2-3 sentences: what's the question, why it matters, what blocks on it)

## Decision
(1-2 sentences: pick one option)

## Alternatives considered
(table: option | pros | cons | rejection rationale)

## Consequences
- Positive: ...
- Negative: ...
- Operational: ...
- Spec impact: ...

## Related
- Engagements affected: <list>
- Other architect questions resolved/superseded: <list>
```

**Effort:** 10 minutes.

---

### TODO-WI-004 — Question-slug derivation rule undocumented

**What:** Slugs for architect questions are referenced (`docs/decisions/<slug>.md`) but no derivation rule. Different orchestrator sessions may produce different slugs for the same question.

**Fix:** Document in `ORCHESTRATOR-CONTRACT.md §Architect-question resolution flow`:

> Question slug = lowercase, kebab-case, ≤ 5 words extracted from the architect question text, prefixed with the source-section slug if needed for uniqueness. Example: question "What is the right credential primitive — shared secret, asymmetric keypair, or JWT?" → slug `credential-primitive`. Collisions: append `-N` (e.g. `dm-semantics-2`). The orchestrator computes the slug deterministically; `workflow_lint.py` warns on collisions.

**Effort:** 5 minutes (just the doc paragraph).

---

### TODO-WI-005 — Acknowledge LLM-trust boundary in the orchestrator prompt

**What:** The contracts describe many "the orchestrator does X" steps that have no actual code:

- Compute risk tier from declared outputs
- Capture mtime snapshots before phase entry
- Parse RESERVATIONS blocks from agent returns
- Run completion-check disk diff
- Compute integrity-validation set difference
- Write parallel-batch halt records
- Compute Question-ADR mapping table
- Sanity-check writes/reads globs

**Why it matters:** All of these are LLM-following-instructions, not deterministic code. Under context pressure, Claude may drop steps. Users will assume the contract is mechanically enforced when it's actually agent-enforced.

**Fix:** Add a paragraph to `tools/orchestrator_prompt.md` IMPERATIVES section:

> **Honest reliability boundary.** Many steps in the contracts ("the orchestrator does X") are instructions to you, not deterministic code. Under context pressure you may be tempted to skip steps to save tokens — DO NOT. If you find yourself skipping a step (mtime snapshot, RESERVATIONS parse, completion check, integrity validation), surface that to the user explicitly: "Skipping <step> due to context pressure; recommend re-running with smaller scope." Silent skipping breaks the protocol's reproducibility guarantees. The user has chosen this protocol over deterministic code; honor that choice with explicit failure rather than hidden cuts.

**Effort:** 5 minutes.

---

## 🟠 HIGH — silent inconsistencies

### TODO-WI-006 — Phase-file mid-flight edits invisible

**What:** REVIEW recovery allows phase-file edits "as a separate authoring action outside the recovery loop." The lint tool doesn't track this. A phase file edited mid-engagement is invisible to the orchestrator.

**Fix:** At phase entry, the orchestrator captures the phase file's git blob hash. At phase exit (or re-dispatch), compare. If the file changed mid-flight without an explicit "phase-contract revision" commit, surface it. Document the protocol for legitimate mid-flight edits (commit → re-run engagement from the affected phase).

**Effort:** 30 minutes contract + lint.

---

### TODO-WI-007 — Sandbox-aware worker-scope check

**What:** The mtime heuristic for the worker-scope rule is now redundant under sandbox isolation (sandbox prevents the writes it checks for). Currently still runs and consumes orchestrator turns.

**Fix:** Detect sandbox at pre-flight (probe for sandbox-specific markers; or accept an env var `WORKFLOW_SANDBOX_ACTIVE=1`). If active, skip the mtime heuristic and note in the preamble: "Worker scope rule enforced by sandbox; orchestrator-side heuristic skipped."

**Effort:** 15 minutes.

---

## 🟡 MEDIUM — lint coverage gaps

### TODO-WI-008 — Lint should verify writes/reads glob syntax

**What:** A typo like `packages/python/**.py` (should be `packages/python/**/*.py`) silently passes. Glob compilation against a sample tree isn't checked.

**Fix:** Add lint check that every glob in `writes:` and `reads:` parses via `pathlib.PurePath.match` semantics; warn on suspect patterns (`**.ext`, `..`, leading `/`).

**Effort:** 30 minutes (workflow_lint addition + tests).

---

### TODO-WI-009 — Lint should verify planner-implementer linkage

**What:** Check (l) verifies that every planning-profile phase has a downstream consumer with the planner's phase_id in its exit criteria. But it doesn't verify:

- The planner's prompt includes the verbatim RESERVATIONS instruction
- The implementer's exit criteria reference `reservations/<phase_id>.json`
- The implementer's `Inputs` section cites the implementation-plan.json

**Fix:** Three new checks (m, n, o) in `workflow_lint.py`.

**Effort:** 1 hour (workflow_lint additions + tests).

---

### TODO-WI-010 — Lint should verify ADR question-resolution declarations

**What:** Depends on TODO-WI-001. Once ADR phases declare `resolves_architect_questions:`, the lint should verify the referenced slugs are real.

**Fix:** Add lint check (p): every slug in any phase's `resolves_architect_questions:` exists in `bucket-classification/classified.json#/architect_questions`.

**Effort:** 15 minutes (workflow_lint addition + test).

---

## 🟢 LOW — polish

### TODO-WI-011 — Trim dispatch envelope by tier

**What:** Currently every dispatch envelope includes WORKER SCOPE RULE + DISPATCH CONSTRAINTS + risk-tier preamble + (for HIGH/MEDIUM) partial-completion instruction + (for code-with-spec) reservations instruction. ~300 tokens of preamble even on LOW-tier review phases that don't need most of it.

**Fix:** Tier-aware envelope. LOW: just WORKER SCOPE RULE + DISPATCH CONSTRAINTS short form. MEDIUM: + partial-completion. HIGH: + incremental-commit hint.

**Effort:** 20 minutes contract + verify with lint.

---

### TODO-WI-012 — Commit example artifacts for the runtime-created files

**What:** `.workflow/parallel-batch-<ts>.json`, `.workflow/partial/<phase_id>.json`, `<plan_dir>/reservations/<phase_id>.json`, `<plan_dir>/reviews/<phase_id>.md` — schemas documented, no concrete examples committed. First run invents the actual shape.

**Fix:** Commit sample artifacts to `.workflow/templates/examples/` so the orchestrator copies a known-good shape rather than improvising. Lock the JSON schemas via a JSON-Schema file the orchestrator can validate against.

**Effort:** 30 minutes.

---

---

## Items learned from the first parallel orchestrator run (2026-04-30)

The first multi-engagement parallel orchestrator run successfully completed `spec-extraction/01-extract`, `identity-primitive/01-adr`, `hooks-middleware/01-adr`, and `defensive-publication/01-housekeeping`. The orchestrator surfaced five contract bugs during the run; some are fixed, some are tracked here.

### TODO-WI-013 — Phase prereqs should encode "touches another engagement's outputs" (FIXED-FORWARD: orchestrator judgment, not contract)

**What:** `defensive-publication/01-housekeeping` wrote SPDX headers across `spec/**/*.md`. It declares `writes:` covering those paths but has no `prereqs:` field encoding the dependency on `spec-extraction/01-extract`. The first orchestrator correctly sequenced it (extract first, then headers) by reasoning, but a blind future orchestrator could dispatch them in parallel with defensive-publication adding headers to files that don't yet exist.

**Why it matters:** The DAG implied by `prereqs:` is the orchestrator's parallelism gate. Cross-engagement file-touching dependencies that are NOT in `prereqs:` are invisible to the gate. The current run got lucky.

**Fix:** Two options:
1. Declare `prereqs: [spec-extraction:01-extract]` in `defensive-publication/01-housekeeping` (cross-engagement prereqs in slug:phase form). Reduces parallelism but is honest about the dependency. Requires extending the prereq syntax.
2. Split `defensive-publication/01-housekeeping` into two phases: license/NOTICE/CONTRIBUTING/SWHID first (no spec dependency) → SPDX header pass second (depends on spec-extraction). Preserves parallelism for the first half.

Option 2 is cleaner. Defer until `defensive-publication` is re-run (currently DONE).

**Effort:** 30 minutes if option 2.

### TODO-WI-014 — Risk-tier heuristic missed `spec-extraction/01-extract`

**What:** Phase declared 3 output bullets (`spec/**`, `docs/adr/0001-*`, `README.md`) → LOW tier. Actually wrote 28 files. No partial-completion warning in dispatch envelope. Took ~650 seconds; no resume needed but only by luck.

**Resolved:** PHASE.md §Risk tier now states: "any output bullet that is a directory or glob counts as ≥4 outputs for tier purposes." Commit: see git log. Re-running `spec-extraction/01-extract` would now correctly classify as MEDIUM/HIGH.

### TODO-WI-015 — Cross-reference `docs/decisions/` in every reviewer phase prompt

**What:** Multiple architect decisions may not propagate fully into spec artifacts. The first orchestrator flagged these specific candidates that may have been missed in `spec-extraction/01-extract`:
- `_sox_protocol` block in list_channels output (version negotiation decision)
- `origin_server` field in envelope (federation-aware decision)
- `replay` as a distinct verb in operations
- `channels__ack` as a dedicated tool
- `backpressure` field on send output

**Resolved (partially):** `spec-extraction/02-review/phases/02-review.md` now has Review Dimension 7 explicitly cross-referencing docs/decisions/ for these and other decisions. But the same pattern should exist in every reviewer phase. Commit: see git log.

**Remaining:** Add a similar cross-reference dimension to:
- `identity-primitive/04-review`
- `hooks-middleware/04-review`
- `chat-webapp/03-polish`
- (any future review phase)

**Effort:** 15 minutes (4 phase-file edits, same template).

### TODO-WI-016 — Lint should detect exit-criterion pipe-masking patterns

**What:** Exit criteria like `cmd 2>&1 | head -30 && echo PASS` always pass because `head` exits 0. Real bug encountered during the first parallel run.

**Resolved (partially):** PHASE.md §Exit criteria now documents the hard rule. Commit: see git log.

**Remaining:** `tools/workflow_lint.py` should grep exit-criterion lines for `| (head|tail|grep|awk|cut|tee)\b` patterns (without `pipefail`) and warn. Strict mode could escalate to error.

**Effort:** 20 minutes (workflow_lint addition + tests).

### TODO-WI-017 — `markdownlint` vs `markdownlint-cli2` tool name mismatch

**What:** `UNIVERSAL-CONSTRAINTS.md` previously specified `npx markdownlint`, but the installed package is `markdownlint-cli2` (different binary name). Future orchestrators running the exit criterion verbatim would get `npm error could not determine executable to run` and silently pass if not careful.

**Resolved:** UNIVERSAL-CONSTRAINTS.md `spec` and `docs` profiles now specify `npx markdownlint-cli2` consistently with fallback to `--yes markdownlint-cli2@latest`. Commit: see git log.

---

## Tracking

When fixed, replace the severity emoji with ✅ and add a `Resolved:` line with the commit SHA. Or — if the protocol matures into a tool — wire these into `tools/workflow_lint.py` so the lint surfaces unresolved TODOs as warnings.
