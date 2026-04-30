<!-- SPDX-License-Identifier: Apache-2.0 -->
# Worked example: speculative-then-reconcile

**Scenario.** Agent A ("implementer") is implementing user account deletion.
Agent B ("policy-reviewer") is the authority on data-retention rules.
Agent A discovers an ambiguity, sends, and continues — but the reply
contradicts the assumption.

---

## Setup

Agent A's task: implement `DELETE /accounts/{id}`. The spec says "delete
the account". Agent A is unsure whether to hard-delete the row or soft-delete
(mark deleted, retain for 30 days per typical GDPR patterns).

**Assumption:** soft-delete (safer default).

```
{{send_tool}}(
  channel = "ticket:DEMO-003",
  body = {
    "type": "clarification_request",
    "subject": "Hard-delete or soft-delete for DELETE /accounts/{id}?",
    "context": "Spec just says 'delete the account'. Our retention table supports both.",
    "question": "Should DELETE permanently remove the row, or set deleted_at and retain?",
    "urgency": "normal"
  }
)
```

Agent A records: *"Assuming soft-delete. Will set `deleted_at = now()`."*

---

## Work done under the false assumption

Agent A implements and commits the following (in-memory, not yet deployed):

1. Handler sets `accounts.deleted_at = now()`.
2. All queries gain a `WHERE deleted_at IS NULL` filter.
3. Unit tests written for soft-delete behaviour.
4. Auth middleware updated to reject tokens for soft-deleted accounts.

---

## Reply arrives — contradiction

At the next checkpoint drain:

```
{{recv_tool}}()
```

Result:
```json
{
  "messages": [
    {
      "channel": "ticket:DEMO-003",
      "sender": "policy-reviewer",
      "body": {
        "type": "clarification_reply",
        "subject": "DELETE /accounts/{id} semantics",
        "answer": "Hard-delete only. Legal confirmed: no retention requirement exists; soft-delete would violate our privacy commitment to delete data on request."
      }
    }
  ]
}
```

The reply contradicts the assumption. Agent A stops the current branch.

---

## Reconciliation steps

**Step 1 — Stop.** Agent A halts the current work (was about to write
integration tests).

**Step 2 — Assess reversibility.**

| Work item | Reversible? |
|---|---|
| Handler sets `deleted_at` | Yes — in-memory code change |
| `WHERE deleted_at IS NULL` filters | Yes — in-memory code change |
| Unit tests for soft-delete | Yes — replace with hard-delete tests |
| Auth middleware change | Yes — in-memory code change |

All work is reversible (none has been deployed or published). Agent A proceeds
with a clean redo.

**Step 3 — Redo under corrected assumption.**

- Handler executes `DELETE FROM accounts WHERE id = ?`.
- Remove all `deleted_at` references.
- Rewrite unit tests for hard-delete semantics.
- Auth middleware: no change needed (row deletion handles it naturally).

**Step 4 — Update working context.**

Agent A removes the assumption caveat and records: *"Hard-delete confirmed by
policy-reviewer on ticket:DEMO-003. No soft-delete column needed."*

---

## Irreversible case (illustrative)

If Agent A had already called an external webhook that notified a third-party
system "account soft-deleted, data retained for 30 days", and that call cannot
be unwound, reconciliation looks different:

> **Surface it, do not paper over it.** State explicitly: the webhook was
> called with the wrong payload. Describe the downstream consequence (third
> party believes data is retained when it will in fact be hard-deleted). Ask
> the orchestrator or user whether to send a corrective webhook, accept the
> inconsistency, or pause and wait for guidance.

Never silently proceed past an irreversible action taken under a false
assumption.

---

## Key takeaways

- Speculation is only valuable if you actually continue working. Stopping to
  wait defeats the pattern.
- Check reversibility before reconciling. Reversible work is cheap to redo;
  irreversible work requires escalation.
- The reply arriving 10 or 20 steps later does not reduce the value of
  speculating — it still saved those steps of productive work.
