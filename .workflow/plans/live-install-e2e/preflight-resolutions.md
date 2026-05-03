# Preflight Resolutions — live-install-e2e phase 02

Resolved: 2026-05-03
CLI version under test: `2.1.126 (Claude Code)`

---

## Q1: Exact `claude` CLI flag set

**Verified by:** `claude --help 2>&1` (v2.1.126)

| Flag | Status | Notes |
|------|--------|-------|
| `-p` / `--print` | **EXISTS** | "Print response and exit (useful for pipes)" |
| `--dangerously-skip-permissions` | **EXISTS** | "Bypass all permission checks." |
| `--max-turns` | **DOES NOT EXIST** | Not present in v2.1.126 help output |
| `--model` | **EXISTS** | "Model for the current session. Provide an alias (e.g. 'sonnet' or 'opus') or full name" |
| `--max-budget-usd` | **EXISTS** | "Maximum dollar amount to spend on API calls (only works with --print)" |
| `--bare` | **EXISTS** | "Minimal mode: skip hooks, LSP, plugin sync... Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper via --settings" |

**Resolution for `--max-turns`:** No CLI-level turn cap exists. Use two complementary controls:
1. `--max-budget-usd 0.10` to cap dollar spend per agent run (works with `--print`)
2. Prompt-level instruction: "You have a budget of at most 8 tool calls. After completing the steps below, print your sentinel and stop immediately."

Phase 03 must use `--max-budget-usd` (not `--max-turns`) in the command template.
Updated command template: `claude --dangerously-skip-permissions --print --model claude-sonnet-4-5 --max-budget-usd 0.10 '<prompt>'`

---

## Q2: Real MCP tool surface — group creation

**Verified by:** `grep -n "@mcp.tool" packages/python/src/sox_protocol/core/mcp_server/tools.py`
**Source file:** `packages/python/src/sox_protocol/core/mcp_server/tools.py` lines 104–630

Full registered tool surface (server name = `sox`, so Claude Code prefix = `mcp__sox__`):

| Registered name | MCP tool name in Claude Code |
|-----------------|------------------------------|
| `channels__send` | `mcp__sox__channels__send` |
| `channels__recv` | `mcp__sox__channels__recv` |
| `channels__subscribe` | `mcp__sox__channels__subscribe` |
| `channels__unsubscribe` | `mcp__sox__channels__unsubscribe` |
| `channels__ack` | `mcp__sox__channels__ack` |
| `channels__heartbeat` | `mcp__sox__channels__heartbeat` |
| `channels__list_agents` | `mcp__sox__channels__list_agents` |
| `channels__replay` | `mcp__sox__channels__replay` |
| `channels__collect` | `mcp__sox__channels__collect` |
| `group__create` | `mcp__sox__group__create` |
| `group__invite` | `mcp__sox__group__invite` |
| `group__join` | `mcp__sox__group__join` |
| `group__leave` | `mcp__sox__group__leave` |
| `group__list_members` | `mcp__sox__group__list_members` |
| `channels__list_channels` | `mcp__sox__channels__list_channels` |

**Key correction from plan:** The plan used `group_create` (underscore separator) as a placeholder.
The real registered name is `group__create` (double underscore), giving the Claude Code tool name `mcp__sox__group__create`.
Agent prompts use `mcp__sox__group__create`, `mcp__sox__group__invite`, `mcp__sox__group__join`.

`group_create` is a **distinct MCP tool** (line 486: `@mcp.tool(name="group__create")`).
It is NOT expressed via `channels__send` to a control channel.

---

## Q3: `ANTHROPIC_API_KEY` authentication for non-interactive `claude --print`

**Verified by:** direct test: `timeout 30 claude --print "reply with just: OK"` returned `OK` (exit 0)
on a machine where `ANTHROPIC_API_KEY` is NOT set in the environment.

**Finding:** On this machine, auth works via the keychain/OAuth session (`claude auth status` shows
`"authMethod": "claude.ai"`, `"subscriptionType": "max"`). `claude --print` honors that session
without any `ANTHROPIC_API_KEY`.

**For CI (no keychain):** The `--bare` flag documentation explicitly states:
> "Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper via --settings (OAuth and keychain are never read)."

Therefore, in CI:
- `ANTHROPIC_API_KEY` env var alone IS sufficient when `--bare` is passed.
- Without `--bare`, Claude Code may attempt keychain reads that fail silently or prompt interactively.

**Recommendation for phase 03:** Use `--bare` in the test subprocess command when running in CI
(detected by `CI=true` env var). Locally, omit `--bare` to allow OAuth. Or always use `--bare`
with an explicit `ANTHROPIC_API_KEY` check (simpler, deterministic). The phase 03 test already
gates on `ANTHROPIC_API_KEY` being set; in that code path, always pass `--bare`.

**Cost note:** This resolution required one live API call (~10 tokens output). The response was
"OK" (3 chars). Estimated cost: < $0.001. Justified per phase 02 instructions.

---

## Q4: Correct Claude state-dir override env var

**Verified by:** binary string search (`strings $(which claude) | grep -i "claude_config\|claude_home"`)
and source reference in extracted binary JavaScript.

**Finding:** `CLAUDE_CONFIG_DIR` appears explicitly in the binary at multiple sites:
- The OMK function propagates `process.env.CLAUDE_CONFIG_DIR` into subprocess envs
- A comment in the binary reads "subprocess CLAUDE_CONFIG_DIR likely differs from parent (custom spawnClaudeCodeProcess / container?)"
- The `--bare` flag docs reference it as the config path

**`CLAUDE_HOME` was NOT found** in the binary's config-handling paths.

**Resolution:** Use `CLAUDE_CONFIG_DIR=<tmp>/.claude_state` (not `CLAUDE_HOME`) for state dir isolation
in phase 03 subprocess env. Also override `HOME=<tmp>/home` as a belt-and-suspenders measure
for any filesystem paths that fall back to `$HOME/.claude`.
