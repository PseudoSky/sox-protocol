---
# Consolidated Planner Prompt — parameterised by RUN
# Agent: sox-cto-system:planner
#
# Three runs, all parallelisable (disjoint output paths):
#
#   RUN 1  identity-primitive + hooks-middleware        ~63K tokens
#   RUN 2  http-transport + conformance-suite           ~67K tokens
#   RUN 3  ts-sdk + chat-webapp + reference-agent       ~58K tokens
#           + chat-tui-demo
#
# Set RUN below before dispatching. All runs read the same spec context;
# each writes only its own implementation-plan.json files.
---

RUN: {{1 | 2 | 3}}

You are producing implementation plans for the SOX Protocol. Read all context in
Section 1 to understand the full system — cross-engagement awareness matters because
plans that don't know about each other produce inconsistent file shapes, duplicate
demo coverage, and mismatched API surfaces. Then write only the plans for your RUN.

---

## SECTION 1 — Full architectural context (read, do not output)

### 1a. Protocol surface (read all — every run)

- `spec/protocol.md` — wire envelope: seq, reply_to, delivered_to, origin_server, _meta
- `spec/primitives/` — all 7 files: channels, dms (dm/<sorted-pair>), ack-nack
  (channels_ack tool, not message body), groups, sequence-numbers, presence
  (channels_heartbeat), namespace
- `spec/operations/*.json` — all 16 schemas including the 8 new ones added by
  03-reconcile: channels_ack, channels_heartbeat, channels_collect, replay,
  plus updated send/recv/list_channels
- `spec/ports/` — identity, middleware, backing-store, transport
- `spec/envelopes/*.json`
- `docs/V1-SCOPE.md`
- `docs/adr/0002-agent-identity-primitive.md`
- `docs/adr/0003-extensibility-mechanism.md`

### 1b. Public SDK surface (read all runs — __init__.py only)

```
find packages/python/src/sox_protocol/ -name "__init__.py"
```

Read each file found. These are short (51 lines total) and tell you the public API
without consuming context on internals.

### 1c. Cross-engagement dependency graph

```
identity-primitive ──┐
                     ├──▶ hooks-middleware ──▶ http-transport ──▶ conformance-suite
                     │                                │
                     │                                └──▶ ts-sdk ──▶ chat-webapp
                     │
                     └──▶ reference-agent
                     └──▶ chat-tui-demo
```

Key cross-cutting facts every planner must internalise:

- **channels_ack is a tool, not a message.** ACKs do NOT appear in channel history.
  `spec/envelopes/sox-ack.schema.json` is now the body schema for the tool response.
  Any plan involving ack (conformance fixtures, reference-agent lifecycle, tui demo
  choreography) must reflect this — no `body.type: sox-ack` in channel messages.

- **DMs use `dm/<sorted-pair>` naming.** The channel name is
  `dm/<agent-a-id>~<agent-b-id>` lexicographically sorted. Plans that create DM
  channels (tui demo, reference-agent) must use this convention.

- **seq is now on every message.** Per `spec/primitives/sequence-numbers.md`,
  every recv response includes `seq` (per-channel monotone integer). Plans that
  process recv output (ts-sdk types, webapp MessageThread component, reference-agent
  main_loop, conformance fixtures) must account for `seq`.

- **ts-sdk is chat-webapp's only client dependency.** The webapp component tree
  is designed against the SDK API; plan both together so helpers match usage.

- **conformance-suite covers every operation.** It must include fixtures for all
  8 new operations, not just the original 5. http-transport's wire_format choice
  (SSE vs WebSocket) determines how the conformance runner polls for live recv.

- **Application-layer demos should collectively cover all updated primitives.**
  Divide coverage deliberately across reference-agent, chat-tui-demo, and
  chat-webapp so all 7 primitives appear somewhere without each demo duplicating
  the others' choreography.

---

## SECTION 2 — Run-specific plans

### RUN 1 — identity-primitive + hooks-middleware

**Additional reading for this run:**

Read `packages/python/src/sox_protocol/core/` in full (not __init__.py only) —
you need the complete existing structure to design the migration seam.

Read the two downstream build phases:
- `.workflow/plans/identity-primitive/phases/03-implement.md`
- `.workflow/plans/hooks-middleware/phases/03-implement.md`

**Why these two together:** hooks-middleware *migrates* the identity code from a
standalone module into a registered plugin. Planning both sides of that seam
simultaneously ensures the migration path is coherent — the identity plan designs
the right public API for the middleware plan to then wrap.

---

**Plan A — identity-primitive**

Output: `.workflow/plans/identity-primitive/implementation-plan.json`

```json
{
  "summary": "<one paragraph: what gets built, in what order>",
  "files": [
    {
      "path": "packages/python/src/sox_protocol/core/identity/registry.py",
      "spec_ref": "spec/ports/identity.md §<section>",
      "purpose": "<one sentence>",
      "public_api": ["fn(...) -> ..."]
    }
  ],
  "test_plan": [
    {
      "spec_section": "spec/ports/identity.md §<section>",
      "test_cases": ["test_name — what it validates"]
    }
  ],
  "risks": [{"risk": "...", "mitigation": "..."}],
  "dependencies": ["cryptography>=41"],
  "build_order": ["registry.py", "middleware.py", "audit.py", "tests"],
  "exit_signals": [
    "100% coverage on core/identity/",
    "mypy --strict clean",
    "lint-imports clean (core/ MUST NOT import adapters/)",
    "audit log writes to ~/.sox/logs/identity-failures.jsonl on rejection"
  ]
}
```

Constraints: every files[] entry has spec_ref; test_plan covers every spec section
imposing runtime behaviour; build_order: registry before middleware before tests;
public_api shapes must be consumable by the hooks-middleware plan you are about to
write.

---

**Plan B — hooks-middleware**

Output: `.workflow/plans/hooks-middleware/implementation-plan.json`

```json
{
  "summary": "...",
  "files": [
    {
      "path": "packages/python/src/sox_protocol/core/middleware/pipeline.py",
      "spec_ref": "spec/ports/middleware.md §<section>",
      "purpose": "...",
      "public_api": [...]
    }
  ],
  "test_plan": [{"spec_section": "...", "test_cases": [...]}],
  "risks": [...],
  "dependencies": [...],
  "build_order": [...],
  "exit_signals": [
    "100% coverage on core/middleware/",
    "Identity tests still pass after migration",
    "Sample plugin registered and exercised by tests",
    "lint-imports clean"
  ],
  "migration_notes": "<how identity moves from core/identity standalone to registered plugin; which identity public_api methods become the plugin entry points>"
}
```

Constraints: migration_notes must reference the specific public_api methods from
Plan A; one sample plugin included (suggest: logging → ~/.sox/logs/middleware.jsonl);
plugin must be registerable from outside core/ — write a test that does this from
the test suite, not from core itself.

---

### RUN 2 — http-transport + conformance-suite

**Additional reading for this run:**

Read existing conformance fixtures:
- `spec/conformance/` — all files (audit to avoid duplication)

Read the two downstream build phases:
- `.workflow/plans/http-transport/phases/02-build.md`
- `.workflow/plans/conformance-suite/phases/02-build.md`

**Why these two together:** the conformance runner's `--target http://localhost:<port>`
mode depends on the HTTP transport's wire format. Planning both together means the
fixture format and the transport's SSE/WebSocket choice are designed in concert —
the conformance plan can specify exactly how it polls for async recv responses based
on what the transport plan decides to expose.

---

**Plan A — http-transport**

Output: `.workflow/plans/http-transport/implementation-plan.json`

```json
{
  "summary": "...",
  "files": [
    {
      "path": "packages/python/src/sox_protocol/adapters/transports/http/server.py",
      "spec_ref": "spec/ports/transport.md §<section>",
      "purpose": "...",
      "public_api": [...]
    }
  ],
  "wire_format": {
    "request_response": "JSON over HTTP POST per operation",
    "live_recv": "<SSE | WebSocket — pick with rationale; conformance suite will use this>",
    "auth": "Authorization: Bearer <credential>"
  },
  "openapi": {
    "path": "spec/transports/http/openapi.yaml",
    "generation": "from spec/operations/*.json via tools/openapi_gen.py"
  },
  "cli_subcommand": {
    "name": "sox serve --transport http",
    "env_vars": ["SOX_HTTP_HOST", "SOX_HTTP_PORT", "SOX_HTTP_CORS_ORIGINS"]
  },
  "test_plan": [...],
  "risks": [...],
  "dependencies": ["fastapi", "uvicorn", "sse-starlette"],
  "build_order": [...],
  "exit_signals": [
    "100% coverage on adapters/transports/http/",
    "Conformance suite passes against HTTP target",
    "OpenAPI generated and valid",
    "CORS configurable",
    "GET /health endpoint"
  ]
}
```

Constraints: include CLI modifications and openapi path in files[]; the wire_format
choice you make here will be referenced by the conformance plan's runner logic.

---

**Plan B — conformance-suite**

Output: `.workflow/plans/conformance-suite/implementation-plan.json`

```json
{
  "summary": "...",
  "fixture_format": {
    "language": "yaml",
    "schema": {
      "setup": "operations to run before the test sequence",
      "sequence": "list of {operation, input, expected_output, expected_store_state}",
      "teardown": "optional cleanup"
    }
  },
  "fixtures": [
    {
      "path": "spec/conformance/<category>/<name>.yaml",
      "spec_ref": "spec/<file>.md §<section>",
      "purpose": "<what behaviour this validates>",
      "operations": ["send", "recv", "channels_ack"]
    }
  ],
  "harness": {
    "path": "tools/conformance_runner.py",
    "public_api": [
      "run(target: str, fixtures: list, strict: bool) -> RunResult",
      "targets: 'packages/python' (stdio) | 'http://host:port' (HTTP)"
    ],
    "live_recv_strategy": "<how runner polls for async recv — must match http-transport wire_format choice above>"
  },
  "ci_workflow": {
    "path": ".github/workflows/conformance.yml",
    "matrix": ["python-reference"],
    "future_matrix_entries": ["typescript-reference"]
  },
  "files": [...],
  "test_plan": [...],
  "risks": [...],
  "dependencies": ["pyyaml", "pytest"],
  "build_order": ["harness runner", "category: send-recv-basic", "category: ack-nack", "remaining categories", "CI workflow"],
  "exit_signals": [
    "All fixtures parse (yamllint clean)",
    "Python reference impl passes 100% of fixtures via stdio",
    "Python reference impl passes 100% of fixtures via HTTP",
    "Harness has 100% unit test coverage",
    "CI runs on PR"
  ]
}
```

Fixture categories (must cover all — audit existing spec/conformance/ to avoid
duplication): `send-recv-basic`, `subscription-patterns`, `threading`, `groups`,
`dms` (dm/<sorted-pair> naming), `ack-nack` (channels_ack tool — not message body),
`identity-verification`, `sequence-monotonicity` (seq on every message),
`presence` (channels_heartbeat → sox/presence channel), `replay` (since seq N),
`namespace-isolation`, `channels-collect` (x-status: planned — mark fixtures
as pending, include them but skip in strict mode).

---

### RUN 3 — ts-sdk + chat-webapp + reference-agent + chat-tui-demo

**Additional reading for this run:**

Read the four downstream build phases:
- `.workflow/plans/ts-sdk/phases/02-build.md`
- `.workflow/plans/chat-webapp/phases/02-build.md`
- `.workflow/plans/reference-agent/phases/02-build.md`
- `.workflow/plans/chat-tui-demo/phases/02-build.md`

Read `packages/typescript/` — understand the existing workspace shape before
designing the SDK layout.

**Why these four together:** all four are application-layer consumers of the
protocol. Plan them together so primitive coverage is divided deliberately:

| Primitive | Primary demo vehicle |
|---|---|
| channels (send/recv/subscribe) | all four — baseline |
| seq (message ordering) | chat-webapp MessageThread (visible sequence numbers) |
| reply_to (threading) | reference-agent thread_handling step |
| dm/<sorted-pair> | chat-tui-demo demo script + chat-webapp DM view |
| channels_ack | reference-agent ack_nack step |
| channels_heartbeat / presence | chat-tui-demo agent roster pane |
| replay | chat-webapp replay_mode feature flag |
| namespace | reference-agent bootstrap (connect to named namespace) |
| groups | chat-webapp channel sidebar (group/ prefix channels) |

Decide this division now — build it into each plan's lifecycle, choreography, and
component specs so the four demos are complementary, not redundant.

---

**Plan A — ts-sdk**

Output: `.workflow/plans/ts-sdk/implementation-plan.json`

```json
{
  "summary": "...",
  "package_layout": {
    "workspace": "packages/typescript/",
    "package_name": "@sox-protocol/client",
    "entry_points": {"esm": "dist/index.js", "cjs": "dist/index.cjs", "types": "dist/index.d.ts"}
  },
  "codegen": {
    "tool": "tools/ts_codegen.ts",
    "input": "spec/operations/*.json + spec/envelopes/*.json",
    "output": "packages/typescript/src/generated/",
    "note": "must cover all 16 schemas including 8 new ones from 03-reconcile"
  },
  "files": [
    {"path": "packages/typescript/src/client.ts", "spec_ref": "spec/protocol.md", "purpose": "one method per operation", "public_api": [...]},
    {"path": "packages/typescript/src/helpers.ts", "purpose": "askAndWait, reply, drain, bootstrap", "public_api": [...]},
    {"path": "packages/typescript/src/generated/", "purpose": "schemas → TS types"}
  ],
  "test_plan": [
    {"spec_section": "...", "test_cases": [...]},
    {"category": "integration", "test_cases": ["live recv via SSE against HTTP transport"]}
  ],
  "risks": [...],
  "dependencies": ["typescript", "vitest", "ajv", "eventsource"],
  "build_order": ["codegen tool", "generated types", "client.ts", "helpers.ts", "tests", "build pipeline", "publish config"],
  "exit_signals": [
    "tsc --strict clean",
    "100% coverage via vitest",
    "eslint --max-warnings=0",
    "no `any` in net-new code",
    "npm pack --dry-run succeeds",
    "bundle ≤50KB minified"
  ]
}
```

Constraints: public_api of client.ts and helpers.ts must be sufficient for the
chat-webapp component tree you are about to plan — design the SDK and webapp together.

---

**Plan B — chat-webapp**

Output: `.workflow/plans/chat-webapp/implementation-plan.json`

```json
{
  "summary": "...",
  "stack": {
    "framework": "<React 18 + Vite | Next.js 14 — chosen with rationale>",
    "state": "<Zustand | Jotai | TanStack Query — chosen>",
    "styling": "<Tailwind | CSS Modules — chosen>"
  },
  "deployment": {"static": "<Vercel | Cloudflare | GH Pages>", "rationale": "..."},
  "component_tree": [
    {"component": "App", "children": ["ChannelSidebar", "MessageThread", "AgentPanel", "ComposeBar"]},
    {"component": "MessageThread", "props": [...], "spec_ref": "spec/primitives/sequence-numbers.md",
     "note": "renders seq on each message; supports reply_to threading"},
    {"component": "AgentPanel", "props": [...], "spec_ref": "spec/primitives/presence.md",
     "note": "subscribes to sox/presence, shows online/busy/offline per heartbeat"},
    {"component": "ChannelSidebar", "props": [...], "spec_ref": "spec/primitives/channels.md",
     "note": "distinguishes group/ channels, dm/<sorted-pair> channels, sox/ system channels"}
  ],
  "files": [{"path": "packages/ui/src/...", "spec_ref": "...", "purpose": "...", "public_api": [...]}],
  "feature_flags": {
    "graph_view": "force-directed agent/message graph; off by default",
    "replay_mode": "MessageThread history scrubber using replay operation; off by default"
  },
  "cli_subcommand": {
    "name": "sox ui",
    "behavior": "start HTTP transport on free port, open browser, serve bundled static assets"
  },
  "test_plan": [...],
  "risks": [
    {"risk": "CORS in dev", "mitigation": "HTTP transport advertises permissive CORS for localhost"},
    {"risk": "auth in browser", "mitigation": "credential in sessionStorage only"}
  ],
  "dependencies": [...],
  "build_order": [...],
  "exit_signals": [
    "tsc --strict clean",
    "100% coverage on logic",
    "Lighthouse perf ≥80, a11y ≥95",
    "bundle ≤250KB gzipped",
    "sox ui works end-to-end"
  ]
}
```

---

**Plan C — reference-agent**

Output: `.workflow/plans/reference-agent/implementation-plan.json`

```json
{
  "summary": "...",
  "lifecycle": [
    {"step": "bootstrap", "spec_ref": "spec/protocol.md §bootstrap-sequence",
     "operations": ["subscribe", "list_agents", "list_pending", "drain_unreplied"],
     "annotation": "connect to named namespace; drain unread messages from prior sessions"},
    {"step": "main_loop", "spec_ref": "spec/primitives/sequence-numbers.md",
     "operations": ["recv", "process", "reply"],
     "annotation": "track last seen seq per channel for recovery"},
    {"step": "thread_handling", "spec_ref": "spec/primitives/sequence-numbers.md",
     "operations": ["recv with thread_depth", "reply with reply_to"],
     "annotation": "demonstrates reply_to threading; use thread_depth=-1 to follow full chain"},
    {"step": "ack_nack", "spec_ref": "spec/primitives/ack-nack.md",
     "operations": ["channels_ack"],
     "annotation": "ACK via tool call — NOT a channel message; ack does not appear in history"},
    {"step": "presence_heartbeat", "spec_ref": "spec/primitives/presence.md",
     "operations": ["channels_heartbeat"],
     "annotation": "emit heartbeat on timer; subscribe to sox/presence to observe others"},
    {"step": "graceful_stop", "spec_ref": "spec/protocol.md §graceful-stop",
     "operations": ["channels_heartbeat (offline)", "unsubscribe"],
     "annotation": "mark offline before exit; refuse stop if unreplied messages pending"},
    {"step": "recovery", "spec_ref": "spec/operations/replay.input.schema.json",
     "operations": ["replay from last_seq", "drain_unreplied"],
     "annotation": "reconstruct missed messages after context reset using stored seq"}
  ],
  "files": [
    {"path": "examples/reference-agent/agent.py", "spec_ref": "spec/protocol.md", "purpose": "fully-annotated reference impl", "public_api": [...]},
    {"path": "examples/reference-agent/README.md", "purpose": "prose walkthrough — teaching-grade, mirrors lifecycle[]"},
    {"path": "examples/reference-agent/run_standalone.sh", "purpose": "quick-start, exits 0 within 30s"},
    {"path": "examples/reference-agent/.claude-agent.md", "purpose": "Claude Code agent definition"}
  ],
  "primitive_coverage": "<list which spec/primitives/ each lifecycle step demonstrates — every primitive must appear>",
  "annotation_density": "1 comment line per 3 code lines minimum",
  "test_plan": [...],
  "risks": [...],
  "dependencies": [...],
  "build_order": ["agent.py skeleton", "bootstrap step", "main_loop", "thread_handling", "ack_nack", "presence_heartbeat", "graceful_stop", "recovery", "tests", "README", "run scripts"],
  "exit_signals": [
    "100% coverage on agent.py logic",
    "Integration test: agent + partner exchange a full thread",
    "Standalone run completes in <30s",
    "README walkthrough mirrors lifecycle[]",
    "Every spec/primitives/ file represented in primitive_coverage"
  ]
}
```

---

**Plan D — chat-tui-demo**

Output: `.workflow/plans/chat-tui-demo/implementation-plan.json`

```json
{
  "summary": "...",
  "ui_layout": {
    "panes": [
      {"name": "channel_list", "position": "left", "purpose": "..."},
      {"name": "message_feed", "position": "center", "purpose": "shows seq on each message bubble"},
      {"name": "agent_roster", "position": "right", "purpose": "live presence from sox/presence channel"},
      {"name": "compose_bar", "position": "bottom", "purpose": "..."}
    ],
    "interactions": ["/reply <id>", "/dm <agent>  (opens dm/<a>~<b> channel)", "/join <channel>", "/ack <id>  (channels_ack tool)"]
  },
  "files": [
    {"path": "packages/python/src/sox_protocol/tui/app.py", "spec_ref": "spec/primitives/channels.md", "purpose": "...", "public_api": [...]}
  ],
  "demo_script": {
    "path": "examples/two-agents-talking/demo.py",
    "choreography": [
      {"t": 0,  "action": "agent A sends to #general — seq:1 appears in feed"},
      {"t": 3,  "action": "agent B replies (reply_to set) — seq:2, thread indicator shown"},
      {"t": 6,  "action": "agent A acks via channels_ack — NOT visible in feed"},
      {"t": 9,  "action": "agent A opens DM: /dm agent-b → dm/agent-a~agent-b channel"},
      {"t": 13, "action": "agent B sends heartbeat — roster shows online→busy transition"},
      {"t": 17, "action": "agent B goes offline — roster shows offline, fade"}
    ],
    "duration_seconds": 45,
    "primitives_demonstrated": ["channels", "sequence-numbers", "ack-nack", "dms", "presence"]
  },
  "recording_strategy": {
    "tool": "<asciinema | vhs — pick with rationale>",
    "output": "docs/media/demo.cast",
    "post_process": "render to docs/media/demo.gif for README embed",
    "rationale": "..."
  },
  "test_plan": [...],
  "risks": [...],
  "dependencies": ["textual>=0.40"],
  "build_order": [...],
  "exit_signals": [
    "100% coverage on TUI logic",
    "Demo script reproducible and ≤60s",
    "Recording committed (cast + gif) ≤5MB total"
  ]
}
```

---

## SECTION 3 — Output instructions

Write each plan file to disk. Validate well-formed JSON before moving to the
next plan. After all plans for your run are written, emit one RESERVATIONS block
per engagement:

```
RESERVATIONS:<engagement-slug>:
- <path from plan.files[].path>
- <path>
END_RESERVATIONS:<engagement-slug>
```

Rules: one path per line, prefixed `- `, no globs, no quotes, must exactly match
`plan.files[].path` for that engagement.

REPORT: one paragraph per plan written — file count, key design decision, any
spec gap noticed. Total ≤ 150 words per plan.
