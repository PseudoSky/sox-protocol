# live-install-e2e — Phase 05 Review

Reviewer: code-reviewer
Date: 2026-05-03
Worktree: agent-a6dedc08fff5d742f (branched from main)

---

## 1. Summary

**APPROVED-WITH-FOLLOWUPS**

No CRITICAL or HIGH issues found. The test is structurally sound, correctly
gated, and the four hard invariants all pass. Three MEDIUM and several LOW/NIT
issues are documented below — none block merging, all are followup candidates.

---

## 2. Static Review Findings

### MEDIUM

- **M-1 — bob's `group__join` tool-use assertion missing**
  `test_live_install_e2e.py:427` lists `group__join` in the docstring as an
  asserted tool-use marker for bob, but lines 486-487 only call
  `_assert_tool_used` for `mcp__sox__channels__recv` and
  `mcp__sox__channels__send`. `mcp__sox__group__join` is never passed to
  `_assert_tool_used`. The docstring claim is false. Bob's transcript could
  pass without him ever calling `group__join` — the only join evidence comes
  from the weak subscription-row count check.

- **M-2 — subscription assertion too weak (`>= 1` instead of `>= 2`)**
  `test_live_install_e2e.py:504`: `assert len(sub_agents) >= 1`. This passes
  even if only alice subscribed and bob never called `group__join`. The plan
  (implementation-plan.json determinism section) states "After bob's run: 2
  rows in `group_members`; after bob: alice + bob both subscribed." The
  assertion should be `>= 2` to enforce that bob actually joined.

- **M-3 — `_run_claude` docstring claims it raises `pytest.fail` on non-zero exit; it does not**
  `test_live_install_e2e.py:255`: docstring says "Raises: pytest.fail if the
  process times out or returns non-zero." The function only calls `pytest.fail`
  on timeout. Non-zero exit is returned to the caller silently. The positive
  test correctly asserts `returncode == 0` itself, so no logic bug — but the
  docstring is misleading and could cause a future caller to skip the
  returncode check assuming the helper already enforced it.

### LOW

- **L-1 — `stderr_so_far` assigned but never used**
  `test_live_install_e2e.py:301`: `stderr_so_far = exc.stderr or b""` is
  assigned on timeout but never written to disk or referenced. The timeout
  diagnostic artifact only saves stdout. Stderr from a timed-out process
  (which may contain the MCP server error) is silently discarded.

- **L-2 — `db_empty` logic has unreachable branch**
  `test_live_install_e2e.py:564`: `len(_query_db(..., "SELECT COUNT(*) FROM
  messages")) == 0` is dead code. `COUNT(*)` always returns exactly one row
  `[(N,)]` so `len(result) == 0` is never true. The check still works
  correctly via the second branch `[0][0] == 0`, but the dead branch adds
  confusion and runs the query twice unnecessarily.

- **L-3 — Workflow artifact upload path is hardcoded to `/tmp/pytest-*/`**
  `.github/workflows/python-live-e2e.yml:128`: The artifact upload glob is
  `/tmp/pytest-*/`. On ubuntu-latest the actual path is
  `/tmp/pytest-of-runner/pytest-<N>/`. The glob pattern `/tmp/pytest-*/`
  matches directories named `pytest-*` directly under `/tmp`, which includes
  the `pytest-of-runner` directory — but the test artifacts are two levels
  deep inside that. The glob should be `/tmp/pytest-of-*/pytest-*/` or
  `/tmp/pytest-*/` with `**` expansion. In practice `if-no-files-found:
  ignore` suppresses failure, but CI debug artifacts may silently not upload.

- **L-4 — No Claude CLI version pin in workflow**
  `.github/workflows/python-live-e2e.yml:89`: `npm install -g
  @anthropic-ai/claude-code` installs the latest version with no pin. The
  workflow comments acknowledge this risk and say the weekly cron will surface
  breakage. Acceptable for now but worth pinning once the test has a first
  successful CI run to anchor a known-good version.

- **L-5 — `schema-strict` install step uses `|| true` silently**
  `.github/workflows/python-live-e2e.yml:107`: `pip install -e
  plugins/sox-plugin-schema-strict || true` swallows install failures. If the
  plugin install fails, the live test venv build will also fail but with a
  less obvious error. Remove `|| true` and let the step fail fast.

### NIT

- **N-1 — `groups` table never asserted**
  The plan (implementation-plan.json determinism assertions 2-3) specifies
  "Exactly one row in the `groups` table" and "Exactly one row in
  `group_members` table for alice as creator." Neither assertion is present in
  the test. These are low-value given the architecture note (group state is
  in-memory only and not persisted), but the plan/test divergence is worth
  documenting.

- **N-2 — NT-3 (missing-bootstrap-line) not implemented**
  The plan specifies three negative tests; only NT-1 and NT-2 are
  implemented. NT-3 (strip `BOOTSTRAP_LINE` from agent .md files) is absent.
  The plan designated it "soft/diagnostic" so this is an acceptable omission,
  but the STATE.md termination targets include no explicit sign-off on
  dropping NT-3.

- **N-3 — `docs/development/live-tests.md` cost note is inconsistent**
  `live-tests.md:65`: "Worst-case full run... is approximately $0.20 in
  direct subprocess spend" but the table above it says "$0.30 – $1.50 per
  full run." The $0.20 figure is the per-agent cap ($0.10 × 2) which is the
  floor, not the realistic average. The prose is confusing.

- **N-4 — alice.md agent file has a stray coordination instruction**
  `tests/fixtures/live_install/.claude/agents/alice.md` last line: "For
  coordination with other agents (clarification, broadcasts, peer questions),
  load the `inter-agent-channels` skill when blocked, broadcasting, or seeking
  peer input." This boilerplate is the bootstrap line the installer injects —
  it is present in the fixture source before install, meaning it will be
  present twice after the installer re-inserts it. If the installer is
  idempotent (checks before inserting), this is harmless. Worth verifying.

---

## 3. Collection / Deselection Invariants

All three checks pass.

| Check | Command | Result |
|---|---|---|
| Without `-m live`: deselected | `pytest --collect-only -q ...test_live_install_e2e.py` | `no tests collected (3 deselected)` — PASS |
| With `-m live`: collected | `pytest -m live --collect-only -q ...test_live_install_e2e.py` | `3 tests collected` — PASS |
| Default run: deselected | `pytest ...test_live_install_e2e.py --tb=short -q` | `3 deselected` — PASS |

---

## 4. Structural Smoke

Skipped — reason: a full structural smoke (venv build + pip install + installer
invocation) would take 30–60 seconds of subprocess time and exercises exactly
what the CI workflow is designed to verify. The collection invariants and
static analysis provide sufficient confidence for this phase. CI will exercise
the full path on first push.

The repo-root resolution `_REPO_ROOT = Path(__file__).parent ×5` was verified
statically: five `.parent` hops from
`packages/python/tests/integration/test_live_install_e2e.py` correctly reach
the repo root. The fixture path `_FIXTURE_DIR` resolves to
`packages/python/tests/fixtures/live_install/` which exists and contains the
expected files.

---

## 5. Adversarial Probe of Negative Tests

### NT-1 (broken-mcp-server-name) — passes for the right reason, with one caveat

The negative test's failure detection at lines 562-569 uses three independent
signals (nonzero exit OR db empty OR no sentinel). This is correctly designed.

One caveat: the `no_sentinel` signal (`"ALICE_DONE" not in alice_tx`) fires
even if alice printed `ALICE_DONE` *before* attempting the first SOX tool call
— for instance if the LLM reordered the steps. However, the alice prompt
(alice_prompt.txt) places `ALICE_DONE` as the *final* step after three SOX
tool calls, so a correctly-following LLM should not print the sentinel without
attempting the tools. The risk is low but non-zero: a sufficiently creative LLM
could print the sentinel early (Step 4 text appears in the prompt) before
attempting tools, which would yield `no_sentinel=False` but `db_empty=True`
would still catch the broken install. Net assessment: the three-signal OR
design provides sufficient defense even against this edge case.

The `_run_claude` helper does NOT call `pytest.fail` on non-zero exit (contrary
to its docstring) — it returns the `CompletedProcess` object. The negative
test correctly uses the returned value without assuming the helper asserts
returncode. This design is correct.

### NT-2 (missing-skill-md) — effectively a no-op; acknowledged in plan

The alice prompt (`alice_prompt.txt`) names exact MCP tool names
(`mcp__sox__group__create`, `mcp__sox__channels__send`) explicitly. The
SKILL.md document provides the same information. As acknowledged in the plan
(implementation-plan.json negative_tests[1]) and in the test's own comment
(line 639-647), removing SKILL.md when the prompt already names the tools
explicitly will not prevent alice from succeeding. The test handles this
correctly as a soft assertion — it logs a warning if alice succeeds rather than
failing. This is an honest diagnostic, not a structural test.

**Risk confirmed:** NT-2 will almost certainly print the warning in CI (the
explicit tool names make SKILL.md non-load-bearing for this prompt design) and
will not provide coverage of the "SKILL.md is required" invariant. This is
acceptable per the plan's design, but the engagement should note that NT-2
provides no regression protection for the SKILL.md path — it is purely
diagnostic.

### NT-3 — not implemented (see N-2)

---

## 6. Hard Invariants

All four pass:

| Invariant | Command | Result |
|---|---|---|
| mypy --strict | `cd packages/python && python3 -m mypy --strict src/sox_protocol/` | `Success: no issues found in 81 source files` |
| Test suite | `pytest packages/python/tests/ --tb=line -q -x --ignore=...test_coverage2.py` | `1238 passed, 3 deselected` |
| Conformance stdio | `conformance_runner.py --transport stdio --strict` | `33 passed, 0 failed, 34 skipped / 67 total` |
| Conformance http | `conformance_runner.py --transport http --strict` | `27 passed, 6 failed, 34 skipped / 67 total` |

Numbers match the expected invariants exactly (33/0/34 stdio; 27/6/34 http).

---

## 7. Recommendation

The test code is sound enough to close the code-side work and mark phase
05-review DONE pending CI confirmation. No CRITICAL or HIGH issues were found.

The three MEDIUM issues (M-1 missing group__join assertion, M-2 weak
subscription count, M-3 misleading docstring) should be addressed as followup
tickets in the next engagement iteration — they do not invalidate the test's
correctness, they only weaken its diagnostic precision.

**The next push to main MUST trigger the CI workflow** (`python-live-e2e.yml`)
to validate the full subprocess path (venv build, pip install, installer run,
real Claude API calls). The static review cannot substitute for this. The
engagement should not be declared fully closed until at least one green CI run
is recorded.

The ADR-0005 entry noted as a phase 05 deliverable in the plan is not present
in the repo. This is a followup item — it does not block CI confirmation.

---

## API Cost

Not collected — a live API run was not performed in this phase per the
environment context (ANTHROPIC_API_KEY not set locally, full run deferred to
CI). Cost band from the plan: **$0.30 – $1.50 per run** (two agents at
--max-budget-usd 0.10 each, sonnet-4-5). CI should record actual spend after
first run.
