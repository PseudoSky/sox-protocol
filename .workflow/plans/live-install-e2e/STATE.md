---
slug: live-install-e2e
target: One end-to-end test that proves the full install→messaging path works. Steps: pip install SOX into temp dir → run claude_code installer against a fresh project → spawn 2 real Claude subprocesses → have them create a group, invite, join, exchange messages → assert delivery via SOX server. Gated on ANTHROPIC_API_KEY so CI can opt out, but CRITICAL for "we know v1 actually works on install" claim.
created: 2026-05-04
last_event: 2026-05-04T00:00:00Z
orchestrator_protocol: v1
parent_plan: plugin-architecture (post-v1-program follow-on)
prereqs: []  # all P1–P6 closed; can run in parallel with fixture-spec-realignment
priority: HIGH — without this, "v1 works on install" is an assumption
---

# live-install-e2e — engagement state

## Status

| Phase | Title | Status | Agent | Attempts | Last touched |
|---|---|---|---|---|---|
| 01-plan | Design the test: isolation strategy (tmp venv vs Docker vs --target), Claude invocation pattern (`--dangerously-skip-permissions`?), agent prompt design (deterministic enough for assertions), API key handling, CI gate strategy. Decide stdio vs HTTP transport for the live test (probably stdio — matches default install). | `DONE` | sox-cto-system:planner | 1 | 2026-05-03T00:00:00Z |
| 02-build-fixture | Construct the test fixture: a fresh-Claude-Code-project skeleton checked into `tests/fixtures/live_install/` with `.claude/` dir, agent .md files for two roles ("alice" + "bob"), prompts that deterministically drive: create_group → invite → join → send → recv → ack. Prompts must be robust to LLM variation (e.g. instruct exact tool calls, not "have a chat"). | `READY` | test-automator | 0 | 2026-05-03T00:00:00Z |
| 03-build-test | `tests/integration/test_live_install_e2e.py`: pytest test that (a) creates tmp venv (b) `pip install -e packages/python plugins/sox-plugin-schema-strict` into it (c) runs `python -m sox_protocol.adapters.runtimes.claude_code.install` against a tmp Claude project copy (d) spawns 2 `claude` CLI subprocesses with the agent prompts (e) waits for them to complete (f) asserts the SOX SQLite database contains the expected message rows + ack records. Test marked `@pytest.mark.live` and `@pytest.mark.skipif(not ANTHROPIC_API_KEY)`. | `BLOCKED` | test-automator | 0 | 2026-05-04T00:00:00Z |
| 04-ci-integration | Add the `live` marker to `pyproject.toml` `[tool.pytest.ini_options]` markers. Add a CI job (separate from the main test job) that runs `pytest -m live` if `ANTHROPIC_API_KEY` secret is configured. Document opt-in path in README. | `BLOCKED` | devops-engineer | 0 | 2026-05-04T00:00:00Z |
| 05-review | Verify the test reliably passes against the current main + that failures genuinely catch broken installs (e.g. break the installer deliberately and confirm the test fails). | `BLOCKED` | code-reviewer | 0 | 2026-05-04T00:00:00Z |

## Currently next action

Phase 01-plan is **DONE** (2026-05-03). Plan artifacts:

- `.workflow/plans/live-install-e2e/implementation-plan.json`
- `.workflow/plans/live-install-e2e/implementation-plan.md`

Dispatch **phase 02-build-fixture** next (test-automator). Phase 02 pre-flight MUST resolve four open questions before fixtures are committed (see `implementation-plan.json#open_questions_for_phase_02_pre_flight`):

1. Confirm `claude` CLI flags (`--print`, `--dangerously-skip-permissions`, `--max-turns`, `--model`) on the targeted CLI version.
2. Confirm registered MCP tool names — specifically whether `group_create` exists or group creation goes through `channels__send` to a control channel. Inspect `core/mcp_server/tools.py:register_tools()`.
3. Confirm `ANTHROPIC_API_KEY` env-var alone authenticates non-interactive `claude --print`.
4. Confirm correct Claude state-dir env-var (`CLAUDE_CONFIG_DIR` vs `CLAUDE_HOME`).

---

## Phase 01 decision summary

1. **Isolation:** real `python -m venv` under tmp_path; reject `--target` (entry-point flakiness) and Docker (overkill). Override `CLAUDE_CONFIG_DIR` + `HOME` to prevent host-state pollution.
2. **Invocation:** `claude --dangerously-skip-permissions --print --model claude-sonnet-4-5 --max-turns 10`, **serial** (alice then bob); parallel parked behind `SOX_LIVE_PARALLEL=1` opt-in.
3. **Determinism:** assert structural DB state (row counts, schema invariants) and tool-use markers in transcript; never assert message body text or non-tool output.
4. **Token budget:** 10 turns × 4k tokens × 2 agents → estimated **$0.30–$1.50 per run**, sonnet-4-5. Cap enforced by CLI `--max-turns` + prompt instructions + 300s subprocess timeout.
5. **Negative tests:** three variants — broken MCP server name (load-bearing), missing SKILL.md (load-bearing), missing bootstrap line (soft/diagnostic).

CI: new `python-live-e2e.yml` workflow on push-to-main + weekly cron + workflow_dispatch, gated on `secrets.ANTHROPIC_API_KEY`. NOT triggered on PRs.

---

## Original critical decisions for the planner (preserved for audit)

1. **Isolation strategy.** Three options:
   - (a) `pip install --target <tmpdir>` + `PYTHONPATH` injection — fastest, but leaks `claude` CLI's own resolution
   - (b) Real `python -m venv <tmpdir>` + activate + install — clean isolation, slower (~30s per test)
   - (c) Docker container — most isolated, requires Docker in CI
   
   Recommend (b) for unit-level isolation; (c) only if (b) leaks Claude CLI globals.

2. **Claude invocation.** `claude --dangerously-skip-permissions --print "<prompt>"` produces non-interactive output. Need to confirm whether two simultaneous Claude processes can coexist on one machine without rate-limit conflict. Plan for serial fallback if parallel fails.

3. **Determinism.** LLMs are non-deterministic. The test must NOT assert on exact message content; it must assert:
   - The right SOX tools were called (group_create, group_invite, group_join, send, recv, channels__ack)
   - The right number of messages flow
   - Acks are received within a reasonable timeout
   - Final SQLite state matches a structural template (count of rows in each table)
   
   Avoid asserting on message body text — that's where LLM drift creates flaky tests.

4. **API cost.** Each test run burns tokens. Plan for a token budget per run (e.g. each agent gets max 10 turns, max 4k tokens per turn). Document expected cost.

5. **Failure modes the test must catch.** Negative tests where the installer is deliberately broken (e.g. wrong MCP server name in `settings.json`) should make the test fail with a useful message. Without this, the test could pass for the wrong reason.

## Termination targets

- [ ] All 5 phases DONE
- [ ] `tests/integration/test_live_install_e2e.py` exists and passes against current main when `ANTHROPIC_API_KEY` is set
- [ ] Test isolated (tmp venv) — does not contaminate dev venv
- [ ] Test marked `@pytest.mark.live` so default `pytest` skips it
- [ ] CI job exists for the live test gated on `ANTHROPIC_API_KEY` secret presence
- [ ] Negative test confirmed: deliberately breaking the installer (wrong MCP path in settings.json) makes the test fail with a useful message
- [ ] Documented in README: how to run the live test locally with own API key
- [ ] Token budget per run documented (estimated cost per CI run)

## Risk register

- **Claude CLI rate limits.** Two concurrent Claudes from one API key may hit per-minute limits. Mitigation: serialize the agents (alice acts → bob acts) instead of true concurrency; the messaging primitives don't require concurrent live agents to be exercised.
- **Claude CLI tooling shifts.** The `claude` CLI evolves. The test must declare its required CLI version range. Pin or test against multiple recent versions.
- **Flakiness from LLM drift.** Mitigated by structural assertions only (counts, table state) rather than content matching.
- **CI cost.** ~$0.50–$2 per run depending on model. Justify by running on PR merge to main only, not every PR.

## Reference

- Surfaced: this conversation's audit ("Have we written live claude e2e tests..." question)
- Existing reference points:
  - `examples/two-agent-clarification/run_demo.py` — has a documented but unverified `SOX_LIVE_TEST=1` opt-in
  - `tests/integration/test_two_agent_exchange.py` lines 21–22: documents but doesn't implement live path
  - `tests/adapters/runtimes/test_claude_code_install.py` — proves the installer file artefacts; doesn't prove the install actually works at runtime
- ADR opportunity: ADR-0005 "Live e2e testing strategy" — document why deterministic in-process tests are insufficient and what the live test covers that they don't
