# `sox-protocol chat` — interactive channels TUI

A Textual-based terminal UI for browsing channels, watching messages arrive in real time, and chatting with agents directly. Useful for debugging multi-agent flows and for one-off "send a message into a running system" tasks.

> Want to install SOX first? See [INSTALL.md](../INSTALL.md). For the integration contract see [USAGE.md](../USAGE.md).

---

## Quick start

Once SOX is installed (the `sox-protocol` entry-point is on `$PATH` after `pip install sox-protocol`):

```bash
# Point at your project's SQLite store and pick an identity
SOX_BACKING_STORE="sqlite:///$(pwd)/.sox/messages.db" \
  sox-protocol chat --agent-id $(whoami) --channel "group/design-review"
```

That's it. The TUI spawns its own SOX MCP server as a stdio subprocess — you don't need to start anything separately. Quit with `Ctrl+C`.

---

## Layout

The screen has three panes plus an input box:

```
┌──────────────┬─────────────────────────────────┬─────────────────┐
│  Channels    │  # group/design-review          │  Agents         │
│  ────────    │  ────────────────────────       │  ──────         │
│  > group/... │  [planner]  task: review ADR    │  • planner   ●  │
│    agent/me  │  [cto]      ack received        │  • cto-agent ●  │
│    test/...  │  [planner]  draft ready, …      │  • observer  ●  │
│              │                                 │                 │
└──────────────┴─────────────────────────────────┴─────────────────┘
│ > Type a message and press Enter                                 │
└──────────────────────────────────────────────────────────────────┘
```

| Pane | Contents |
|---|---|
| **Channels** (left) | All channels visible to your agent identity; arrow keys to navigate |
| **Messages** (center) | Scroll of messages on the focused channel, oldest at top |
| **Agents** (right) | Online agents (those with recent heartbeats) |
| **Input** (bottom) | Type a message + Enter to send to the focused channel |

---

## Flags

```bash
sox-protocol chat --help
```

| Flag | Default | Use |
|---|---|---|
| `--agent-id ID` | `tui-user` | Your identity in the channel — pick something distinctive (`nix`, `observer`, `qa-1`) |
| `--channel CHANNEL` | `#general` | Channel to focus on launch |
| `--no-spawn` | (off) | Attach to an already-running SOX server instead of spawning one |
| `--server-cmd CMD` | (auto) | Override the spawn command — useful when running against a non-default Python interpreter |

The TUI honors the same env vars as the MCP server itself — most importantly `SOX_BACKING_STORE` (which DB it talks to). See [USAGE.md §3](../USAGE.md#3-configuration-reference) for the full list.

---

## Two practical patterns

### 1. Watch a real two-agent conversation in real time

Open `sox-protocol chat` against the shared channel in one terminal, then run your agents (alice/bob, planner/cto-agent, etc.) in another. Their messages appear live in the TUI as they're sent. Great for debugging multi-agent flows — you see exactly what each agent sees, in order.

```bash
# Terminal 1
SOX_BACKING_STORE="sqlite:///$(pwd)/.sox/messages.db" \
  sox-protocol chat --agent-id observer --channel "group/design-review"

# Terminal 2 (or 3, 4…)
SOX_AGENT_ID=planner claude   # interactive
# or
SOX_AGENT_ID=cto-agent claude --print "..."   # scripted
```

### 2. Inject a message into a running multi-agent system

If your agents are subscribed to `agent/cto-agent` (or any channel), open `sox-protocol chat --agent-id user --channel agent/cto-agent`, type a question, hit Enter. The next time the target agent calls `mcp__sox__channels__recv`, it picks up your message. Two-way conversation with bots from a normal terminal — handy for steering long-running flows or asking ad-hoc questions.

---

## Connection model

The TUI is itself an MCP **client** — it speaks JSON-RPC to a stdio MCP server, the same way Claude Code does. Two modes:

- **Spawn mode (default).** The TUI launches its own `sox-mcp-server` subprocess on stdio. Each `sox-protocol chat` invocation gets its own server; multiple TUI windows pointing at the same `SOX_BACKING_STORE` see the same SQLite database, so messages flow between them. This is the simplest setup and what you want most of the time.
- **Attach mode (`--no-spawn`).** The TUI expects to find a SOX server already running on stdio (e.g. spawned by another supervisor process). Useful when you want a single long-lived server with multiple ephemeral TUI clients.

For the design rationale and trade-offs, see [docs/decisions/tui-connection-model.md](../decisions/tui-connection-model.md).

---

## Quick verification

```bash
# Send a message via TUI, then check the DB to confirm it landed
sqlite3 .sox/messages.db "
  SELECT seq, channel, sender, body
  FROM messages
  ORDER BY seq DESC
  LIMIT 5;
"
```

If your message is there, the wire works.

---

## Caveats

- **Requires a real TTY.** The TUI uses Textual's renderer; it fails silently in non-interactive contexts (CI scripts, redirected stdio). Use a real terminal — iTerm, Ghostty, default Terminal.app, etc.
- **Backing-store URL must point at a real path.** `sqlite:///` (three slashes) means an absolute path; `sqlite://./` means relative. Most issues come from mistyping these.
- **First connection takes 5–30 s.** Same MCP cold-start as Claude Code. The TUI shows a spinner — wait for the channel list to populate before typing.
- **Heartbeats are explicit.** The "Agents" pane only shows agents that have called `mcp__sox__channels__heartbeat` recently. Bots that don't heartbeat are invisible to the pane even if they're actively sending messages.

---

## Related

- [INSTALL.md](../INSTALL.md) — install + first-run guide
- [USAGE.md](../USAGE.md) — the integration contract, MCP tool reference, env vars
- [decisions/tui-connection-model.md](../decisions/tui-connection-model.md) — design rationale for the spawn/attach split
