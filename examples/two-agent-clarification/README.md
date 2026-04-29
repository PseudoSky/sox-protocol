# Example: two-agent-clarification

Demonstrates the **speculative-then-reconcile** pattern described in
`spec/discipline/examples/send-and-continue.md` and `spec/discipline/examples/reconciliation.md`.

Two subagents collaborate on implementing a REST endpoint:

- **implementer** — builds `POST /login`. Detects an ambiguous spec requirement
  (JWT token lifetime), posts a clarification request to `ticket:DEMO-001`,
  records a best-guess assumption, and continues implementing without stalling.
- **api-reviewer** — the authority on API design decisions. Subscribes to
  `ticket:DEMO-001`, drains its inbox, finds the clarification request, and
  sends the authoritative reply.

The implementer drains its inbox at a later checkpoint, finds the reply,
and reconciles (confirming or revising its assumption).

## What this demonstrates

| SOX concept | Where it appears |
|---|---|
| `channels__send` non-blocking | Implementer sends and immediately continues |
| `channels__recv` at checkpoints | Two drains: empty at T=4, reply at T=20 |
| Speculative-then-reconcile | Assumption recorded; confirmed on reply |
| `correlation_id` threading | Request and reply share `clarif-jwt-001` |
| Shared SQLite backing store | Two independent MCP server instances, one DB |

## Run the demo

From the repo root:

```bash
make demo
```

Or directly:

```bash
pip install -e packages/python[dev]
python examples/two-agent-clarification/run_demo.py
```

The demo runs entirely in-process — no Claude API key required. It prints
a full transcript of every SOX tool call made by both agents.

Expected output (abbreviated):

```
========================================================================
  DEMO-001: Two-Agent Clarification (speculative-then-reconcile)
========================================================================
  ...
[implementer] spec is silent on JWT expiry — sending clarification request
  -> channels__send({"channel": "ticket:DEMO-001", "body": {...}, ...})
  ...
[implementer] checkpoint drain (T=4, no reply expected yet)
  -> channels__recv({})
  <- messages: {"messages": [], ...}
  ...
[api-reviewer] sending clarification reply
  -> channels__send({"channel": "ticket:DEMO-001", "body": {...}, ...})
  ...
[implementer] draining inbox before finalising (T=20)
  <- messages: {"messages": [{...clarification_reply...}], ...}
  [implementer NOTES] Assumption CONFIRMED. expires_in=900 s. No rework needed.
  ...
  DEMO-001 PASSED
```

## File layout

```
two-agent-clarification/
├── README.md                          this file
├── run_demo.py                        self-contained demo runner (no Claude needed)
├── tasks/
│   └── DEMO-001.md                    deliberately ambiguous task description
└── .claude/
    ├── settings.json                  committed copy of what `install` produces
    └── agents/
        ├── implementer.md             implementer agent system prompt
        └── reviewer.md                api-reviewer agent system prompt
```

## Running as a real Claude Code project

The `.claude/` directory contains the agent definitions and settings that
`python -m sox_protocol.adapters.runtimes.claude_code install` would produce.
To run the demo with real Claude subagents:

1. Install SOX into this directory:
   ```bash
   cd examples/two-agent-clarification
   pip install sox-protocol
   python -m sox_protocol.adapters.runtimes.claude_code install
   ```

2. Start a Claude Code session pointing at this directory. Claude Code will
   discover the agent files in `.claude/agents/` and the MCP server registered
   in `.claude/settings.json`.

3. Ask the orchestrator to run `implementer` and `api-reviewer` in parallel on
   `tasks/DEMO-001.md`.

The bootstrap line at the bottom of each agent file is what prompts each
subagent to load the `inter-agent-channels` skill when it needs to coordinate.

## The ambiguity in DEMO-001

`tasks/DEMO-001.md` is deliberately silent on JWT token lifetime. The implementer
must:

1. Notice the ambiguity.
2. Post `clarification_request` to `ticket:DEMO-001`.
3. Implement with a 15-minute (900 s) assumption.
4. Drain inbox before finalising.
5. Confirm or revise based on the reviewer's reply.

The `api-reviewer`'s authoritative answer (in its system prompt) is **15 minutes**,
so the assumption is confirmed and no rework is needed. The reconciliation.md
example uses a contradiction — see `spec/discipline/examples/reconciliation.md`
for that variant.

## Automated CI version

The protocol mechanics are tested without a Claude API in:
`packages/python/tests/integration/test_two_agent_exchange.py`

Run it with:
```bash
make test-integration
```
