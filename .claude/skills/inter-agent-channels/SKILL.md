---
name: inter-agent-channels
description: >
  Inter-agent coordination via async channels. Load this skill when blocked
  waiting on a peer, broadcasting a status update, or seeking clarification
  from another agent. Provides the send-and-continue pattern, polling cadence
  rules, and the speculative-then-reconcile recipe.
---

# Inter-agent channels

SOX channels give agents an async mailbox per named channel. Any agent can
send a message to a channel; any agent that has subscribed to that channel
receives it on the next drain. Sends are non-blocking — the caller returns
immediately once the backing store accepts the message. Drains are pull-based
and non-blocking — the receiver controls when it checks its inbox. Use this
model to coordinate peers without stalling either side.

> **Placeholder note for runtime adapters.** This document uses
> `mcp__sox__channels__send`, `mcp__sox__channels__recv`, `mcp__sox__channels__subscribe`, and `mcp__sox__channels__list_channels`
> as stand-ins for runtime-specific tool names. The adapter installer
> substitutes them before rendering this skill.

---

## When to send

Send when you have discovered something a peer needs to know and cannot
resolve alone. Primary triggers:

- **Ambiguity mid-task** — you have hit a requirement or constraint you cannot
  resolve alone and a peer may have the answer.
- **Status broadcast** — you have reached a milestone that subscribers of a
  ticket channel should track.
- **Handoff ready** — your output is complete and the next agent in the
  pipeline should begin.

Do **not** send for every intermediate result. Do not use channels as a
logging or observability mechanism. If no agent has subscribed to a channel,
your message accumulates unread; prefer direct tool calls or sub-agent
spawning when you need an immediate, synchronous response.

---

## How to send

Call `mcp__sox__channels__send` with a `channel` name and a `body` object:

```
mcp__sox__channels__send(
  channel = "ticket:PROJ-42",
  body = {
    "type": "clarification_request",
    "subject": "Preferred auth scheme",
    "context": "Implementing POST /login; spec is silent on token lifetime.",
    "question": "Should JWT expiry be 15 min or 24 h?",
    "urgency": "normal"
  }
)
```

Required fields: `channel`, `body`. Optional: `correlation_id` — set this to a
shared ID when you want to match a reply to this message later. Recommended
`body` keys: `type`, `subject`, `context`, `question` / `answer`, `urgency`
(`low` / `normal` / `high`). All are advisory; the protocol does not inspect
them.

`mcp__sox__channels__send` returns as soon as the message is durably accepted. Proceed
without waiting for a reply.

---

## Polling cadence

Drain your inbox at natural checkpoints between major sub-tasks and before
synthesising a final output. Call `mcp__sox__channels__recv` with no arguments to drain
all subscribed channels:

```
mcp__sox__channels__recv()
```

Rules:
- Drain at every significant decision point, even if you expect nothing.
- An empty drain is cheap; a stale inbox is expensive.
- The cadence enforcer will inject a reminder after
  approximately five tool calls or three turns without a drain. Do not wait
  for the reminder — drain earlier.
- After draining, process each returned message before continuing. If a
  message is not actionable now, note its content and move on.

---

## The send-and-continue pattern

This is the core async-first workflow. Follow these steps exactly:

1. **Identify the ambiguity.** Name the assumption you are about to make.
2. **Send.** Call `mcp__sox__channels__send` with a `clarification_request` body.
3. **State your assumption.** Record it explicitly in your working context
   (e.g., "Assuming 15-minute JWT expiry until I hear otherwise").
4. **Continue immediately.** Begin work under the best-guess assumption. Do
   not pause, poll, or spin-wait.
5. **Drain at checkpoints.** Call `mcp__sox__channels__recv` before each major decision.
6. **On confirmation.** If the reply agrees with your assumption, proceed with
   no rework.
7. **On contradiction.** Follow the speculative-then-reconcile recipe below.

Worked example: `spec/discipline/examples/send-and-continue.md`.

---

## The speculative-then-reconcile recipe

When `mcp__sox__channels__recv` returns a `clarification_reply` that contradicts your
working assumption:

1. **Stop the current branch of work.**
2. **Assess irreversibility.** List what you have already done under the false
   assumption. For each item: is it reversible? (In-memory changes: yes.
   Committed writes, published API calls: no.)
3. **Reversible work** — undo and redo under the corrected assumption.
4. **Irreversible work** — surface the situation explicitly: state what
   actions were taken, why they cannot be unwound, and what the downstream
   consequences are. Ask the user or orchestrator whether to proceed or roll
   back. Do not paper over it.
5. **Update your working assumption** and continue from the earliest safe
   point.

Worked example: `spec/discipline/examples/reconciliation.md`.

---

## Anti-patterns

**Send-and-wait** — calling `mcp__sox__channels__send` and then making no progress until
a reply arrives. This eliminates the async benefit entirely and causes stalls
the cadence enforcer will detect. If you find yourself waiting on a reply:
re-read this section, state an assumption, and continue.

**Over-sending** — broadcasting intermediate results, heartbeats, or
log-level events to a channel. This floods subscribers' inboxes, wastes drain
budget, and makes channels harder to reason about. Ask: would a subscriber
take a meaningful action on this message? If not, do not send it.

---

## What not to use channels for

- **Logging / observability.** Use a dedicated structured log sink, not a
  channel.
- **Synchronous RPC.** If you need an immediate answer, use a direct tool call
  or spawn a sub-agent; do not send and then block.
- **Large binary payloads.** The `body` is a JSON object. Store large
  artefacts externally and pass a reference.
- **High-frequency ping / keep-alive.** Each message occupies backing-store
  capacity and drain budget.
- **Secrets or credentials.** SOX channels have no confidentiality guarantee
  in v0; any subscribed agent can read any message on a channel.

