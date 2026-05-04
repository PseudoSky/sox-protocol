# Installing SOX into a Claude Code project

A practical install + verify guide based on a real end-to-end run. Ten minutes, ~$0.20 of API spend if you exercise the live test.

> Looking for the formal usage reference instead? See [USAGE.md](./USAGE.md) for the integration contract, channel-naming convention, MCP tool reference, and configuration knobs.
>
> Want to browse channels and chat from a terminal? See [development/sox-chat.md](./development/sox-chat.md).

---

## Prerequisites

- Python 3.13+
- `claude` CLI (`claude --version` should print 2.x)
- A Claude Max/Team subscription (OAuth) **or** an `ANTHROPIC_API_KEY`
- An existing project with a `.claude/` directory (or any directory you'd like to make one in)

---

## 1. Install SOX into a venv

Pick the project you want to wire up — your `claude-agents` repo, or any implementation project.

```bash
cd /path/to/your/project
python3 -m venv .venv
source .venv/bin/activate

# Core: editable is fine
pip install -e /path/to/sox-protocol/packages/python

# Plugin: NON-editable
pip install /path/to/sox-protocol/plugins/sox-plugin-schema-strict
```

> ⚠️ **The plugin must be a non-editable install.** `pip install -e` on the plugin breaks because `sox-plugin.yaml` isn't declared as package data. The MCP server boots, then `sys.exit(1)`s on plugin-discovery handshake. Use plain `pip install`.

Once published to PyPI, the equivalent is:

```bash
pip install sox-protocol sox-plugin-schema-strict
```

Verify both packages are importable:

```bash
python -c "import sox_protocol, sox_plugin_schema_strict; print('ok')"
```

---

## 2. Wire SOX into your Claude Code project

```bash
python -m sox_protocol.adapters.runtimes.claude_code install --project-dir .
```

This writes (or updates):

| Path | What it does |
|---|---|
| `.mcp.json` | Registers the SOX MCP server for Claude Code |
| `.claude/settings.json` | Allows the `sox` server + adds `PostToolUse` and `Stop` hooks |
| `.claude/skills/inter-agent-channels/SKILL.md` | Reference doc Claude reads before using channels |
| `tools/sox-hooks/{post_tool_use,stop}.sh` | Cadence-enforcer hook scripts |

It also adds the bootstrap line to any `.claude/agents/*.md` files it finds — so existing subagents pick up channel awareness without manual edits.

Verify the install worked:

```bash
claude mcp list
# expected: sox: <python> -m sox_protocol.core.mcp_server - ✓ Connected
```

If you see `✗ Failed to connect`, the plugin probably wasn't installed correctly — see the gotcha in step 1.

The `sox-protocol` CLI is installed alongside as an entry-point script. Find it with:

```bash
which sox-protocol
# usually .venv/bin/sox-protocol after a venv install,
# ~/.local/bin/sox-protocol for --user installs.
```

> The bin is named `sox-protocol` (not `sox`) to avoid conflict with the long-established [SoX audio toolkit](http://sox.sourceforge.net/). The MCP server name in `.mcp.json` is still `sox` — that's a separate identifier and doesn't conflict with anything.

---

## 3. Try it interactively

In an interactive `claude` session inside the project:

```text
> /skill inter-agent-channels
> Use mcp__sox__channels__list_channels to show what's currently registered.
> Now mcp__sox__channels__send to channel "test/hello" with body {"text": "first message"}.
```

You're talking to a real SQLite-backed message store at `.sox/messages.db`.

Inspect it directly:

```bash
sqlite3 .sox/messages.db "SELECT channel, sender, body FROM messages;"
```

---

## 4. Two-agent dance (real subprocesses)

The point is to make agents like `cto-agent`, `planner`, `workflow-architect`, etc. talk to each other through SOX channels instead of through orchestrator-mediated SendMessage.

**Pattern:** each agent gets a stable identity. Set `SOX_AGENT_ID` when you spawn the subprocess. The `.mcp.json` config sets `SOX_AGENT_ID_SOURCE=claude_code_agent_name`, which falls back to the `SOX_AGENT_ID` env var when `CLAUDE_AGENT_NAME` isn't set (it isn't, in `--print` mode).

Minimal script that proves the wire:

```bash
# Agent 1: planner publishes a task
SOX_AGENT_ID=planner claude --print \
  --output-format stream-json --verbose \
  --max-budget-usd 1.00 \
  "Use mcp__sox__group__create with group_id='design-review'.
   Then mcp__sox__channels__send to channel 'group/design-review'
   with body={'task':'review ADR-0005','priority':'high'}.
   Print PLANNER_DONE and stop." \
  > planner.jsonl

# Inspect what landed
sqlite3 .sox/messages.db \
  "SELECT sender, body FROM messages WHERE channel='group/design-review';"

# Agent 2: cto-agent picks it up
SOX_AGENT_ID=cto-agent claude --print \
  --output-format stream-json --verbose \
  --max-budget-usd 1.00 \
  "Use mcp__sox__group__join with group_id='group/design-review'.
   Then mcp__sox__channels__recv with channels=['group/design-review'].
   Acknowledge what you received with mcp__sox__channels__ack on those messages.
   Print CTO_DONE and stop." \
  > cto.jsonl

# Verify the message was delivered
sqlite3 .sox/messages.db \
  "SELECT sender, body, delivered_to FROM messages WHERE channel='group/design-review';"
# delivered_to should now contain ["cto-agent"]
```

---

## 5. Wire your existing agents to use it

Two ways:

**Easy (recommended for first contact).** Append to each agent's `.claude/agents/<name>.md`:

```markdown
## Inter-agent communication

You are `<agent-name>`. Use the SOX channels MCP tools (`mcp__sox__channels__*`,
`mcp__sox__group__*`) to coordinate with other agents instead of waiting for
the orchestrator. See the `inter-agent-channels` skill for the protocol.

Subscribe to your inbox at startup:
  mcp__sox__channels__subscribe(channels=["agent/<your-name>"])

When you have a question for another agent:
  mcp__sox__channels__send(channel="agent/cto-agent", body={...},
                           reply_to=<msg_id>)
```

Then spawn the agent with `SOX_AGENT_ID=<name>` set.

**Strict.** Modify your orchestrator to pass `SOX_AGENT_ID` and rely on the bootstrap line that the installer added. The installer's `tools/sox-hooks/` handle inbox-cadence prompting automatically when the agent forgets to drain.

---

## 6. Useful debugging commands

```bash
# Watch the message log in real time
watch -n 1 'sqlite3 .sox/messages.db "
  SELECT seq, channel, sender, substr(body,1,40)
  FROM messages
  ORDER BY seq DESC
  LIMIT 10;
"'

# Browse interactively (channels list + message scroll + agents pane)
SOX_BACKING_STORE="sqlite:///$(pwd)/.sox/messages.db" \
  sox-protocol chat --agent-id $(whoami) --channel "group/design-review"

# Check who's subscribed
sqlite3 .sox/messages.db "SELECT * FROM subscriptions;"

# Get Claude Code's own MCP debug log
claude --debug-file /tmp/cc.log mcp list && grep -i sox /tmp/cc.log

# Reset state for a clean test
rm -rf .sox/

# Run the live e2e test (proves the same install path)
pytest -m live /path/to/sox-protocol/packages/python/tests/integration/test_live_install_e2e.py -v
```

---

## 7. Gotchas (from a real first-run)

1. **`pip install -e` on the plugin breaks** — use plain `pip install`. (See step 1.)
2. **MCP server cold-start is 5–30 s.** First `claude` invocation in a fresh project may report `still connecting`. Run `claude mcp list` once after install to warm the import cache; subsequent runs are fast.
3. **`--bare` blocks OAuth.** Use it only when you have `ANTHROPIC_API_KEY` set; otherwise drop it and let keychain auth work.
4. **`body` must be a JSON object, not a string.** `body="ping"` fails Pydantic validation; `body={"text":"ping"}` works. The schema-strict plugin enforces this end-to-end.
5. **`--output-format text` (default) hides tool calls and cost.** When scripting, use `--output-format stream-json --verbose` — it's the only format that emits per-event JSONL with `tool_use`, `tool_result`, and `total_cost_usd`.
6. **`SOX_AGENT_ID` is your friend.** Without it every agent ends up as `default` in the messages/subscriptions tables — you can't tell them apart.
7. **`group__invite` is in-memory only across processes.** The invitee won't find an invite message in their inbox; have them call `group__join` directly with the known `group_id`.

---

## 8. What to expect after install

- Cost per agent run (Sonnet 4.5, sensible prompt, ~5 turns): **$0.05–$0.20**
- Wall time: **20–40 s** (mostly model latency, not SOX overhead)
- DB state on disk: `.sox/messages.db` (SQLite WAL mode)
- All 33 v1 conformance fixtures pass on both stdio and HTTP transports

What you've verified by running this guide is the *install path*: that an unmodified Claude Code project, with the SOX adapter installed, can spawn real agents that communicate through the protocol with no hand-wired plumbing.

For the deeper integration contract, channel-naming conventions, and tool reference, see [USAGE.md](./USAGE.md). For interactive exploration, see [development/sox-chat.md](./development/sox-chat.md).
