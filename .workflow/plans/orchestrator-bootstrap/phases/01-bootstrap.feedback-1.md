# Feedback for 01-bootstrap attempt 1

## Failed checks

1. **ruff check fails (F401):**
   ```
   F401 [*] `pytest` imported but unused
     --> tools/workflow_lint_tests/test_workflow_lint.py:18:8
   ```

2. **Coverage exit criterion uses `--cov=tools.workflow_lint`** but `tools/` is not a Python package, so the canonical importable name is `workflow_lint`. Pytest reports 0% coverage when invoked as `pytest tools/workflow_lint_tests/ --cov=tools.workflow_lint`.

3. **workflow_lint reports a hard ERROR for the `sox-protocol-current-state` engagement:**
   ```
   [ERROR] sox-protocol-current-state: [state_missing_file] STATE.md not found in engagement directory
   ```
   This engagement is the workflow-analyzer's read-only output. It has `status.md` and `analysis.md` but no `phases/` directory and no STATE.md by design — analyzer-only engagements never decompose. The lint tool must tolerate this case.

## Diagnosis

- (1) is a trivial unused-import.
- (2) and (3) compound: the phase's universal `code-python` exit criteria assume `tools.workflow_lint` is importable as a package, AND assume every engagement directory has STATE.md.

## Corrective instructions

Apply all three fixes:

1. **Remove the unused `pytest` import** from `tools/workflow_lint_tests/test_workflow_lint.py` (line 18). If the test file genuinely uses `pytest.raises` or fixtures elsewhere, keep the import; but if it's truly unused (per ruff), delete it.

2. **Make `tools.workflow_lint` importable as `tools.workflow_lint`** by adding an empty `tools/__init__.py`. This makes `tools/` a package without changing any runtime behavior, and lets the universal `code-python` exit criterion `--cov=tools.workflow_lint` work as written. Verify after: `python3 -m pytest tools/workflow_lint_tests/ --cov=tools.workflow_lint --cov-fail-under=100 -q` returns 100%.

3. **Update `tools/workflow_lint.py` check (i)** so engagements without a `phases/` directory are treated as analyzer-only and SKIP the STATE.md presence requirement. Specifically:
   - If `<plan_dir>/phases/` does not exist → emit a single INFO-level note ("analyzer-only engagement, no phase decomposition") and skip checks (i), (j), (l) for that engagement
   - The `sox-protocol-current-state` engagement should pass `--strict` after this change
   - Keep all other checks (frontmatter, etc.) for the engagement's `status.md` if a similar metadata check applies

After fixing, run all the original ACCEPTANCE checks. Report only the final state — what changed, what now passes.

## Hard constraints (unchanged from original prompt)

- 100% coverage on `tools/workflow_lint.py` (still required)
- mypy --strict still clean
- ruff check still clean (incl. the F401 fix)
- Lint runtime still <5s
- No changes to existing logic in hook scripts beyond the env-var guard already added
