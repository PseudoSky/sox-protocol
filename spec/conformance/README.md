# SOX Protocol — Language-Neutral Conformance Suite

This directory is the **verification authority** for SOX v1.0 compliance. Any
implementation that passes all scenarios here is "SOX v1.0-compliant,"
irrespective of implementation language, repository, or maintainer.

---

## Overview

The suite consists of:

| Artefact | Purpose |
|---|---|
| `scenarios/*.json` | Seven scenario files covering the normative wire behaviours |
| `runner/run.sh` | Bash + jq harness that executes scenarios and reports pass/fail |
| `docker-compose.yml` | Compose file for container-based execution against any image |

The harness speaks only the **MCP wire protocol** (HTTP/JSON-RPC). It has no
dependency on any language package under `packages/`. This is by design: the
suite must remain usable by future TypeScript, Rust, or other implementations
without modification.

---

## Running against any implementation

### Requirements

- `docker` and `docker compose` (for the container path), **or**
- `sh`, `curl`, `jq` (for the direct path against a running server)

### Method 1 — Docker Compose (recommended for CI)

Build your implementation into a Docker image that:

- Starts an MCP HTTP (streamable-http) server on `$SOX_HTTP_PORT` (default 8000).
- Reads `SOX_AGENT_ID` (identifies the server process; the runner overrides
  this per-call via the `X-SOX-Agent-ID` request header).
- Reads `SOX_BACKING_STORE` for the backing-store URI.
- Sets `SOX_MCP_TRANSPORT=http`.

Then run:

```bash
export IMPLEMENTATION_IMAGE=my-sox-server:latest
export SPEC_ROOT="$(git rev-parse --show-toplevel)/spec/conformance"

cd spec/conformance
docker compose up --abort-on-container-exit --exit-code-from mcp-test-client
docker compose down -v
```

Exit code 0 means all scenarios passed. Non-zero means at least one failed;
see stdout for per-scenario output.

### Method 2 — Direct (server already running)

If you have a server running at a known URL:

```bash
SOX_SERVER_URL=http://localhost:8000/mcp \
SCENARIOS_DIR=spec/conformance/scenarios \
  sh spec/conformance/runner/run.sh
```

### Method 3 — Python reference implementation

Use the thin wrapper in `packages/python/tests/conformance/`:

```bash
# From the repo root
python packages/python/tests/conformance/run_python_impl.py

# Or via pytest
pytest packages/python/tests/conformance/run_python_impl.py -v -m conformance
```

---

## IMPLEMENTATION_IMAGE contract

The `IMPLEMENTATION_IMAGE` environment variable identifies the Docker image
of the implementation under test. It is the **only required input** to the
docker-compose path.

### What the image MUST do

| Requirement | Detail |
|---|---|
| Expose MCP HTTP | Listen on `0.0.0.0:$SOX_HTTP_PORT` (default 8000) using MCP streamable-http transport |
| Respect `SOX_AGENT_ID` | Use this value as the agent identity for the backing-store agent routing |
| Respect `SOX_BACKING_STORE` | URI-scheme-based backing store selection (`memory://`, `sqlite://...`, etc.) |
| Respect `SOX_MCP_TRANSPORT=http` | Must start HTTP transport when this env var is set |
| Respond to healthcheck | The compose healthcheck POSTs an MCP `initialize` request; the server must respond before tool calls begin |
| Handle `X-SOX-Agent-ID` header | The conformance runner sets this header on every request to identify the calling agent; the server MUST use this to route per-agent state (subscriptions, recv buffers) |

### What the image MUST NOT require

- A pre-seeded database (the compose `tmpfs` volume gives a clean `/data`).
- Network access outside the `sox-conformance` Docker network.
- Any ports other than `SOX_HTTP_PORT`.

### Example — Python reference image

```bash
# Build from the repo root (build context must include both spec/ and packages/python/)
docker build \
  -f packages/python/Dockerfile \
  -t sox-protocol-python:latest \
  .

IMPLEMENTATION_IMAGE=sox-protocol-python:latest \
SPEC_ROOT="$(pwd)/spec/conformance" \
  docker compose -f spec/conformance/docker-compose.yml \
  up --abort-on-container-exit --exit-code-from mcp-test-client
```

---

## Scenario coverage

| File | What it verifies |
|---|---|
| `01-send-and-recv.json` | Single sender + receiver; exact round-trip; output conforms to `recv.output.schema.json` |
| `02-group-broadcast.json` | One sender, three receivers on the same channel; all three receive independently |
| `03-subscription-glob.json` | Glob patterns (`ticket:proj-*`) deliver matching messages only; non-matching channels do not leak |
| `04-concurrent-writers.json` | 5 writers × 4 messages = 20 total; no loss, no duplication |
| `05-per-channel-ordering.json` | Within a channel, send-time order preserved; body `seq` field verifies order end-to-end |
| `06-listener-buffering.json` | Message arrives before `recv`; the listener's watch-loop must have buffered it |
| `07-recv-atomicity.json` | Second `recv` by same agent returns empty; concurrent recv by another agent is unaffected |

---

## Scenario file format

Each scenario is a JSON object:

```jsonc
{
  "name": "short-identifier",
  "description": "Human-readable purpose",
  "agents": { ... },           // agent role → agent_id mapping (informational)
  "setup": [ ... ],            // optional pre-test MCP calls (subscribe, etc.)
  "steps": [
    {
      "id": "step-id",         // referenced by assertions
      "agent": "agent-id",     // X-SOX-Agent-ID header value
      "tool": "channels__send", // MCP tool name
      "args": { ... },         // tool arguments
      "expect": {              // per-field type predicates (checked immediately)
        "field": { "type": "number|string|array", "minItems": N }
      },
      "capture": ["field"],    // capture these fields for later assertions
      "assertions": [ ... ]   // per-step inline assertions
    },
    {
      "id": "sleep-id",
      "type": "sleep",         // special step: pause execution
      "milliseconds": 500
    }
  ],
  "assertions": [              // scenario-level assertions checked after all steps
    {
      "type": "no_loss",       // see assertion types below
      "recv_step": "recv-1",
      "min": 1
    }
  ]
}
```

### Assertion types

| Type | Checks |
|---|---|
| `no_loss` | `recv_step` result has `>= min` messages |
| `no_duplication` | All `message_id` values in `recv_step` are unique |
| `no_redelivery` | `recv_step` result has exactly `expected_count` messages (used for second-recv = 0) |
| `independent_delivery` | `recv_step` result has `>= min` messages (for second subscriber) |
| `ordering` | Messages on `channel` in `recv_step` are in ascending `by` (field) order |
| `body_seq_ascending` | `body[body_field]` values on `channel` are ascending integers |
| `received_count` | `recv_step` message count is in `[min, max]` |
| `no_channel_leak` | No message in `recv_step` has `channel == forbidden_channel` |
| `all_channels_match_pattern` | All channels in `recv_step` match the glob `pattern` |
| `all_receivers_got_message` | Each step in `recv_steps` has `>= 1` message |
| `all_writers_represented` | For each value in `writers`, at least one message with `body[body_field] == writer` exists in `recv_step` |
| `message_id_present` | The `message_id` captured from `capture_ref` step appears in `recv_step` |
| `schema_valid` | (Informational) step output conforms to the named spec schema |

---

## Adding the suite to a new language port

1. Build your implementation into a Docker image satisfying the contract above.
2. Create `packages/<lang>/tests/conformance/run_<lang>_impl.<ext>` following
   the same pattern as `packages/python/tests/conformance/run_python_impl.py`:
   - Start your MCP server.
   - Set `SOX_SERVER_URL`.
   - Execute `spec/conformance/runner/run.sh`.
   - Propagate exit code.
3. Add a CI job mirroring `conformance` in `.github/workflows/python-ci.yml`.
4. When all seven scenarios pass, open a PR; the badge workflow picks it up.

No changes to `spec/conformance/` are needed. The harness is language-neutral.

---

## What conformance does NOT verify

Per CONTRACTS.md §10.4:

- Performance (latency, throughput, memory usage).
- Operational durability (crash recovery, backing-store restart behaviour).
- Quality of the runtime adapter's discipline prompt-engineering.
- Adherence to the host runtime's idioms.

These are implementation quality concerns evaluated per-implementation by
operators.
