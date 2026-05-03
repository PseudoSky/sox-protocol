# live-install-e2e — implementation plan

Companion prose for `implementation-plan.json`. Section order matches the JSON keys.

---

## Decision 1 — Isolation strategy: tmp venv

**Choice:** Real `python -m venv` under pytest `tmp_path`.

**Rationale.** The Claude Code installer resolves discipline content via `importlib.resources.files("sox_protocol")` and the schema-strict plugin must be discoverable by the registry's entry-point scan. `pip install --target` plus `PYTHONPATH` injection is known-flaky for entry-points (the resolver expects a real `site-packages/*.dist-info`). Docker would force Docker-in-CI for what is fundamentally a Python-isolation problem; revisit only if the venv approach leaks Claude CLI state via `~/.claude` (mitigated below).

**Alternatives rejected.**

- `pip install --target <tmpdir>` — entry-point discovery flakiness; `claude` CLI's own resolution would still see the host site-packages.
- Docker container — overkill, slow (~60s per run), and the contributor experience for running the live test locally degrades.

**Implementation notes.**

- `venv.create(tmp_path/"venv", with_pip=True)` (stdlib, no uv bootstrapping order issues in CI).
- Resolve `<venv>/bin/python` and `<venv>/bin/pip` explicitly. Never rely on shell activation.
- Install order: `pip install -e packages/python` then `pip install plugins/sox-plugin-schema-strict`. Editable for the main package gives meaningful tracebacks.
- Override Claude state: `CLAUDE_CONFIG_DIR=<tmp>/.claude_home`, `HOME=<tmp>/home` for every Claude subprocess, so the test cannot pollute the developer's real session history or pick up cached auth.

---

## Decision 2 — Claude invocation: serial, --print, --dangerously-skip-permissions

**Command template:** `claude --dangerously-skip-permissions --print --model claude-sonnet-4-5 --max-turns 10 '<prompt>'`

**Parallelism:** serial (alice runs to completion, then bob runs to completion).

**Rationale.** STATE.md flags concurrent Claudes on one API key as the most likely flake source. The SOX messaging primitives don't require live concurrency — they're designed for drain-at-checkpoint. Serial is also dramatically easier to debug; a failure is unambiguous. Parallel mode is parked behind a `SOX_LIVE_PARALLEL=1` opt-in for future investigation; phase 03 must NOT enable it by default.

**Verification required in phase 02.** Run `claude --help` and confirm each flag exists on the CLI version targeted in CI. If `--max-turns` is not exposed at the CLI level, fall back to constraining inside the system prompt and assert turn-count from the captured transcript. Confirm `ANTHROPIC_API_KEY` env-var is sufficient (vs requiring `claude setup-token`).

**Subprocess shape.**

- transport: stdio (matches the default installer; HTTP transport is out of scope).
- stdin closed (via `--print`).
- stdout fully captured; tee to `<tmp>/artifacts/` for CI debug.
- stderr captured separately.
- timeout 300s per agent run.
- cwd is the tmp Claude project copy so `.mcp.json` and `.claude/settings.json` resolve from project-local paths.

---

## Decision 3 — Determinism

**What to assert (structural, LLM-drift-resistant):**

- `<project>/.sox/messages.db` exists and is non-empty after each run.
- After alice: 1 row in `groups`, 1 row in `group_members` (alice).
- Alice's transcript contains tool-use markers for the SOX send tool and a group-lifecycle tool.
- After bob: 2 rows in `group_members`; ≥1 outbound message row from bob.
- Final assertion: alice's inbox contains bob's message — verified by direct `SqliteStore` query, NOT by parsing alice's stdout.
- All subprocesses returncode 0 within timeout.
- Tool-call count from transcript ≤ token budget cap.

**What to NOT assert (LLM-drift-prone):**

- Exact message body text.
- Exact ordering of non-tool-call output lines.
- Whether the agent called non-SOX tools (Read/Bash/etc.); only that the SOX tool-set was exercised.
- Wall-clock duration (only that it stayed under timeout).
- Token count below an exact threshold (cap is enforced by `--max-turns`, not asserted post-hoc).

**Implementation.** Open the SQLite DB directly via stdlib `sqlite3` from the *test process* (NOT the freshly-installed venv), but reuse `SqliteStore` from the editable-installed `sox_protocol` to stay forward-compatible with schema migrations.

---

## Decision 4 — Token budget and cost

| Cap | Value |
| --- | --- |
| `--max-turns` per agent | 10 |
| `--max-tokens` per turn (model default) | ~4000 |
| Model | `claude-sonnet-4-5` |
| Subprocess timeout | 300s |
| Estimated cost band | **$0.30 – $1.50 per full run** |

Worst case: both agents hit the turn cap with full 4k output each → ~80k output tokens + ~40k input tokens ≈ $1.20 at sonnet-4-5 pricing (May 2026).

Phase 04 must record the realised cost from the first 5 CI runs and tighten this band in `REVIEW.md` before the engagement closes.

Enforcement layers (defense in depth):

1. CLI-level `--max-turns 10`.
2. System prompt instruction (`Stop after sending exactly one SOX message and a final summary`).
3. Subprocess timeout (300s).

---

## Decision 5 — Negative tests

Three negative variants run alongside the positive test. **Without these, a passing positive test could be a coincidence.**

### NT-1 — broken-mcp-server-name (load-bearing)

After install, mutate `<project>/.mcp.json` to rename the `sox` server to `sox-broken`. Re-run alice's prompt. The test MUST observe failure: returncode != 0 OR DB never gets a `groups` row OR transcript shows the tool unavailable. If the run somehow succeeds, raise `pytest.fail("negative test should have failed")`.

### NT-2 — missing-skill-md

Delete `<project>/.claude/skills/inter-agent-channels/SKILL.md` after install. Alice may not know which tools to call. Assert `groups` table row count == 0. (Returncode may or may not be non-zero; DB-state is the load-bearing assertion.)

### NT-3 — missing-bootstrap-line (soft)

Strip `BOOTSTRAP_LINE` from each `.claude/agents/*.md`. Without bootstrap, alice may not load the skill. Soft-assert: log a warning if the run still succeeds (this would tell us the bootstrap line is non-load-bearing for this prompt design — useful diagnostic signal, not a test failure).

---

## Phase 02 — fixture skeleton

Files to create under `tests/fixtures/live_install/`:

- `.claude/agents/alice.md`, `.claude/agents/bob.md` — minimal agent system-prompt files installed by the runtime.
- `.claude/CLAUDE.md` — project-level guidance (skill load order).
- `prompts/alice_prompt.txt`, `prompts/bob_prompt.txt` — the imperative prompts passed via `claude --print`.
- `README.md` — explains the fixture's purpose for future maintainers.

**Prompt design principles.**

- Imperative, not conversational. ("Call X" not "have a conversation about X.")
- Each prompt names the EXACT `mcp__sox__...` tool name. Phase 02 must cross-reference these with `register_tools()` in `core/mcp_server/tools.py` before the fixture is committed.
- Each prompt prints a sentinel (`ALICE_DONE` / `BOB_DONE`) so the test can detect successful completion without parsing tool sequences.
- Each prompt caps its own tool-call count, complementing CLI `--max-turns`.

**Open question for phase 02.** Is `group_create` a distinct MCP tool or is it expressed via `channels__send` to a control channel? The plan currently uses `group_create` as a placeholder; phase 02 MUST verify by inspecting `register_tools()` in `core/mcp_server/tools.py` before fixtures are committed.

---

## Phase 03 — test skeleton

`packages/python/tests/integration/test_live_install_e2e.py` (note: STATE.md references `tests/integration/...` but the canonical Python test root is `packages/python/tests/integration/`).

- Module-level `@pytest.mark.live` + `@pytest.mark.skipif(no API key)` + `@pytest.mark.skipif(no claude in PATH)`.
- Session-scoped `tmp_venv` fixture (built once per pytest invocation).
- Function-scoped `tmp_project` fixture that copies the fixture skeleton and runs the installer in the venv.
- `run_claude(prompt_path, project_dir, env_extras)` helper that wraps `subprocess.run` with the env overrides.
- `assert_db_state(project_dir, expected)` helper that reuses `SqliteStore` for forward-compat.
- Three tests: positive happy-path + the three negative variants.

Estimated runtime: 150 – 360s per pytest invocation (venv build ~30s once, two Claude runs 60–150s each, DB assertions <1s).

---

## Phase 04 — CI

**New workflow file:** `.github/workflows/python-live-e2e.yml` (separate from `python-ci.yml` because triggers, secrets, and cost profile all differ).

**Triggers:**

- push to `main` (paths-filtered to packages/python/**, plugins/sox-plugin-schema-strict/**, the test file, the fixture dir).
- `workflow_dispatch` (manual debug runs).
- weekly cron (Sunday 06:00 UTC) — catches upstream Claude CLI drift.

**Secret:** `ANTHROPIC_API_KEY`. Job condition: `if: secrets.ANTHROPIC_API_KEY != ''` — forks silently skip.

**Claude CLI install step:** placeholder `npm install -g @anthropic-ai/claude-code` then `claude --version`. Phase 04 must research and pin a specific CLI version.

**Marker registration:** append `"live: requires ANTHROPIC_API_KEY and the claude CLI; opts out by default"` to `packages/python/pyproject.toml` `[tool.pytest.ini_options]` markers.

**Default skip:** confirm `--strict-markers` + `@pytest.mark.live` means default `pytest` runs skip the tests automatically — no `-m 'not live'` flag needed.

---

## Phase 05 — review criteria

- Reviewer runs `pytest -m live` against current main with their own key. First-try pass required.
- Reviewer breaks `_MCP_SERVER_NAME` in `install.py` (e.g. 'sox' → 'sox-zzz') and confirms the test fails with a useful message.
- Reviewer collects realised $ cost from the API console and attaches to `REVIEW.md`.
- Reviewer confirms default `pytest packages/python/tests/` skips all live tests with no API key required.
- Reviewer reads agent prompts and verifies all named tools are real (no hallucinations).
- Reviewer verifies the workflow runs only on main + workflow_dispatch, NOT every PR.
- Reviewer adds ADR-0005 documenting why this live test exists and what it covers that in-process tests don't.

---

## Risks (summary — see JSON for full list)

1. **Claude CLI flag drift** → pin minimum version, smoke-check before each run.
2. **Per-minute rate limit even on serial** → 5s sleep between alice and bob; one retry on 429 with 60s backoff.
3. **Cost overrun on flaky retries** → workflow auto-retry = 0; failed runs comment on commit and a human decides.
4. **Claude CLI mutates `~/.claude`** → `CLAUDE_CONFIG_DIR` + `HOME` overrides per isolation strategy.
5. **schema-strict plugin entry-point not picked up** → smoke-test `load_plugins()` in the venv before the Claude run.
6. **Hypothetical tool names in prompts** → phase 02 pre-flight enumerates registered tools and aligns prompts.
7. **MCP server start with absolute python path** → installer already uses `sys.executable`; phase 03 verifies this resolves to the venv python.

---

## Open questions (phase 02 pre-flight)

1. Confirm `claude` CLI flags `--print`, `--dangerously-skip-permissions`, `--max-turns`, `--model` on the targeted CLI version.
2. Confirm registered MCP tool names — specifically whether `group_create` exists or whether group creation is expressed via `channels__send` to a control channel.
3. Confirm `ANTHROPIC_API_KEY` env-var is enough for non-interactive `claude --print` (vs needing `claude setup-token`).
4. Confirm `CLAUDE_CONFIG_DIR` is the correct env-var (vs `CLAUDE_HOME` or other).
