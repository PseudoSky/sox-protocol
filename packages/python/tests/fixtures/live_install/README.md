# tests/fixtures/live_install — SOX Live Install E2E Fixture

## What this proves

This fixture is the skeleton project used by the SOX Protocol live end-to-end test
(`packages/python/tests/integration/test_live_install_e2e.py`, written in phase 03).

The test proves the full install-to-messaging path works with real Claude agents:

1. `pip install -e packages/python` + `pip install plugins/sox-plugin-schema-strict` into a fresh tmp venv.
2. `python -m sox_protocol.adapters.runtimes.claude_code install --project-dir <tmp_copy>` against a copy of this directory.
3. Spawn `claude --print` as alice (from the tmp project dir), running `prompts/alice_prompt.txt`.
4. Alice calls `mcp__sox__group__create`, `mcp__sox__group__invite`, `mcp__sox__channels__send`.
5. Spawn `claude --print` as bob, running `prompts/bob_prompt.txt`.
6. Bob calls `mcp__sox__channels__recv`, `mcp__sox__group__join`, `mcp__sox__channels__send`.
7. Assert the SOX SQLite database at `<tmp>/.sox/messages.db` contains the expected structural state.

Without this test, "SOX works on install" is an assumption. With it, it is a verified fact.

## Directory contents

```
live_install/
├── .claude/
│   ├── CLAUDE.md               # project-level guidance (minimal; installer adds the skill)
│   └── agents/
│       ├── alice.md            # alice agent definition (creator role)
│       └── bob.md              # bob agent definition (invitee role)
├── prompts/
│   ├── alice_prompt.txt        # imperative prompt passed via claude --print
│   └── bob_prompt.txt          # imperative prompt passed via claude --print
└── README.md                   # this file
```

What the installer adds to a **copy** of this directory at test time:

```
<tmp_copy>/
├── .mcp.json                   # MCP server entry (sox → python -m sox_protocol.core.mcp_server)
├── .claude/
│   ├── settings.json           # hooks (PostToolUse/Stop/SubagentStop) + allowedMcpServers
│   └── skills/
│       └── inter-agent-channels/
│           └── SKILL.md        # rendered discipline (tool names substituted)
└── tools/
    └── sox-hooks/              # hook shell scripts
```

## How the phase 03 test uses this fixture

```python
# Pseudocode — see test_live_install_e2e.py for the real implementation
tmp_project = tmp_path / "project"
shutil.copytree("tests/fixtures/live_install", tmp_project)
subprocess.run([venv_python, "-m", "sox_protocol.adapters.runtimes.claude_code",
                "install", "--project-dir", str(tmp_project)])

alice_result = subprocess.run(
    ["claude", "--dangerously-skip-permissions", "--print", "--bare",
     "--model", "claude-sonnet-4-5", "--max-budget-usd", "0.10",
     (tmp_project / "prompts/alice_prompt.txt").read_text()],
    cwd=tmp_project,
    env={**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path / ".claude_state"),
         "HOME": str(tmp_path / "home")},
    timeout=300,
)
# ... then bob, then assert_db_state(tmp_project)
```

## Prompt design rationale

Prompts are **imperative, not conversational**. Each step names the exact `mcp__sox__...`
tool. LLM drift on imperative prompts is markedly lower than on open-ended ones.

The sentinels (`ALICE_DONE` / `BOB_DONE`) let the test detect successful completion
by scanning stdout without parsing tool-call sequences.

Error sentinels (`ALICE_ERROR: ...` / `BOB_ERROR: ...`) are detected by the test to
distinguish "agent ran but SOX tools failed" from "agent didn't run at all".

## Tool names used (verified against register_tools() in phase 02 preflight)

All tool names were verified against `packages/python/src/sox_protocol/core/mcp_server/tools.py`
(`register_tools()`, lines 86–660) using `claude` CLI v2.1.126.

| Prompt step | Tool name |
|-------------|-----------|
| alice step 1 | `mcp__sox__group__create` |
| alice step 2 | `mcp__sox__group__invite` |
| alice step 3 | `mcp__sox__channels__send` |
| bob step 1 | `mcp__sox__channels__recv` |
| bob step 3 | `mcp__sox__group__join` |
| bob step 4 | `mcp__sox__channels__recv` |
| bob step 5 | `mcp__sox__channels__send` |

## Token budget per run

| Parameter | Value |
|-----------|-------|
| `--max-budget-usd` per agent | `$0.10` |
| Model | `claude-sonnet-4-5` |
| Prompt-level tool cap | 8 calls per agent |
| Subprocess timeout | 300s |
| **Estimated cost per full run** | **$0.05 – $0.30** (two agents, serial) |

Note: `--max-turns` does not exist in `claude` CLI v2.1.126. The plan's decision §4 used
`--max-turns 10` as a placeholder; phase 02 preflight confirmed it must be replaced with
`--max-budget-usd` + prompt-level instruction.

## CLI version compatibility

Verified against `claude` CLI v2.1.126 (Claude Code). Key flags:

- `--print` / `-p`: exists
- `--dangerously-skip-permissions`: exists
- `--bare`: exists (required in CI for ANTHROPIC_API_KEY-only auth — see preflight Q3)
- `--max-budget-usd`: exists (replaces the non-existent `--max-turns`)
- `--max-turns`: **does not exist** in v2.1.126

## Auth notes

On developer machines with a Claude.ai subscription, `claude --print` works via keychain
OAuth without `ANTHROPIC_API_KEY`. In CI, `--bare` must be passed alongside `ANTHROPIC_API_KEY`
because `--bare` disables keychain reads and requires explicit API key auth.

The phase 03 test is `@pytest.mark.skipif(not os.environ.get('ANTHROPIC_API_KEY'))`.
When that gate is satisfied (CI or local override), the test passes `--bare` unconditionally.

## Negative tests covered by phase 03

1. **broken-mcp-server-name**: rename `sox` → `sox-broken` in `.mcp.json` after install;
   alice's run must fail (empty `groups` table or non-zero exit).
2. **missing-skill-md**: delete `.claude/skills/inter-agent-channels/SKILL.md` after install;
   assert `groups` table row count == 0.
3. **missing-bootstrap-line** (soft): strip bootstrap line from agent `.md` files;
   log warning if run still succeeds (non-load-bearing diagnostic).

## Maintenance notes

If `register_tools()` in `tools.py` changes tool names, update the prompts in `prompts/`
AND the agent `.md` files in `.claude/agents/`. The tool name table above is the
authoritative cross-reference. Run `grep '@mcp.tool' packages/python/src/sox_protocol/core/mcp_server/tools.py`
to regenerate it.
