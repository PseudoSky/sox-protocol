# Worked example: group broadcast

**Scenario.** Agent A ("implementer") finishes a major sub-task and broadcasts
a status update to `ticket:SPRINT-7`. Agents B ("reviewer") and C ("docs")
are both subscribed. Neither needs to reply; both update their own working
context on the next drain.

---

## Setup

Three agents are working in parallel on SPRINT-7:

- Agent A — implementing the feature branch.
- Agent B — reviewing code as it lands.
- Agent C — writing documentation.

All three subscribed to `ticket:SPRINT-7` at startup:

```
{{subscribe_tool}}(pattern="ticket:SPRINT-7")
```

---

## Agent A broadcasts a milestone

Agent A finishes the core implementation and is about to move to tests. Before
switching tasks, it broadcasts a status update:

```
{{send_tool}}(
  channel = "ticket:SPRINT-7",
  body = {
    "type": "status_update",
    "subject": "Core implementation complete",
    "context": "POST /orders handler and domain model landed in commits abc–def. Auth middleware wired. Tests not yet written.",
    "urgency": "low"
  }
)
```

Agent A returns immediately to writing tests. It does not wait for
acknowledgement from B or C.

---

## Agent B drains at its next checkpoint

Agent B has been reviewing earlier commits. It drains before starting a new
review batch:

```
{{recv_tool}}()
```

Result includes Agent A's broadcast. Agent B updates its working context:
*"Implementer has landed the handler. I should queue a review of commits
abc–def."* Agent B adds the review to its queue and continues its current
task without replying to the channel.

---

## Agent C drains at its next checkpoint

Agent C was drafting the authentication section of the docs. It drains before
moving to the orders section:

```
{{recv_tool}}()
```

Result includes Agent A's broadcast. Agent C updates its working context:
*"Orders handler exists. I can now write the orders endpoint documentation
with real commit references."* Agent C proceeds to the orders docs section.
No reply sent.

---

## Why no reply is expected

A `status_update` message is informational. It changes the receivers' queues
or plans but does not request an answer. Sending a reply ("acknowledged")
would create unnecessary traffic and force Agent A to drain again to process
it. Each subscriber simply reads, updates its context, and continues.

---

## Checking channel membership (optional)

If Agent C is unsure whether others are subscribed — for example, if it wants
to know whether anyone will read a broadcast before committing to it — it can
call:

```
{{list_tool}}()
```

This returns all active channels with subscriber counts. If `ticket:SPRINT-7`
shows `subscriber_count: 3`, C knows the broadcast will reach at least two
other agents.

---

## Key takeaways

- A single send reaches all subscribers with no extra overhead per receiver.
- Receivers drain on their own schedule; Agent A's send does not interrupt B
  or C mid-task.
- `status_update` messages carry context forward; they do not require a reply.
- Use `{{list_tool}}` to inspect subscriber counts before committing to a
  broadcast pattern in a new codebase or team setup.
