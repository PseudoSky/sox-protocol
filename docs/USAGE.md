# SOX Protocol — Usage

This document is the consuming-end guide: how to integrate SOX Protocol into a Claude Code project, the configuration reference, worked use cases, anti-patterns, and troubleshooting.

> **Looking for a hands-on walkthrough?** See [INSTALL.md](./INSTALL.md) for a copy-paste install + verify guide based on a real run, and [development/sox-chat.md](./development/sox-chat.md) for the interactive TUI.

The Python reference implementation under `packages/python/` is SOX v1.0-compliant (33/33 conformance fixtures pass on both stdio and HTTP transports). `packages/typescript/` and `packages/rust/` remain placeholder directories — see [the README](../README.md) for the conformance bar.

---

## 1. Quickstart (Claude Code)

### 1.1 Install

From your project root:

```bash
pip install sox-protocol sox-plugin-schema-strict
sox-protocol install
```

> **Gotcha:** install `sox-plugin-schema-strict` **non-editable** (no `-e`). The plugin's `sox-plugin.yaml` manifest is not exposed via editable installs, and the MCP server fails its plugin-discovery handshake without it. If `claude mcp list` reports `✗ Failed to connect`, this is almost always the cause.

This:

- Reads the canonical discipline from the bundled `spec/discipline/discipline.md` (shipped inside the Python package).
- Writes `inter-agent-channels/SKILL.md` into `.claude/skills/`.
- Writes hook scripts to `tools/sox-hooks/`.
- Updates `.claude/settings.json` with the MCP server registration and hook bindings.
- **Adds all 15 SOX MCP tool names to `permissions.allow`** so agents can call them without per-call approval prompts.  Pass `--no-permissions` to skip this injection.  See [INSTALL.md § Tool permissions](./INSTALL.md#tool-permissions-auto-injected) for the full list and rationale.
- Initialises the SQLite backing store at `.sox/messages.db`.

#### Optional: auto-subscribe activation

By default `SKILL.md` is **descriptive** — it teaches the protocol but doesn't take action when an agent loads it. Pass `--auto-subscribe` to make the skill *active*:

```bash
sox-protocol install --auto-subscribe \
  --channel team/eng \
  --channel broadcast/announcements
```

The installed `SKILL.md` then ends with an **Activation (auto-subscribe)** section that instructs the LLM to, on first skill load:

1. Subscribe to its personal inbox (`agent/<your-agent-id>`) plus any channels you passed via `--channel`.
2. Drain pending messages once with `mcp__sox__channels__recv`.
3. Emit a single `online` heartbeat.

After activation, the agent participates per the polling-cadence rules in §1.4 below. This turns `/inter-agent-channels` (or auto-load via the skill's `description`) into a one-step "join the team" command — no follow-up "subscribe to X" prompt needed.

> **Loading note:** Claude Code's slash-command for a skill is `/<skill-name>` — so `/inter-agent-channels`, *not* `/skill inter-agent-channels`. (`/skill` is unknown; `/skills` opens the management dialog.) Skills with a good `description` field auto-load when the agent's task matches.

The two modes (descriptive / auto-subscribe) toggle freely: re-run `sox-protocol install` (or `sox-protocol upgrade`) with or without the flag and the SKILL.md is rewritten to match.

### 1.2 Configure

The default configuration is sensible for single-machine multi-subagent use. To override, set environment variables (or add to `.env`):

```bash
SOX_BACKING_STORE=sqlite:///.sox/messages.db    # default
SOX_AGENT_ID_SOURCE=env:CLAUDE_AGENT_NAME       # how to derive the agent's own ID
SOX_REMINDER_THRESHOLD=5                        # tool calls before "drain inbox" reminder
SOX_FORCE_DRAIN_ON_STOP=true                    # block agent exit if inbox non-empty
SOX_DEFAULT_CHANNEL_PREFIX=ticket               # channels named ticket:<id> by default
```

See [§3](#3-configuration-reference) for the full list.

### 1.3 Add the bootstrap line to agent prompts

Each agent that should participate in cross-agent messaging needs one line in its system prompt:

```markdown
For coordination with other agents (clarification, broadcasts, peer questions),
load the `inter-agent-channels` skill when blocked, broadcasting, or seeking
peer input.
```

The full discipline lives in the skill, loaded on demand. The bootstrap line just makes the skill's existence known.

### 1.4 Verify

```bash
sox-protocol verify
```

Reports on: backing store reachable, MCP server registered, hooks installed, skill present, all four MCP tools surfaced.

---

## 2. Channel naming convention

SOX has no enforced namespace, but the recommended convention (used by the default discipline document) is:

| Pattern | Use |
|---|---|
| `ticket:<ticket-id>` | All agents working on the same ticket auto-subscribe; clarification questions and status updates go here |
| `agent:<agent-id>` | Direct mailbox for a specific agent |
| `role:<role-name>` | All agents with a given role (e.g., `role:qa`); useful for broadcast-to-role |
| `broadcast:<topic>` | Project-wide announcements (e.g., `broadcast:cto-announcements`) |

Channels are implicit: `send` to a non-existent channel creates it. There is no "create channel" operation. Subscriptions can use glob patterns (e.g., `ticket:ENGI-*` to subscribe to every ticket).

---

## 3. Configuration reference

| Env var | Default | Meaning |
|---|---|---|
| `SOX_BACKING_STORE` | `sqlite:///.sox/messages.db` | URL of the backing store. Supported schemes: `sqlite://`, `file://` (filesystem), `memory://` (ephemeral, tests only). NATS / Redis added in v0.1+. |
| `SOX_AGENT_ID_SOURCE` | `env:CLAUDE_AGENT_NAME` | How the MCP server learns its agent's identity. Format: `env:<VAR>` or `arg:<n>` (positional CLI arg). |
| `SOX_REMINDER_THRESHOLD` | `5` | Number of tool calls without a `channels__recv` before the cadence enforcer injects a reminder. |
| `SOX_FORCE_DRAIN_ON_STOP` | `true` | If true, the stop hook blocks agent exit until the inbox is drained. |
| `SOX_DEFAULT_CHANNEL_PREFIX` | `ticket` | Prefix used for auto-derived channels in the discipline's worked examples. |
| `SOX_LOG_LEVEL` | `INFO` | Logging verbosity for the MCP server. |
| `SOX_MCP_TRANSPORT` | `stdio` | `stdio` or `http`. HTTP needed if you want one MCP server shared across multiple Claude processes; otherwise stdio is simpler. |

---

## 4. The four MCP tools

Surfaced by the SOX MCP server. All four are non-blocking.

### 4.1 `channels__send`

Send a message to a channel.

```python
# input
{
  "channel": "ticket:ENGI-0042",
  "body": {
    "type": "clarification_request",
    "question": "Should we keep the legacy /v1/users endpoint or deprecate it?",
    "context": "Working on auth rewrite; the spec is ambiguous on this."
  },
  "correlation_id": "clarif-1"   # optional
}

# output
{
  "sent_at": 1714320000.123,
  "message_id": "msg_abc123"
}
```

Returns immediately. The agent does **not** wait for a reply.

### 4.2 `channels__recv`

Drain the local mailbox.

```python
# input
{
  "channels": null,            # null = all subscribed channels
  "max_messages": 50
}

# output
{
  "drained_at": 1714320005.456,
  "messages": [
    {
      "channel": "ticket:ENGI-0042",
      "sender": "agent-qa-001",
      "body": { "type": "clarification_reply", "answer": "Deprecate it.", ... },
      "correlation_id": "clarif-1",
      "sent_at": 1714320003.789,
      "message_id": "msg_def456"
    }
  ]
}
```

Returns immediately with whatever has accumulated. If nothing has arrived, `messages` is empty.

### 4.3 `channels__subscribe`

Subscribe to a channel pattern.

```python
# input
{ "pattern": "ticket:ENGI-0042" }   # or "ticket:ENGI-*" for glob

# output
{ "subscribed": ["ticket:ENGI-0042"] }
```

Auto-subscribed channels (per `SOX_DEFAULT_CHANNEL_PREFIX` and the agent's task assignment) do not require explicit subscribe calls.

### 4.4 `channels__list_channels`

Discovery / introspection.

```python
# output
{
  "channels": [
    {"name": "ticket:ENGI-0042", "subscriber_count": 3},
    {"name": "broadcast:cto-announcements", "subscriber_count": 12}
  ],
  "protocol_version": "1.0"
}
```

---

## 5. Use cases

### 5.1 Clarification while continuing work

The motivating use case. Agent A is implementing a feature; encounters ambiguity; posts a clarification request; continues under best-guess; integrates the reply when it lands.

**Flow:**

1. **T=1** Agent A detects ambiguity. Loads `inter-agent-channels` skill (the bootstrap line in its system prompt names this skill).
2. **T=2** Skill content guides A to call `channels__send` with the question on `ticket:<id>`, *not* to wait for a reply, and to record the assumption being made in its working notes.
3. **T=3 — T=10** A continues implementation under best-guess. Cadence enforcer reminds A to call `channels__recv` every ~5 tool calls.
4. **T=4** Agent B (subscribed to `ticket:<id>`) receives the question via its own MCP server's listener. B answers via `channels__send`.
5. **T=11** A's next `channels__recv` returns B's answer.
6. **T=12** Per the speculative-then-reconcile recipe in the skill: A compares the answer against the recorded best-guess. If aligned, A annotates the working notes "assumption confirmed" and continues. If contradicted, A revises the assumption, flags any work that needs rollback, and continues.

**Worked example:** see `core/discipline/examples/send-and-continue.md` in the reference implementation (lands at [Milestone 4](./IMPLEMENTATION-PLAN.md#milestone-4--discipline-document)).

### 5.2 Group broadcast

Agent C wants to announce a status update visible to everyone on a ticket.

**Flow:**

1. C calls `channels__send` to `ticket:<id>` with a `status_update` message body.
2. All agents subscribed to `ticket:<id>` (including C itself) receive it on their next drain.
3. No reply is required. The discipline guides receivers to record the update in their working state without responding.

This is also how agents coordinate "I'm taking this part" / "I'm done with that part" without a centralised manager.

### 5.3 Cross-agent handoff with continuation

Agent A finishes its slice of a task; agent B picks up the next slice; A continues with another slice in parallel rather than stopping.

**Flow:**

1. A sends a `handoff_ready` message to `agent:B` with the artefact URL or relevant state pointer.
2. A continues with its next slice without waiting for B to acknowledge.
3. B drains, finds the handoff, picks up the work.
4. If B has questions back to A, B sends to `agent:A` (or to `ticket:<id>` for visibility).

This is **not** a "handoff" in the OpenAI Agents SDK sense (which transfers control). A keeps working.

### 5.4 Asking the room when you don't know who can answer

Agent A has a question but doesn't know which peer is best placed to answer.

**Flow:**

1. A sends to `ticket:<id>` (or `role:expert`) with the question and a reasonable timeout-of-relevance.
2. Multiple agents may answer. A's `recv` returns all answers.
3. The discipline guides A to consume answers in order, and to apply a documented "first-good-enough wins" or "merge consensus" pattern depending on question type.

---

## 6. Anti-patterns

Things the discipline document explicitly forbids. Listed here so integrators recognise them when reviewing agent behaviour.

### 6.1 Send-and-wait

**Wrong:** agent calls `channels__send`, then in the next turn says *"I will now wait for the answer"* and produces no progress.

**Why it's wrong:** defeats the entire async property. The framework cannot prevent this — only the discipline + the cadence enforcer's "send-followed-by-stalled-turns" detection can.

**Right:** after sending, immediately continue with best-guess work. Drain inbox between major decisions; integrate the reply when it lands.

### 6.2 Synchronous request/reply via channels

**Wrong:** using channels to do RPC. "Send a request, drain, expect the reply, block."

**Why it's wrong:** that's a tool call, not a channel. Use a tool call (or A2A) for genuine request/reply.

**Right:** use channels when (a) you don't need the answer immediately, or (b) you have other work to do meanwhile.

### 6.3 Unbounded polling

**Wrong:** agent calls `channels__recv` after every single token / minor reasoning step.

**Why it's wrong:** tool-call token cost grows linearly. Cadence enforcer's reminder is calibrated for ~5 tool calls, not every step.

**Right:** drain at major decision points or when the cadence enforcer prompts.

### 6.4 Treating channels as durable task state

**Wrong:** an agent posts its work-in-progress state to a channel and treats the channel as the source of truth.

**Why it's wrong:** channels are messaging, not storage. A SOX channel is not a database.

**Right:** use channels for *messages between agents*; use your task tracker / database / file system for *task state*.

### 6.5 Bypassing the discipline

**Wrong:** an agent's system prompt embeds the channel-usage instructions inline, "for safety", in case the skill doesn't load.

**Why it's wrong:** defeats progressive disclosure and creates two sources of truth that drift.

**Right:** keep the bootstrap line minimal; trust the skill-loading mechanism. If skill loading is unreliable in your runtime, that's a runtime bug to file.

---

## 7. Troubleshooting

### 7.1 "My agent never calls `channels__recv`"

Most likely cause: bootstrap line missing from the agent's system prompt, or the skill is not being loaded because the `description` doesn't match the situation the agent is in.

Fix: verify with `sox-protocol verify`. Check that the agent's system prompt includes the bootstrap line. Consider broadening the skill's `description` in `SKILL.md`.

### 7.2 "Messages aren't being delivered between subagents"

Check whether stdio MCP is being used with multiple subagents. Stdio MCP spawns one server per Claude process — each subagent's MCP server is isolated. Either:

- Use a backing store all servers connect to (SQLite is fine — they all open the same DB file). This is the default and should work.
- If you've configured an in-memory store, switch to SQLite or use HTTP MCP transport.

Verify with `sqlite3 .sox/messages.db 'SELECT * FROM messages'` — if messages are landing in the DB but not reaching readers, it's a subscription / drain issue, not a delivery issue.

### 7.3 "The cadence enforcer keeps injecting reminders even when the agent is busy"

Tune `SOX_REMINDER_THRESHOLD` upward. Default 5 is calibrated for clarification-heavy tasks; pure-implementation work may benefit from 10–15.

### 7.4 "Agent gets stuck in a loop of `recv → think → recv` without making progress"

This is the cadence-enforcer false-positive case: it's nagging too aggressively, and the agent has internalised the nagging into its loop. Increase `SOX_REMINDER_THRESHOLD` and consider toggling the discipline's "anti-pattern: unbounded polling" example to be more prominent in the skill body.

### 7.5 "Late replies arrive after the agent has finished its task"

By design, the stop hook (when `SOX_FORCE_DRAIN_ON_STOP=true`) blocks agent exit until the inbox is drained. If you are still seeing this, the message arrived after the drain on stop. Two options:

- Increase the listener's grace period before the stop hook returns.
- Shift to a long-lived "supervisor" pattern where the agent does not exit between tasks — common in daemon-shaped multi-agent systems.

### 7.6 "How do I see what's flowing on a channel?"

Run `python -m sox_protocol.cli tail ticket:ENGI-0042` for a live tail. Or query the SQLite store directly. A graphical tool is in [FUTURE.md](./FUTURE.md) §7.

### 7.7 "My agent receives its own sent messages on the next `recv`"

By design. An agent that is subscribed to a channel receives **all** messages on that channel, including ones it sent itself. This is consistent with a pub/sub model: the sender is also a subscriber.

**This is not a bug** — it is what allows agents to maintain a coherent view of the conversation, including their own contributions.

**If you want to filter out self-messages**, check the `sender` field:

```python
reply = channels__recv()
peer_messages = [m for m in reply["messages"] if m["sender"] != MY_AGENT_ID]
```

The discipline's reconciliation recipe already accounts for this: when draining inbox after sending a clarification request, an agent filters for messages of `type: clarification_reply` from senders other than itself. Do not assert on the total message count when the agent is subscribed to the channel it sent on.

### 7.8 "Demo runner exits with 'Demo FAILED: assertion error'"

Most likely cause: a timing issue where the background listener has not yet
delivered a message when `recv` is called.

The demo runners and integration tests include `asyncio.sleep(0.1–0.15)` pauses
between `send` and the subsequent `recv` to allow the watch loop (which polls
every 50 ms) to pick up and buffer new messages. If your environment is under
heavy load, you may need to increase these sleeps.

For CI environments with slow I/O, set `SOX_WATCH_POLL_INTERVAL_MS=25` to make
the listener more responsive (at the cost of slightly higher SQLite read traffic).

### 7.9 "Three-agent broadcast: implementer sees its own broadcast in its final drain"

Expected behaviour. When the implementer broadcasts on `ticket:DEMO-002` and
then drains its own inbox, it receives the broadcast it sent — because it is
subscribed. The correct check is:

```python
# Does NOT assert inbox is empty — implementer sees own broadcast.
non_self_msgs = [m for m in inbox if m["sender"] != "implementer"]
assert non_self_msgs == []  # no *peer* replies
```

See `examples/group-broadcast/run_demo.py` Phase 6 for the reference
implementation of this pattern.

---

## 8. Operational concerns

### 8.1 Storage growth

The SQLite backing store grows over time. v0 has no automatic retention. Operators should run a periodic vacuum:

```bash
python -m sox_protocol.cli vacuum --older-than 7d
```

### 8.2 Concurrency limits

SQLite's WAL mode handles concurrent writers well up to ~50 msg/sec on commodity hardware. Beyond that, switch to NATS or Redis (v0.1+).

### 8.3 Live-test guidance

For any project using SOX Protocol, the policy of running real (not mocked) tests of multi-agent behaviour applies. See the [project's mock-vs-live policy](../../../../CLAUDE.md) for context. Mocking SOX channels in unit tests is fine; verifying that the runtime + discipline + cadence enforcer interact correctly requires live agents.

---

## 9. Where to go next

- [DESIGN.md](./DESIGN.md) for architecture and rationale.
- [CONTRACTS.md](./CONTRACTS.md) if you're writing a new adapter or implementing the protocol.
- [FUTURE.md](./FUTURE.md) for what is and isn't on the roadmap.
- [RESEARCH.md](./RESEARCH.md) for the bibliography that informed the design.
