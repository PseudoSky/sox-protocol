# Live E2E Tests

## What the live test does

`packages/python/tests/integration/test_live_install_e2e.py` exercises the
full install-to-messaging path using real Claude CLI subprocesses and a real
Anthropic API key. It:

1. Creates an isolated `python -m venv` under pytest's `tmp_path`.
2. `pip install -e packages/python plugins/sox-plugin-schema-strict` into it.
3. Copies `packages/python/tests/fixtures/live_install/` into a fresh tmp
   Claude project directory.
4. Runs `python -m sox_protocol.adapters.runtimes.claude_code install` against
   that project to produce `.mcp.json`, `.claude/settings.json`, and skill files.
5. Spawns two `claude` CLI subprocesses **serially** (alice then bob) with
   `--dangerously-skip-permissions --print --bare --model claude-sonnet-4-5
   --max-budget-usd 0.10`.
6. Asserts on the SOX SQLite database **structurally** — row counts and
   sentinel presence only; never message body text (LLM drift is not a defect).

The test is marked `@pytest.mark.live` and skipped by default in all regular
CI runs.

## Prerequisites

- Python 3.11 or 3.12
- The `claude` CLI installed globally: `npm install -g @anthropic-ai/claude-code`
- An Anthropic API key with access to `claude-sonnet-4-5`

## Running locally

```bash
# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# From the repo root
python3 -m pytest -m live \
  packages/python/tests/integration/test_live_install_e2e.py \
  -v --tb=short
```

To see subprocess output (useful for debugging agent transcripts):

```bash
python3 -m pytest -m live \
  packages/python/tests/integration/test_live_install_e2e.py \
  -v --tb=short -s
```

## Expected runtime and cost

| Resource | Expected value |
|----------|---------------|
| Wall time | 150 – 360 seconds |
| venv build | ~30 s (once per pytest session) |
| Per-agent Claude run | 60 – 150 s |
| Estimated API cost | $0.30 – $1.50 per full run |
| Model | `claude-sonnet-4-5` |
| Budget cap | `--max-budget-usd 0.10` per agent subprocess |

Cost is dominated by the two Claude subprocess runs. The `--max-budget-usd 0.10`
flag hard-caps spend per agent; if either agent approaches the limit, it stops
cleanly. Worst-case full run (both agents hit cap) is approximately $0.20
in direct subprocess spend, but realistic runs average higher due to input
tokens from the fixture and skill files.

## Authentication in CI vs local

**Local:** If you have a Claude.ai subscription and are authenticated via
`claude auth login` (OAuth/keychain), you do NOT need `ANTHROPIC_API_KEY`
set — `claude --print` will use your session.

**CI (and recommended for reproducibility):** The test subprocess command
always passes `--bare`, which forces strictly `ANTHROPIC_API_KEY`-based auth
and bypasses keychain/OAuth. Set `ANTHROPIC_API_KEY` in your environment
before running.

## CI trigger

The live test runs in `.github/workflows/python-live-e2e.yml` under these
conditions:

- Push to `main` (path-filtered to `packages/python/**`,
  `plugins/sox-plugin-schema-strict/**`, the test file, fixture dir, and
  the workflow file itself).
- Manual `workflow_dispatch` (includes a `debug_verbose` toggle for `-s` output).
- Weekly cron: Sunday 06:00 UTC (catches upstream `claude` CLI version drift).

The job is gated with `if: ${{ secrets.ANTHROPIC_API_KEY != '' }}` so forks
and PRs without the secret configured silently skip the job.

**The live test never runs on pull requests** — only on push to main and the
triggers above. This is intentional to contain API token spend.

## What the test asserts (and does not assert)

Asserted (structural, LLM-drift-resistant):

- `.sox/messages.db` exists and is non-empty after each agent run.
- `subscriptions` table contains a row for bob after his run.
- `messages` table contains at least one message from the session.
- All subprocess return codes are 0 within the 300 s timeout.
- Agent stdout contains the sentinel string (`ALICE_DONE` / `BOB_DONE`).

Not asserted (LLM-drift-prone):

- Exact message body text.
- Exact tool-call ordering.
- Whether the agent called non-SOX tools (Read/Bash/etc.).
- Token count below an exact threshold.

## Negative tests

The module also contains negative variants that verify broken install
configurations are detected:

- **NT-1 broken-mcp-server-name:** renames the `sox` server to `sox-broken` in
  `.mcp.json`; the test asserts the run fails or the DB stays empty.
- **NT-2 missing-skill-md:** deletes the SKILL.md file; asserts `groups` table
  row count is 0.

Without these, a passing positive test could be coincidental (e.g. if the
agent happened not to use SOX tools at all).

## Debugging a failing run

1. Pass `-s` to see full subprocess stdout/stderr interleaved with pytest output.
2. The test tees subprocess output to `<tmp_path>/artifacts/` — look there for
   full agent transcripts.
3. Inspect the SQLite DB directly:

```bash
sqlite3 /tmp/pytest-*/test_happy_path0/project/.sox/messages.db \
  "SELECT sender, json_extract(body, '$.type'), sent_at FROM messages ORDER BY sent_at"
```

4. Check `.mcp.json` and `.claude/settings.json` in the tmp project dir to
   verify the installer wrote the correct server config.
