---
phase_id: 01-bootstrap
title: Build lint tool, system prompt, hook opt-out
agent: python-pro
profile: code-python
estimated_effort: 1-2 days
prereqs: []
unblocks: []
parallelizable_with: []
writes: ["tools/workflow_lint.py", "tools/workflow_lint_tests/**", "tools/orchestrator_prompt.md", "tools/sox-hooks/**", ".github/workflows/workflow-lint.yml"]
reads:  [".workflow/**", "tools/sox-hooks/**"]
context_size: medium
---

# 01 — Bootstrap

## Objective

Ship three orchestrator-prerequisite artifacts in one specialist's pass:

1. **`tools/workflow_lint.py`** — validates internal consistency of `.workflow/`
2. **`tools/orchestrator_prompt.md`** — system prompt that loads the contracts as enforced rules for orchestrator sessions
3. **SOX hook opt-out** — env-var-gated short-circuit in the project hook scripts so orchestrator sessions running bash exit-criteria don't drown in inbox reminders

## Inputs

- `/Users/nix/dev/ai/sox-protocol/.workflow/templates/PHASE.md`
- `/Users/nix/dev/ai/sox-protocol/.workflow/templates/STATE.md`
- `/Users/nix/dev/ai/sox-protocol/.workflow/templates/ORCHESTRATOR-CONTRACT.md`
- `/Users/nix/dev/ai/sox-protocol/.workflow/templates/UNIVERSAL-CONSTRAINTS.md`
- `/Users/nix/dev/ai/sox-protocol/.workflow/plans/**` (the corpus to lint against)
- `/Users/nix/dev/ai/sox-protocol/tools/sox-hooks/post_tool_use.sh`
- `/Users/nix/dev/ai/sox-protocol/tools/sox-hooks/stop.sh`

## Prompt (verbatim)

```text
Build the SOX Protocol orchestrator-bootstrap toolset.

READ FIRST:
- .workflow/templates/PHASE.md
- .workflow/templates/STATE.md
- .workflow/templates/ORCHESTRATOR-CONTRACT.md
- .workflow/templates/UNIVERSAL-CONSTRAINTS.md
- .workflow/plans/ (sample several engagements to understand the corpus)
- tools/sox-hooks/post_tool_use.sh and stop.sh (current hook scripts)

DELIVER THREE THINGS:

═════════════════════════════════════════════════════════════════
1. tools/workflow_lint.py — internal-consistency validator
═════════════════════════════════════════════════════════════════

A Python script that scans .workflow/ and reports violations. Exit 0 on clean, non-zero on any violation.

Required checks:

  a. Every phase frontmatter has the required keys: phase_id, title, agent, profile, estimated_effort, prereqs, unblocks, parallelizable_with, writes, reads, context_size
  b. phase_id matches filename (modulo .md extension)
  c. Every prereqs[] entry is a phase_id that exists in the same engagement's phases/
  d. Every unblocks[] entry is a phase_id that exists in the same engagement's phases/
  e. Dependency DAG is acyclic per engagement
  f. profile is one of the documented values from UNIVERSAL-CONSTRAINTS.md
  g. agent is a non-empty string (cannot validate against the global agent registry without dispatch; warn-only if matches a known list)
  h. writes[] and reads[] are non-empty arrays of strings (warn if writes is empty for non-review profiles)
  i. STATE.md status table phase rows match the actual phases/ directory listing exactly (no orphans, no missing)
  j. STATE.md "Currently next action" references a phase that is actually status=READY in the table
  k. Every phase that cites another file in its Inputs section uses a path that exists (warn-only — paths may be future artifacts)
  l. RESERVATIONS contract: every planning-profile phase has a downstream consumer phase whose phase_id appears in the planner phase's exit criteria

Output format: human-readable summary + `--json` mode that emits a structured report orchestrators can parse.

CLI:
  workflow_lint.py [path]                # default: .workflow/
  workflow_lint.py --json                # machine-readable output
  workflow_lint.py --strict              # warnings become errors
  workflow_lint.py --engagement <slug>   # scope to one engagement

Tests at tools/workflow_lint_tests/ with 100% coverage. Cover at least:
  - clean corpus passes
  - missing prereqs phase fails
  - cyclic dependency fails
  - bad profile fails
  - frontmatter schema mismatch fails
  - JSON output validates as JSON

═════════════════════════════════════════════════════════════════
2. tools/orchestrator_prompt.md — orchestrator system prompt
═════════════════════════════════════════════════════════════════

A markdown system prompt designed to be loaded by Claude Code sessions invoked as "Run .workflow/plans/<slug>/STATE.md" or "Run .workflow orchestrator". It MUST:

  a. Load the four contracts as authoritative rules: PHASE.md (frontmatter shape + writes/reads + reservations), STATE.md (commit-trailer rules), ORCHESTRATOR-CONTRACT.md (full main loop, parallel mode, REVIEW recovery, dispatch constraints), UNIVERSAL-CONSTRAINTS.md (profile-specific exit criteria)
  b. Open with the orchestrator's identity statement: "You are the SOX workflow orchestrator. You drive engagements through their phase state machines per the contracts loaded below. You do NOT do the work yourself; you dispatch agents, verify their output, and mutate state."
  c. Encode the no-paraphrase rule, the agent_id-in-commits rule, the reservations capture protocol, and the parallel-batch glob-intersection algorithm as IMPERATIVES
  d. End with a startup checklist: pre-flight (working tree clean, tools available, run workflow_lint first), set SOX_ORCHESTRATOR_MODE=1 for the session, then enter main loop

The file is meant to be either:
  - cat'd into a Claude Code session as initial context: `claude "$(cat tools/orchestrator_prompt.md) Run .workflow/plans/<slug>/STATE.md"`
  - or referenced from a future shell wrapper: `tools/run-orchestrator.sh <slug>`

═════════════════════════════════════════════════════════════════
3. SOX hook opt-out
═════════════════════════════════════════════════════════════════

Modify tools/sox-hooks/post_tool_use.sh and tools/sox-hooks/stop.sh to honor the env var SOX_ORCHESTRATOR_MODE.

Add at the very top of each hook script (after shebang, before any other logic):

  if [ "${SOX_ORCHESTRATOR_MODE:-0}" = "1" ]; then
    exit 0
  fi

Document the env var in:
  - tools/sox-hooks/README.md (new or updated) — briefly: "Set SOX_ORCHESTRATOR_MODE=1 to disable enforcer hooks for the current session. Used by the workflow orchestrator to suppress inbox reminders during automated exit-criterion verification."
  - tools/orchestrator_prompt.md — startup checklist instructs setting it
  - .workflow/templates/ORCHESTRATOR-CONTRACT.md — add a one-line note in pre-flight: "Set SOX_ORCHESTRATOR_MODE=1 in the orchestrator's shell environment so SOX cadence-enforcer hooks don't re-inject inbox reminders during bash exit-criterion runs."

═════════════════════════════════════════════════════════════════
4. CI integration
═════════════════════════════════════════════════════════════════

Add .github/workflows/workflow-lint.yml: runs python tools/workflow_lint.py --strict on every PR that touches .workflow/. Fails the build on violation.

═════════════════════════════════════════════════════════════════

HARD CONSTRAINTS:

- 100% line coverage on tools/workflow_lint.py
- mypy --strict clean on the lint tool
- ruff check clean
- The lint tool must run in <5s against the current corpus (12 engagements, 30 phases)
- Hook script changes are additive only — do not modify existing logic, only prepend the env-var check
- orchestrator_prompt.md is plain markdown, no executable code

ACCEPTANCE (self-check):
- [ ] python tools/workflow_lint.py exits 0 against current .workflow/
- [ ] python tools/workflow_lint.py --strict exits 0
- [ ] All workflow_lint_tests pass with 100% coverage
- [ ] mypy --strict tools/workflow_lint.py passes
- [ ] tools/orchestrator_prompt.md exists, references all four templates verbatim or by include
- [ ] grep -q SOX_ORCHESTRATOR_MODE tools/sox-hooks/post_tool_use.sh AND tools/sox-hooks/stop.sh
- [ ] SOX_ORCHESTRATOR_MODE=1 hooks exit immediately (test by running the hook with the env var)
- [ ] .github/workflows/workflow-lint.yml exists and is valid yaml

REPORT: ≤ 250 words. Lint check count, lint runtime, orchestrator-prompt total length in tokens, hook-opt-out test result.
```

## Exit criteria

Universal (`code-python`):
- [ ] `python3 -m pytest tools/workflow_lint_tests/ --cov=tools.workflow_lint --cov-fail-under=100 -q`
- [ ] `mypy --strict tools/workflow_lint.py`
- [ ] `ruff check tools/workflow_lint.py tools/workflow_lint_tests/`
- [ ] `! grep -rE '(SECRET|PASSWORD|API_KEY)\s*=\s*["\047][^"\047]+' tools/workflow_lint.py`

Engagement-specific:
- [ ] `python3 tools/workflow_lint.py --strict` exits 0 against `.workflow/`
- [ ] `python3 tools/workflow_lint.py --json` produces valid JSON: `python3 tools/workflow_lint.py --json | python3 -c "import json,sys; json.load(sys.stdin)"`
- [ ] `test -f tools/orchestrator_prompt.md`
- [ ] `grep -q SOX_ORCHESTRATOR_MODE tools/sox-hooks/post_tool_use.sh && grep -q SOX_ORCHESTRATOR_MODE tools/sox-hooks/stop.sh`
- [ ] Hook opt-out works: `SOX_ORCHESTRATOR_MODE=1 echo '{}' | bash tools/sox-hooks/post_tool_use.sh; test $? -eq 0`
- [ ] `test -f .github/workflows/workflow-lint.yml && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/workflow-lint.yml'))"`
- [ ] Lint runtime < 5s: `start=$(date +%s); python3 tools/workflow_lint.py >/dev/null; end=$(date +%s); test $((end - start)) -lt 5`

## Outputs

- `tools/workflow_lint.py`
- `tools/workflow_lint_tests/`
- `tools/orchestrator_prompt.md`
- Modified `tools/sox-hooks/{post_tool_use,stop}.sh`
- `tools/sox-hooks/README.md` (new or updated)
- `.github/workflows/workflow-lint.yml`
- One-line note appended to `.workflow/templates/ORCHESTRATOR-CONTRACT.md` (pre-flight section)

## Next state

Leaf. Engagement complete on DONE.

## Notes

This engagement is RUN FIRST. The lint tool catches cross-reference bugs before they bite at runtime. The orchestrator system prompt is what makes "Claude Code is the orchestrator" reproducible across sessions. The hook opt-out is the only way orchestrator sessions can execute bash exit criteria without drowning in cadence-enforcer reminders.

The engagement does NOT add hard prereqs to the other 12 — those continue to be dispatchable independently. But running them WITHOUT this bootstrap means the orchestrator either spams inbox reminders, fails to lint the corpus, or has to re-derive its own discipline from the templates each time.

Mark this `priority: critical` and run it first. Half a day to a day of work; permanent leverage.
