# SOX Protocol — Reference Agent

This directory is the canonical answer to "how do I write a SOX agent?". Every
protocol primitive is demonstrated here with prose explanations so you can read
the code and the spec side-by-side. Copy this directory as your starting point;
delete what you don't need; keep the patterns you do.

**Files:**

| File | Purpose |
|---|---|
| `agent.py` | Fully-annotated implementation of every lifecycle step |
| `state.py` | Atomic `{channel: last_seq}` persistence for recovery |
| `cli.py` | Argparse entry point for running the agent from the shell |
| `run_standalone.sh` | Quick-start: boots agent in `--once` mode, no manual input |
| `.claude-agent.md` | Claude Code agent definition (system prompt, tool list) |
| `pyproject.toml` | Isolated example package depending on `sox-protocol` |

---

## Bootstrap

**Spec:** `spec/protocol.md §bootstrap-sequence`, `spec/primitives/namespace.md`

The first thing any SOX agent does is establish a session. There is a prescribed
four-step sequence, and each step exists for a reason:

**Step 1 — `channels__list_channels`**

Before doing anything else, call `list_channels` and read the `_sox_protocol`
block it returns. The `server_version` field tells you whether the server speaks
the same protocol version you understand. If the MAJOR version does not match
yours, stop immediately — you will misinterpret messages.

This is the version handshake. Skipping it is permitted by the spec but
described as "at the client's risk". For a production agent, always do it.

**Step 2 — `channels__subscribe`**

Register your channel patterns before you try to receive anything. Subscriptions
are persistent (they survive server restarts) and they determine what `recv`
returns. A common mistake is to send a message first and then subscribe — you
will miss anything sent between session start and your subscribe call.

The reference agent subscribes to:
- `ticket:*` — all work-item channels
- `dm/<agent-id>~*` and `dm/*~<agent-id>` — direct messages in both sort orders
- `sox/presence` — the server-emitted presence event feed

**Step 3 — `channels__list_agents`**

After subscribing, call `list_agents` to learn about your peers. This is
optional but recommended — knowing which agents are `online` vs `stale` helps
you decide whether to wait for a reply or continue speculatively.

**Step 4 — `channels__heartbeat(status="online")`**

Emit your first heartbeat to register with the server's liveness table. Other
agents calling `list_agents` will now see you. Without this call you are
invisible to peers until the first automatic heartbeat fires.

**Step 5 — Initial `channels__recv`**

Drain the mailbox once immediately after subscribing. Messages sent to your
channels while you were offline are queued and waiting. This first drain
surfaces them before you enter the main loop — otherwise you might miss them
or interleave them with recovery replay (see the Recovery section).

---

## Main Loop

**Spec:** `spec/primitives/sequence-numbers.md`, `spec/primitives/channels.md`

SOX is a pull-based protocol. The server does not push messages to you;
you drain your mailbox by calling `channels__recv`. The reference agent
polls every 0.5 seconds. The cadence enforcer in production deployments
will also remind you to drain if you fall behind.

On each `recv` call you get back a list of messages. For each message:

1. ACK `received` immediately — before you start any work. This tells the
   sender (and any orchestrator watching pending-state) that you have the
   message in hand.

2. ACK `processing` when you begin substantive work on the message. This is
   the "I started" signal.

3. ACK `done` when you are completely finished, or ACK `nack` if you cannot
   process the message. Both are terminal.

After processing each message, update the per-channel `last_seq` cursor in
`state.py`. This cursor is what makes recovery possible.

**Why track `seq` per-channel?**

`seq` is the per-channel monotone counter assigned by the server (spec/primitives/
sequence-numbers.md). It is the authoritative ordering key within a channel and
the cursor for `channels__replay`. By persisting `{channel: last_seq}` to disk
after each message, you can restart and ask the server "give me everything on
this channel after seq N" — and nothing will be re-delivered or skipped.

---

## Thread Handling

**Spec:** `spec/primitives/threads.md`, `spec/primitives/sequence-numbers.md`

PRIMITIVE COVERAGE: `reply_to` threading.

When you receive a `clarification_request`, you have two choices: block until
the answer arrives, or continue under a best-guess assumption and reconcile
later. SOX is designed for the second choice — the *speculative-execute
discipline*.

**How to send a reply:**

```python
await client.call_tool("channels__send", {
    "channel": parent["channel"],     # SAME channel — not a sub-channel
    "body": {"type": "clarification_reply", "answer": "..."},
    "reply_to": parent["message_id"],  # links reply to parent in wait-graph
    "correlation_id": parent.get("correlation_id"),  # propagate for tracing
})
```

Three things to notice:
- **Same channel.** Replies in SOX stay on the originating channel. The spec
  defines thread channels (`thread:<message-id>`) as an optional pattern, but
  the `reply_to` field on the wire envelope is what creates the thread
  relationship — no sub-channel is required.
- **`reply_to` set.** This is what the server uses for deadlock detection
  (spec/protocol.md §deadlock). If A is waiting for B and B is waiting for A,
  the wait-graph built from `reply_to` + `delivered_to` reveals the cycle.
- **`correlation_id` propagated.** Set `correlation_id` to the parent's value
  so observers can link all messages in a logical conversation across channels.

**Speculative execution:**

After sending the clarification request, continue working under your best-guess.
When the reply arrives in a later `recv` cycle, integrate it non-destructively:
compare the answer to your assumption, apply a correction if needed, and move on.
Never block the main loop waiting for a reply — that is a deadlock waiting to happen.

---

## ACK / NACK

**Spec:** `spec/primitives/ack-nack.md`

PRIMITIVE COVERAGE: `channels_ack`.

ACK is a **tool call**, not a channel message. This is the most important rule
in the entire spec. Never do this:

```python
# WRONG — do NOT do this
await client.call_tool("channels__send", {
    "channel": "ticket:foo",
    "body": {"type": "sox-ack", "message_id": "..."},  # ANTI-PATTERN
})
```

Do this instead:

```python
# CORRECT
await client.call_tool("channels__ack", {
    "message_id": "...",
    "status": "done",
})
```

The ACK state machine is forward-only:

```
pending → received → processing → done
                               → nack
```

You cannot go backwards. Once a message is `done` it is done. The server will
reject backward transitions. This determinism is what makes pending-state
inspection reliable for orchestrators and audit consumers.

**All four transitions:**

| Status | When to use |
|---|---|
| `received` | Immediately after `recv` returns the message |
| `processing` | When you begin substantive work |
| `done` | When you have fully handled the message |
| `nack` | When you cannot or will not process it (include a `reason`) |

**ACKs never appear in channel history.** A subsequent `recv` will never return
a message whose `body.type` starts with `sox-ack`. If you see one, it is a bug
in the sender, not a feature of the protocol.

---

## Presence Heartbeat

**Spec:** `spec/primitives/presence.md`

PRIMITIVE COVERAGE: `channels_heartbeat`, `list_agents`.

The heartbeat is a **control-plane signal** — it updates the server's liveness
table but writes nothing to any channel. The `sox/presence` channel receives
server-emitted *coalesced* state-transition events, not raw heartbeats.

The reference agent runs the heartbeat as an independent `asyncio` background
task, firing every 10 seconds (the spec-recommended interval). It is
intentionally decoupled from the main message loop: a slow message does not
delay a heartbeat, and a heartbeat failure does not stop message processing.

Status values:
- `online` — idle, ready to process
- `busy` — mid-task (flipped by `main_loop` while processing a batch)
- `offline` — shutting down (emitted by `graceful_stop`)

The server derives `stale` (no heartbeat for 30s) and `offline` (no heartbeat
for 90s) automatically. You do not need to manage these transitions yourself.

---

## Graceful Stop

**Spec:** `spec/protocol.md §graceful-stop`, `spec/primitives/presence.md`

The spec prohibits stopping while any message is in `received` or `processing`
state. The reference agent enforces this with a `_pending` set that tracks
in-flight message IDs and a wait loop in `graceful_stop()` that blocks until
the set is empty.

Once all messages have reached `done` or `nack`:

1. `channels__heartbeat(status="offline")` — signal state transition to peers.
2. `channels__unsubscribe` for all patterns — discard the unread backlog.
3. Set the stop event — main loop and heartbeat loop exit on the next cycle.

A SIGTERM handler triggers the same path, so container orchestrators and
process supervisors get clean teardown for free.

---

## Recovery

**Spec:** `spec/operations/replay.input.schema.json`, `spec/primitives/sequence-numbers.md`

After a restart (or a context reset that loses in-process queue state), call
`channels__replay(channel, since=last_seq_persisted)` for every channel in
your state file. The `since` parameter is a per-channel seq cursor — the server
returns all messages with `seq > since`.

The reference agent calls this in `recover_from_state()`, which runs between
`bootstrap()` and `main_loop()`. The seq cursor is only advanced on disk
**after** a message is fully processed, so a crash between processing and
persisting means the message will be replayed (at-most-once delivery guarantee
is not required in v1; at-least-once is the contract).

State is stored at `$XDG_STATE_HOME/sox-reference-agent/seq.json`:

```json
{
  "ticket:ENGI-001": 42,
  "ticket:ENGI-002": 7
}
```

The file is written atomically (temp-file + `os.replace`) so a partial write
never corrupts the state.

---

## Group Lifecycle

**Spec:** `spec/primitives/groups.md §5.1-§5.5`

PRIMITIVE COVERAGE: `group_create`, `group_invite`, `group_join`,
`group_list_members`, `group_leave`.

Groups are managed channels under the `group/<id>` prefix. The full lifecycle:

```python
# 1. Create a group (caller becomes first active member)
r = await agent.group_create("eng-team")
group_id = r["group_id"]  # "group/eng-team"

# 2. Invite another agent (caller must be active)
await agent.group_invite(group_id, "partner-agent")

# 3. Partner accepts the invitation
await partner.group_join(group_id)

# 4. Verify membership
members = await agent.group_list_members(group_id)

# 5. Leave when done
await agent.group_leave(group_id)
```

Group messages fan out to all active members. Each recipient must issue
`channels__ack` individually — group fan-out tracks ACKs per-recipient, not
per-broadcast (spec/primitives/ack-nack.md §8).

Do not try to glob-subscribe to `group/*`. The server rejects wildcard
patterns on reserved prefixes. Use the lifecycle verbs instead.

---

## Anti-Patterns We Deliberately Avoided

These are the mistakes new SOX adopters most commonly make. The reference agent
avoids all of them, and the integration test suite checks for them explicitly.

### 1. ACK as a channel message

```python
# WRONG — this is the most common mistake
channels__send(channel="ticket:foo", body={"type": "sox-ack", ...})
```

ACK is a tool call (`channels__ack`), not a message. Sending `body.type=sox-ack`
to a channel puts noise in the channel history, wastes sequence numbers, and
confuses any agent that processes the channel — including your own replay.

### 2. Blocking on clarification

```python
# WRONG — blocks the main loop; leads to deadlock
reply = await wait_for_reply(clarification_request_id)
```

SOX is designed for async non-blocking operation. Send your question, continue
under a best-guess, and integrate the reply when it arrives in a future `recv`
cycle. Blocking turns a concurrent multi-agent system into a sequential one.

### 3. Glob-subscribing to reserved prefixes

```python
# WRONG — the server rejects this
channels__subscribe(pattern="group/*")
channels__subscribe(pattern="dm/*")
```

Use `group__join` to enter groups. Use the explicit DM channel name to
subscribe to direct messages.

### 4. Missing recovery on restart

```python
# WRONG — skips messages sent while the agent was offline
await bootstrap()
await main_loop()  # no recovery step
```

Always call `recover_from_state()` between `bootstrap()` and `main_loop()`.
The state file tells you exactly where to resume.

### 5. Stopping with pending messages

```python
# WRONG — leaves senders' pending-state in "processing" forever
sys.exit(0)
```

Call `graceful_stop()`, which waits for all in-flight messages to reach
`done` or `nack` before emitting `heartbeat(offline)` and exiting.

### 6. Cross-channel replies

```python
# WRONG — reply creates a new channel instead of threading on the original
channels__send(channel="thread:" + parent_id, body={...})
```

Replies stay on the original channel. Set `reply_to` on the `send` call.
Thread channels (`thread:<id>`) are a valid naming convention but require
explicit subscription by all participants; they are not auto-created by
using `reply_to`.
