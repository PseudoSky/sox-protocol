---
slug: conformance-suite
state: initialized
bucket: protocol+implementation
stream: A
created: 2026-04-29
last_event: 2026-04-29T00:00:00Z
priority: high
unblocks: []
depends_on: [spec-extraction]
---

# Engagement: conformance-suite

## Objective
Build a language-agnostic conformance test suite — JSON-in/JSON-out fixtures that any implementation (Python, Rust, TS, …) must pass. Wires up Python reference impl in CI as the first conformant target.

## Acceptance criteria
- [ ] `spec/conformance/` directory with declarative test fixtures (YAML or JSON)
- [ ] Fixture format documented: setup, sequence of operations, expected responses, expected store state
- [ ] Categories covered (minimum v1 set):
  - send / recv basic flow
  - subscription patterns
  - threading via `reply_to`
  - groups (membership, send-to-group)
  - DM addressing
  - ACK / NACK envelope handling
  - identity verification (rejection on mismatch)
  - sequence number monotonicity
- [ ] Python harness `tools/conformance_runner.py` that loads fixtures and runs them against any conformant implementation
- [ ] CI job runs the harness against `packages/python/` on every PR
- [ ] README under `spec/conformance/` documents how a third-party implementation registers itself

## Inputs
- Output of spec-extraction (the spec is the truth source)

## Outputs
- `spec/conformance/*.yaml` fixtures
- `tools/conformance_runner.py`
- CI workflow update

## Suggested executor
`test-automator`.

## State transitions
- 2026-04-29 initialized — workflow-architect
