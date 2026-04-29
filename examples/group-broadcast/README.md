# Example: group-broadcast

Demonstrates the **group broadcast** pattern described in
`spec/discipline/examples/group-broadcast.md`.

Three subagents work in parallel on DEMO-002:

- **implementer** — builds `POST /orders`. When the handler is complete,
  broadcasts a `status_update` to `ticket:DEMO-002` and immediately continues
  writing tests.
- **reviewer** — subscribed to `ticket:DEMO-002`. Drains at a checkpoint,
  receives the broadcast, updates its review queue. Sends **no reply**.
- **docs-writer** — subscribed to `ticket:DEMO-002`. Drains at a checkpoint,
  receives the broadcast, extracts commit references, starts writing endpoint
  docs. Sends **no reply**.

## What this demonstrates

| SOX concept | Where it appears |
|---|---|
| `channels__subscribe` at startup | All three agents subscribe before work begins |
| Single `channels__send` fans out | One broadcast reaches 2 subscribers |
| Receivers drain on their own schedule | Reviewer and docs-writer drain independently |
| No-reply discipline | `status_update` requires no acknowledgement |
| `channels__list_channels` | Implementer verifies 3 subscribers before broadcasting |
| Own-message visibility | Implementer's own broadcast visible on its final drain |

## Run the demo

From the repo root:

```bash
make demo-broadcast
```

Or directly:

```bash
pip install -e packages/python[dev]
python examples/group-broadcast/run_demo.py
```

The demo runs entirely in-process — no Claude API key required.

Expected output (abbreviated):

```
========================================================================
  DEMO-002: Group Broadcast (three-agent status update)
========================================================================
  Agents: implementer, reviewer, docs-writer
  ...
[implementer] broadcasting status update
  -> channels__send({"channel": "ticket:DEMO-002", "body": {...}})
  <- sent: {"message_id": "1", ...}

[implementer] returning immediately to write tests (no wait for ack)
  ...
[reviewer] checkpoint drain before next review batch
  <- messages: {"messages": [{"type": "status_update", ...}]}
  [reviewer NOTES] Broadcast received. Queuing review. NO reply sent.
  ...
[docs-writer] checkpoint drain before starting orders section
  <- messages: {"messages": [{"type": "status_update", ...}]}
  [docs-writer NOTES] Handler exists — commit refs: abc-001 through abc-004. NO reply sent.
  ...
  DEMO-002 PASSED
```

## File layout

```
group-broadcast/
├── README.md                          this file
├── run_demo.py                        self-contained demo runner (no Claude needed)
├── tasks/
│   └── DEMO-002.md                    task description with three-agent parallel work
└── .claude/
    ├── settings.json                  committed copy of what `install` produces
    └── agents/
        ├── implementer.md             implementer agent system prompt
        ├── reviewer.md                reviewer agent system prompt
        └── docs-writer.md             docs-writer agent system prompt
```

## Why receivers do not reply

A `status_update` message is informational. It updates the receivers' working
context and queues but requests no action. Sending an acknowledgement reply
would:

1. Create unnecessary channel traffic.
2. Force the implementer to drain again to process ACKs.
3. Violate the discipline's "unbounded polling" anti-pattern if both
   receivers reply and the implementer drains after each.

The SOX discipline guides receivers: update your state, do not reply.

## Running as a real Claude Code project

The `.claude/` directory is ready for a real Claude Code session:

1. Install SOX:
   ```bash
   cd examples/group-broadcast
   pip install sox-protocol
   python -m sox_protocol.adapters.runtimes.claude_code install
   ```

2. Start a Claude Code session. Three subagents will coordinate over
   `ticket:DEMO-002` using the shared SQLite backing store.

## Automated CI version

The broadcast scenario is covered in:
`packages/python/tests/integration/test_two_agent_exchange.py::test_group_broadcast_received_no_replies`

Run it with:
```bash
make test-integration
```
