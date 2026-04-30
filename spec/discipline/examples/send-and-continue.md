<!-- SPDX-License-Identifier: Apache-2.0 -->
# Worked example: send-and-continue

**Scenario.** Agent A ("implementer") is writing a REST endpoint. The spec
does not specify JWT token lifetime. Agent B ("api-reviewer") is available on
`ticket:DEMO-001` and may have an authoritative answer.

---

## T=1 — Ambiguity discovered

Agent A is drafting `POST /login`. It reads the spec and notices the token
lifetime is unspecified.

**Decision:** make a best-guess assumption, send a clarification request, and
continue.

```
{{send_tool}}(
  channel = "ticket:DEMO-001",
  body = {
    "type": "clarification_request",
    "subject": "JWT expiry for POST /login",
    "context": "Spec §4 is silent on token lifetime.",
    "question": "Should access-token expiry be 15 min or 24 h?",
    "urgency": "normal"
  }
)
```

Agent A records: *"Assuming 15-minute expiry — standard short-lived token.
Will revise if reviewer contradicts."*

Agent A immediately continues implementing the endpoint with `exp = now + 900`.

---

## T=4 — Checkpoint drain, no reply yet

Agent A finishes the handler and is about to write tests. Before choosing
which expiry values to use in test fixtures, it drains the inbox.

```
{{recv_tool}}()
```

Result: `{"messages": [], "drained_at": <T4>}`

No reply. Agent A proceeds with the 15-minute assumption in test fixtures.
No stall, no wait.

---

## T=20 — Checkpoint drain, reply arrives; assumption confirmed

Agent A is about to generate API documentation and drains once more.

```
{{recv_tool}}()
```

Result:
```json
{
  "messages": [
    {
      "channel": "ticket:DEMO-001",
      "sender": "api-reviewer",
      "body": {
        "type": "clarification_reply",
        "subject": "JWT expiry for POST /login",
        "answer": "15 minutes for access token is correct per our security policy."
      }
    }
  ]
}
```

The reply **confirms** the assumption. Agent A has nothing to redo. It notes
the confirmation, removes the assumption caveat from its working context, and
continues generating documentation without interruption.

---

## Key takeaways

- The send at T=1 costs one tool call. Work continued for 19 time-steps
  without blocking.
- The T=4 drain was empty. That drain is still valuable: it keeps the
  cadence counter from triggering a reminder, and it only costs one tool call.
- The T=20 drain delivered a reply that required zero rework because the
  assumption was correct.
- Total overhead: two extra tool calls over 20 steps.
