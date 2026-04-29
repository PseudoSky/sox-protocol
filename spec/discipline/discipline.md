# Inter-agent channels

<!-- TODO (M4): Write the H1 introduction paragraph. Cover: what SOX channels are, why they exist,
     the one-line mental model (async mailbox per named channel, non-blocking send, agent-controlled drain).
     Keep to 3–5 sentences. -->

> TODO: Introduction prose lands at Milestone 4.
>
> Structural note for runtime adapters: this document uses `{{placeholder}}` tokens for all
> tool name references. The adapter's installer substitutes them with runtime-specific names
> before rendering this content into the prompt surface. Current placeholders:
> - `{{send_tool}}` — the tool for sending a message
> - `{{recv_tool}}` — the tool for receiving (draining) messages
> - `{{subscribe_tool}}` — the tool for registering a channel subscription
> - `{{list_tool}}` — the tool for listing known channels

---

## When to send

<!-- TODO (M4): Write guidance on when an agent should call {{send_tool}}.
     Cover: (a) ambiguity discovered mid-task that a peer can resolve, (b) status broadcast to
     a ticket channel, (c) handoff-ready notification. Anti-guidance: do not send for every
     intermediate result; do not use channels as a logging mechanism. -->

> TODO: Prose lands at Milestone 4.
>
> Structural example (placeholder form — do not use concrete tool names here):
>
> ```
> # Good: broadcast a blocker
> {{send_tool}}(channel="ticket:{{placeholder}}", body={"type": "clarification_request", ...})
>
> # Bad: logging intermediate steps to a channel
> {{send_tool}}(channel="log:{{placeholder}}", body={"step": "read file", "result": "..."})
> ```

---

## How to send

<!-- TODO (M4): Write mechanics of calling {{send_tool}}. Cover: required fields (channel, body),
     optional correlation_id for request-reply matching, the body field conventions from CONTRACTS.md §9
     (type, subject, context, question, answer, urgency), and the non-blocking guarantee
     (send returns immediately once the store accepts the message). -->

> TODO: Prose lands at Milestone 4.

---

## Polling cadence

<!-- TODO (M4): Write guidance on when and how often to call {{recv_tool}}. Cover:
     (a) drain at natural checkpoints (between major sub-tasks, before final synthesis),
     (b) the cadence enforcer will inject a reminder after {{placeholder}} tool calls or turns
         without a drain — agents should not wait for the reminder,
     (c) empty drain is cheap and preferred over stale-inbox risk. -->

> TODO: Prose lands at Milestone 4.

---

## The send-and-continue pattern

<!-- TODO (M4): Write the core async-first pattern. Cover:
     (1) detect ambiguity or need for peer input,
     (2) call {{send_tool}} with a clarification_request,
     (3) DO NOT wait — immediately continue working under a best-guess interpretation,
     (4) label the assumption clearly in your internal state,
     (5) drain inbox periodically via {{recv_tool}} at checkpoints,
     (6) if a reply arrives that confirms the best-guess, proceed with no rework,
     (7) if a reply contradicts, go to the reconcile recipe. -->

> TODO: Prose lands at Milestone 4.

---

## The speculative-then-reconcile recipe

<!-- TODO (M4): Write the reconciliation recipe. Cover:
     (1) when {{recv_tool}} returns a clarification_reply that contradicts the working assumption,
     (2) identify what work was done under the false assumption,
     (3) assess whether any taken actions are reversible,
     (4) emit a targeted revision — do not restart from scratch,
     (5) update the working assumption in your next-turn context,
     (6) continue.
     Note the open problem documented in DESIGN.md §7.1: irreversible actions under a false assumption
     cannot be fully resolved by protocol; the discipline surfaces the situation and recommends rollback
     where possible. -->

> TODO: Prose lands at Milestone 4.

---

## Anti-patterns

<!-- TODO (M4): Document the two primary anti-patterns with recognisable descriptions:
     (1) send-and-wait: calling {{send_tool}} then stalling (no progress) until a reply arrives.
         This negates the async benefit. The cadence enforcer detects this and will inject a reminder.
     (2) over-sending: broadcasting intermediate results or log-level events to channels, flooding
         subscribers and wasting context on drain. -->

> TODO: Prose lands at Milestone 4.

---

## What not to use channels for

<!-- TODO (M4): Enumerate explicit non-uses. Cover:
     - Logging or observability (use a dedicated log sink)
     - Synchronous RPC (use direct tool calls or sub-agent spawning)
     - Large binary payloads (the body is a JSON object; reference an external store for large data)
     - High-frequency ping/keep-alive (wastes backing store capacity)
     - Authentication or secrets passing (channels have no confidentiality guarantee in v0) -->

> TODO: Prose lands at Milestone 4.
