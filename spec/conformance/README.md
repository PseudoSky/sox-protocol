<!-- SPDX-License-Identifier: Apache-2.0 -->
# SOX Protocol — Language-Neutral Conformance Suite

This directory is the **verification authority** for SOX v1.0 compliance. Any
implementation that passes all scenarios here is "SOX v1.0-compliant,"
irrespective of implementation language, repository, or maintainer.

---

## Overview

The suite consists of:

| Artefact | Purpose |
|---|---|
| `<category>/*.yaml` | Declarative YAML fixtures covering all 12 fixture categories |
| `scenarios/*.json` | Legacy JSON scenarios (superseded by YAML; kept for reference) |
| `runner/run.sh` | Bash + jq harness for the legacy JSON scenarios |
| `docker-compose.yml` | Compose file for container-based execution against any image |

The primary harness is `tools/conformance_runner.py` at the repository root,
which loads YAML fixtures and runs them against any conformant target. It has
no dependency on any language package under `packages/` except when targeting
the Python reference implementation directly.

---

## Fixture Format (YAML)

Each fixture is a YAML file with the following shape:

```yaml
name: human-readable-fixture-name           # required
spec_ref: spec/<file>.md#section            # required — normative spec reference
description: >                              # required — what this fixture verifies
  Human-readable description.

pending: true                               # optional — if true, runner skips in
                                            # --strict mode (use for x-status: planned
                                            # operations like channels_collect)

agents:                                     # optional list of virtual agents
  - id: agent-a                             # agent_id used in sequence steps
    credential: secret-a                    # credential string for auth
  - id: agent-b
    credential: secret-b

setup:                                      # optional — steps run before sequence;
  - operation: subscribe                    # responses ignored unless asserted
    as_agent: agent-b
    input:
      pattern: "test:channel"

sequence:                                   # required — ordered list of steps
  - id: step-id                             # unique within fixture; referenced by assertions
    as_agent: agent-a                       # which agent runs this step
    operation: send                         # SOX operation name (see Operations below)
    input:                                  # tool input arguments
      channel: "test:channel"
      body:
        type: status_update
        subject: hello
    expected_output:                        # optional subset match (wildcards supported)
      message_id: "{{any_string}}"
      seq: 1
    expected_error:                         # optional — expect an error response
      error_code: "{{any_string}}"

  - id: sleep-step                          # special sleep step
    type: sleep
    milliseconds: 500

assertions:                                 # optional fixture-level assertions
  - type: no_loss
    recv_step: recv-1
    min: 1
```

### Wildcards in `expected_output`

| Wildcard | Matches |
|---|---|
| `{{any_string}}` | Any non-null string value |
| `{{any_number}}` | Any integer or float |
| `{{any_array}}` | Any list |
| `{{any_object}}` | Any dict/object |
| `{{any_bool}}` | Any boolean |
| `{{capture:step-id.field}}` | The value captured from a previous step's output field |

### Operations

The following SOX operation names are valid in `operation:` fields:

| Operation | MCP tool name |
|---|---|
| `send` | `channels__send` |
| `recv` | `channels__recv` |
| `subscribe` | `channels__subscribe` |
| `unsubscribe` | `channels__unsubscribe` |
| `list_channels` | `channels__list_channels` |
| `channels_ack` | `channels__ack` |
| `channels_heartbeat` | `channels__heartbeat` |
| `replay` | `channels__replay` |
| `group_create` | `channels__group_create` |
| `group_invite` | `channels__group_invite` |
| `group_join` | `channels__group_join` |
| `group_leave` | `channels__group_leave` |
| `group_list_members` | `channels__group_list_members` |
| `channels_collect` | `channels__collect` |

### Assertion Types

| Type | Fields | Checks |
|---|---|---|
| `no_loss` | `recv_step`, `min` | Step has `>= min` messages |
| `no_duplication` | `recv_step` | All `message_id` values are unique |
| `no_redelivery` | `recv_step`, `expected_count` | Step has exactly `expected_count` messages |
| `independent_delivery` | `recv_step`, `min` | Step has `>= min` messages (second subscriber) |
| `ordering` | `recv_step`, `channel`, `by` | Messages on channel are in ascending `by` (field) order |
| `body_seq_ascending` | `recv_step`, `channel`, `body_field` | `body[body_field]` values are ascending integers |
| `received_count` | `recv_step`, `min`, `max` | Message count in `[min, max]` |
| `no_channel_leak` | `recv_step`, `forbidden_channel` | No message has `channel == forbidden_channel` |
| `all_channels_match_pattern` | `recv_step`, `pattern` | All channels match the glob `pattern` |
| `all_receivers_got_message` | `recv_steps` | Each step in `recv_steps` has `>= 1` message |
| `all_writers_represented` | `recv_step`, `writers`, `body_field` | Each writer value appears in at least one message body |
| `message_id_present` | `recv_step`, `capture_ref` | The captured message_id appears in recv results |
| `schema_valid` | — | Informational only; not enforced by runner |

---

## Fixture Categories

| Category | Fixtures | What they verify |
|---|---|---|
| `send-recv-basic/` | 3 | Basic round-trip, empty recv, _meta toggle |
| `subscription-patterns/` | 3 | Glob match, unsubscribe discard, multi-pattern dedup |
| `threading/` | 2 | reply_to link, deep 3-level thread |
| `groups/` | 3 | Create/invite/join, broadcast fan-out, leave |
| `dms/` | 2 | Sorted-pair naming, third-party cannot read |
| `ack-nack/` | 2 | ACK as tool (not message), NACK via channels_ack |
| `identity-verification/` | 2 | Server-certified sender, unknown credential rejected |
| `sequence-monotonicity/` | 2 | seq starts at 1, monotone per-channel independence |
| `presence/` | 2 | Heartbeat updates sox/presence, stale marks offline (pending) |
| `replay/` | 2 | Replay since_seq, empty future cursor |
| `namespace-isolation/` | 2 | Scoped channels (pending), version block |
| `channels-collect/` | 1 | collect N replies (pending — x-status: planned) |
| `plugin-contract/` | 7 | Plugin load via entry-point, version-mismatch refusal, kind-taxonomy enforcement, applies-to scope, ordering constraints, short-circuit halt, synthetic provider lifecycle — **all pending** until P4 (`plugin-discovery-py`) + P5 (`reference-plugins`) ship |

---

## Running the Conformance Suite

### Prerequisites

```bash
pip install pyyaml pytest pytest-cov httpx yamllint
pip install -e packages/python[dev]
```

### Method 1 — Python reference implementation (in-process)

```bash
# From the repository root
python3 tools/conformance_runner.py --target packages/python --strict
```

### Method 2 — HTTP target (against a running server)

```bash
# Start the server
SOX_MCP_TRANSPORT=http SOX_HTTP_PORT=8765 \
  python -m sox_protocol.core.mcp_server &

# Run conformance
python3 tools/conformance_runner.py \
  --target http://localhost:8765 --strict

kill %1
```

### Method 3 — Filter by category

```bash
python3 tools/conformance_runner.py \
  --target packages/python \
  --category identity-verification,send-recv-basic \
  --strict
```

### Harness unit tests (100% coverage required)

```bash
cd tools
pytest conformance_runner_tests/ \
  --cov=conformance_runner \
  --cov-fail-under=100 \
  -q
```

### Lint fixture YAML

```bash
yamllint -d relaxed spec/conformance/
```

---

## Pending Fixtures

Fixtures marked `pending: true` are:

- **Skipped** in `--strict` mode (used in CI).
- **Run but reported separately** in non-strict mode.

Use `pending: true` for:
- Operations with `x-status: planned` in their schema (e.g., `channels_collect`).
- Fixtures that require timing-dependent server behaviour (e.g., stale heartbeat
  after 30 s timeout).
- Fixtures that require multi-server namespace configuration not available in
  the default single-server setup.
- Fixtures whose required implementation has not yet shipped. All 7 fixtures in
  `plugin-contract/` are `pending: true` until engagement P4 (`plugin-discovery-py`)
  wires the Python entry-point loader and engagement P5 (`reference-plugins`) ships
  the `io.sox.schema-strict` transformer plugin. When those engagements complete,
  `pending: true` MUST be removed from each fixture that passes. Any fixture that
  cannot be un-skipped at that point MUST document the blocking reason.

---

## Adding Fixtures for a New Language Port

1. Build your implementation into a Docker image satisfying the
   `IMPLEMENTATION_IMAGE` contract (see original `docker-compose.yml`).
2. Create `packages/<lang>/tests/conformance/run_<lang>_impl.<ext>` following
   the pattern in `packages/python/tests/conformance/run_python_impl.py`:
   - Start your server.
   - Run `tools/conformance_runner.py --target http://localhost:<port> --strict`.
   - Propagate exit code.
3. Add a CI job mirroring the `conformance` workflow.
4. When all non-pending fixtures pass, open a PR.

**No changes to `spec/conformance/` are needed.** The YAML fixtures and the
runner are language-neutral.

---

## Registering a Third-Party Target

Any implementation may be tested against these fixtures by invoking:

```bash
python3 tools/conformance_runner.py \
  --target http://<your-server-host>:<port> \
  --strict
```

The server MUST:
- Accept `X-SOX-Agent-ID` header to identify the calling agent.
- Expose `POST /v1/ops/<operation>` endpoints for each SOX operation.
- Return JSON responses conforming to the operation output schemas.

---

## What Conformance Does NOT Verify

Per CONTRACTS.md §10.4:

- Performance (latency, throughput, memory usage).
- Operational durability (crash recovery, backing-store restart behaviour).
- Quality of the runtime adapter's discipline prompt-engineering.
- Adherence to the host runtime's idioms.
- Operations marked `x-status: planned` in their JSON Schema.

These are implementation quality concerns evaluated per-implementation by operators.
