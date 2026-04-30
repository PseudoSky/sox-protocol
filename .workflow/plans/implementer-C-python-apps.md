---
# Implementer Prompt C — Python Demo Apps
# Agent: python-pro
# Engagements: reference-agent/02-build, chat-tui-demo/02-build
#
# PREREQUISITE: implementer-A-spec-core.md must have completed with GATE line emitted.
# Specifically requires on disk:
#   - packages/python/src/sox_protocol/core/identity/  (from identity-primitive)
#   - packages/python/src/sox_protocol/core/middleware/ (from hooks-middleware)
#   - packages/python/src/sox_protocol/adapters/transports/http/ (from http-transport)
#   - All 8 implementation-plan.json files (from consolidated-planner-prompt.md)
#
# Can run in parallel with implementer-B-typescript.md — write envelopes are disjoint:
#   B writes: packages/typescript/, packages/ui/
#   C writes: examples/reference-agent/, packages/python/src/sox_protocol/tui/,
#             examples/two-agents-talking/, docs/media/
---

You are building two Python demo artifacts that exercise the SOX Protocol SDK:
the canonical reference agent (teaching artifact) and the TUI chat demo (recording
for the README). Both consume the Python SDK built in Prompt A. Read the spec and
plans once, then build both engagements in order.

## READ ONCE (shared context)

1. `spec/protocol.md` — wire envelope, operation overview
2. `spec/primitives/` — all primitive files (channels, dms, ack-nack, groups,
   sequence-numbers, presence, namespace)
3. `spec/operations/*.json` — operation schemas
4. `docs/V1-SCOPE.md`
5. `packages/python/src/sox_protocol/` — the full SDK (identity, middleware,
   transports, core) as built by Prompt A

Then read each engagement's `implementation-plan.json` before building it.

---

## ENGAGEMENT 1 — reference-agent

**Plan:** `.workflow/plans/reference-agent/implementation-plan.json`

Read additionally:
- `.workflow/plans/reference-agent/phases/02-build.md`

**Deliver:**
- Every file in `plan.files[]`:
  - `examples/reference-agent/agent.py` — fully-annotated reference implementation
  - `examples/reference-agent/README.md` — prose walkthrough (teaching-grade, not API
    reference; mirrors `plan.lifecycle[]` steps in order)
  - `examples/reference-agent/run_standalone.sh` — quick-start, exits 0 within 30s
  - `examples/reference-agent/.claude-agent.md` — Claude Code agent definition
- Every lifecycle step in `plan.lifecycle[]` implemented in `agent.py`:
  - `bootstrap` — subscribe, list_agents, list_pending, drain_unreplied
  - `main_loop` — recv, process, reply, ack
  - `thread_handling` — reply_to threading via new `reply_to` envelope field
  - `ack_nack` — `channels_ack` tool (ACKs do NOT enter channel history)
  - `presence_heartbeat` — `channels_heartbeat` → `sox/presence` channel
  - `graceful_stop`
  - `recovery` — `replay` from last known `seq` after context reset
- Every primitive in `spec/primitives/` appears at least once in the lifecycle
- Tests per `plan.test_plan[]` — including integration test: agent + partner
  exchange a scripted thread via the SOX backing store
- Annotation density: minimum 1 comment line per 3 code lines in `agent.py`

**Hard constraints:**
- 100% coverage on `agent.py` logic (excluding CLI entry point boilerplate)
- `mypy --strict` on `agent.py`
- Standalone run completes in ≤ 30s without manual input
- Agent runnable both as plain Python (`python examples/reference-agent/agent.py`)
  and as a Claude Code agent (via `.claude-agent.md`)

**Acceptance:**
```bash
pytest packages/python/tests/reference_agent/ \
  --cov=examples.reference_agent.agent --cov-fail-under=100 -q
mypy --strict examples/reference-agent/agent.py
bash examples/reference-agent/run_standalone.sh   # exits 0 within 30s
```
Also verify: integration test (agent + partner scripted exchange) passes end-to-end.

---

## ENGAGEMENT 2 — chat-tui-demo

**Plan:** `.workflow/plans/chat-tui-demo/implementation-plan.json`

Read additionally:
- `.workflow/plans/chat-tui-demo/phases/02-build.md`
- `packages/python/src/sox_protocol/tui/` (if partially scaffolded)

**Deliver:**
- TUI app per `plan.files[]` under `packages/python/src/sox_protocol/tui/`:
  - `app.py` — Textual application with four panes (channel list, message feed,
    agent roster, compose bar)
  - Live updates via `watch()` — no polling loops
- `sox chat` CLI subcommand wired in `packages/python/src/sox_protocol/cli/`
- `examples/two-agents-talking/demo.py` — scripted, reproducible, no manual input;
  exercises: channel send, thread reply, DM (`dm/<sorted-pair>`), ACK, presence
- `docs/media/demo.cast` — asciinema recording of demo.py run
- `docs/media/demo.gif` — rendered from demo.cast via vhs or equivalent
- `README.md` updated: embed `docs/media/demo.gif` near the top (one-line change;
  full rewrite belongs to launch-narrative engagement)
- Tests per `plan.test_plan[]` under `packages/python/tests/tui/` — use
  `textual.pilot` for interaction tests

**Hard constraints:**
- 100% coverage on TUI logic (state, event handlers); pure rendering glue may be
  excluded with a `# pragma: no cover` comment and explanation in conftest
- `mypy --strict` on `src/sox_protocol/tui/`
- `lint-imports` clean
- `demo.py` requires no manual input; deterministic — running twice produces the
  same conversation sequence
- Recording ≤ 60 seconds wall time; artifact ≤ 5 MB on disk

**Acceptance:**
```bash
pytest tests/tui/ --cov=src/sox_protocol/tui --cov-fail-under=100 -q
mypy --strict src/sox_protocol/tui/
lint-imports
python -m sox_protocol.cli chat --help
python examples/two-agents-talking/demo.py   # completes in ≤ 60s, exits 0
ls -lh docs/media/demo.cast docs/media/demo.gif  # both exist, each ≤ 5MB
```

---

## EXECUTION ORDER

```
Engagement 1  reference-agent   agent.py skeleton → lifecycle steps → tests → README
Engagement 2  chat-tui-demo     TUI app → CLI wire-up → demo.py → recording → README embed
```

These engagements are independent of each other (no shared write paths) but are
ordered so the reference agent's integration test can serve as a smoke test that
the full Python stack (identity → middleware → transport → backing store) is wired
correctly before beginning the more complex TUI demo.

Commit each engagement's files before moving on.

---

## PARTIAL COMPLETION

```
PARTIAL_COMPLETION:
- completed_engagements:
  - reference-agent
  - <...>
- remaining_engagements:
  - <...>
- resume_hint: <one sentence>
END_PARTIAL_COMPLETION
```

Stop at an engagement boundary. Never truncate mid-build.

---

## REPORT

One paragraph per engagement — files written, coverage achieved, recording duration
and size (chat-tui-demo only), one implementation decision worth noting.
Total ≤ 200 words.
