---
# Implementer Prompt A — Spec Implementation + Conformance Feedback Loop
# Agent: python-pro
# Engagements: conformance-suite/02-build (harness first),
#              identity-primitive/03-implement,
#              hooks-middleware/03-implement,
#              http-transport/02-build
#
# PREREQUISITE: All 4 implementation-plan.json files must exist on disk.
# UNBLOCKS: implementer-B-typescript.md, implementer-C-python-apps.md
---

You are building the SOX Protocol spec implementation — the Python protocol core plus
the conformance harness that validates it. Build the conformance harness FIRST so every
subsequent implementation engagement has a runnable test loop. After each engagement's
acceptance commands pass, immediately run the conformance suite against the target to
confirm spec fidelity before moving on.

## READ ONCE (shared context)

1. `spec/protocol.md` and `spec/primitives/` — all primitive files
2. `spec/operations/*.json` — all 16 operation schemas
3. `spec/ports/` — identity, middleware, backing-store, transport contracts
4. `spec/envelopes/*.json`
5. `docs/adr/0002-agent-identity-primitive.md`
6. `docs/adr/0003-extensibility-mechanism.md`
7. `docs/V1-SCOPE.md`
8. `packages/python/src/sox_protocol/` — existing SDK shape
9. `spec/conformance/` — existing fixtures (audit, do not duplicate)

Then read each engagement's `implementation-plan.json` before building it.

---

## STEP 1 — Build the conformance harness (feedback tool)

**Plan:** `.workflow/plans/conformance-suite/implementation-plan.json`

Build the harness and fixtures before anything else. This is your test loop for all
subsequent engagements — you will re-run it after each one.

Read additionally:
- `.workflow/plans/conformance-suite/phases/02-build.md`
- `packages/python/` (first conformant target)

**Deliver:**
- Every fixture in `plan.fixtures[]` at the exact path — declarative YAML: setup,
  operation sequence, expected responses, expected store state
- `tools/conformance_runner.py` per `plan.harness` — loads `spec/conformance/`
  recursively, runs each fixture against target, reports per-fixture pass/fail with diffs
- `spec/conformance/README.md` explaining fixture format and third-party registration
- `tools/conformance_runner_tests/` — harness unit tests, 100% line coverage
- `.github/workflows/conformance.yml` per `plan.ci_workflow`

Fixture categories to cover (minimum): `send-recv-basic`, `subscription-patterns`,
`threading`, `groups`, `dms`, `ack-nack`, `identity-verification`,
`sequence-monotonicity`, `presence`.

**Acceptance:**
```bash
pytest tools/conformance_runner_tests/ --cov=tools.conformance_runner --cov-fail-under=100 -q
yamllint spec/conformance/
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/conformance.yml'))"
```

> At this point the harness exists but the Python target will not pass all fixtures
> yet — that is expected. Proceed to Step 2.

---

## STEP 2 — identity-primitive

**Plan:** `.workflow/plans/identity-primitive/implementation-plan.json`

Read additionally:
- `spec/ports/identity.md`
- `spec/ports/middleware.md`
- `packages/python/src/sox_protocol/core/` (existing structure)

**Deliver:**
- Every file in `plan.files[]` at the exact path
- Tests for every `plan.test_plan[].test_cases[]` entry
- `~/.sox/logs/identity-failures.jsonl` — one line per rejected request:
  `{ts, claimed_agent_id, reason, operation}`
- Identity middleware registered as first in the pipeline; unverified callers
  rejected before any backing-store access

**Hard constraints:**
- 100% line coverage on `packages/python/src/sox_protocol/core/identity/`
- `mypy --strict` clean
- `lint-imports` — `core/` MUST NOT import from `adapters/`
- `ruff` clean; no secrets in source

**Acceptance:**
```bash
pytest packages/python/tests/identity/ -q
pytest --cov=src/sox_protocol/core/identity --cov-fail-under=100
mypy --strict src/sox_protocol/core/identity/
lint-imports
```
Also confirm: rejection-path integration test produces an audit log entry in
`~/.sox/logs/identity-failures.jsonl`.

**Conformance loop:**
```bash
python3 tools/conformance_runner.py --target packages/python \
  --category identity-verification --strict
```
Fix any fixture failures before proceeding to Step 3. The conformance runner is
the authoritative signal — a passing unit test suite with failing conformance fixtures
means the implementation diverges from spec.

---

## STEP 3 — hooks-middleware

**Plan:** `.workflow/plans/hooks-middleware/implementation-plan.json`

Read additionally:
- `spec/ports/middleware.md`
- `packages/python/src/sox_protocol/core/identity/` (code to migrate per
  `plan.migration_notes`)

**Deliver:**
- Every file in `plan.files[]`
- Identity check migrated to middleware plugin per `plan.migration_notes`;
  existing identity tests remain green (regression check)
- One sample plugin (logging → `~/.sox/logs/middleware.jsonl` or rate-limit)
- Plugin registration documented in module docstring

**Hard constraints:**
- 100% line coverage on `core/middleware/`
- `mypy --strict`, `lint-imports`, `ruff` clean
- Plugin registerable from outside `core/` — test this from the test suite,
  not from core itself

**Acceptance:**
```bash
pytest tests/middleware/ -q
pytest tests/identity/ -q                           # regression
pytest --cov=src/sox_protocol/core/middleware --cov-fail-under=100
mypy --strict src/sox_protocol/core/middleware/
lint-imports
```

**Conformance loop:**
```bash
python3 tools/conformance_runner.py --target packages/python \
  --category identity-verification,send-recv-basic --strict
```
The identity-verification fixtures now run through the middleware pipeline.
Fix any regressions before Step 4.

---

## STEP 4 — http-transport

**Plan:** `.workflow/plans/http-transport/implementation-plan.json`

Read additionally:
- `spec/ports/transport.md`
- `spec/operations/*.json`
- `packages/python/src/sox_protocol/adapters/transports/stdio/` (existing model)

**Deliver:**
- `packages/python/src/sox_protocol/adapters/transports/http/` per `plan.files[]`
- `spec/transports/http/openapi.yaml` generated from operation schemas
- `tools/openapi_gen.py` if plan calls for codegen
- `sox serve --transport http` CLI subcommand wired
- SSE or WebSocket for live recv (per `plan.wire_format`)
- Identity middleware integrated (Authorization: Bearer → credential check)
- `GET /health` endpoint; CORS configurable via env

**Hard constraints:**
- 100% coverage on `adapters/transports/http/`
- `mypy --strict`, `lint-imports` (adapter may import core; core MUST NOT import adapter)
- `ruff` clean
- OpenAPI valid: `openapi-spec-validator spec/transports/http/openapi.yaml`

**Acceptance:**
```bash
pytest tests/transports/http/ --cov=src/sox_protocol/adapters/transports/http --cov-fail-under=100 -q
mypy --strict src/sox_protocol/adapters/transports/http/
lint-imports
python -m sox_protocol.cli serve --transport http --port 8765 &
sleep 2 && curl -sf http://localhost:8765/health && kill %1
python -m openapi_spec_validator spec/transports/http/openapi.yaml
```

**Conformance loop — full suite against HTTP target:**
```bash
python -m sox_protocol.cli serve --transport http --port 8765 &
sleep 2
python3 tools/conformance_runner.py --target http://localhost:8765 --strict
kill %1
```
This is the definitive conformance gate. All fixtures in all categories must pass
against the HTTP transport before this step is considered complete. Fix any failures
by tracing back to which layer (transport, middleware, or identity) is at fault.

**Also run conformance against stdio (regression):**
```bash
python3 tools/conformance_runner.py --target packages/python --strict
```

---

## EXECUTION ORDER SUMMARY

```
Step 1  conformance-suite   Build harness + fixtures (feedback tool)
Step 2  identity-primitive  Build → unit tests → conformance:identity-verification
Step 3  hooks-middleware    Build → unit tests + regression → conformance:identity+send-recv
Step 4  http-transport      Build → unit tests → full conformance (stdio + HTTP)
```

After each acceptance block passes AND the conformance loop exits 0, commit that
engagement's files before proceeding. Use `git add -p` to stage only the current
engagement's files.

---

## PARTIAL COMPLETION

If context budget runs short, stop at a step boundary:

```
PARTIAL_COMPLETION:
- completed_steps:
  - conformance-suite (harness)
  - identity-primitive
  - <...>
- remaining_steps:
  - <...>
- conformance_status: <last conformance run result — categories passed, categories failed>
- resume_hint: <one sentence>
END_PARTIAL_COMPLETION
```

Never truncate mid-step. Finish the step's conformance loop before stopping.

---

## REPORT

One paragraph per step — files written, unit test coverage, conformance fixture
pass rate, one implementation decision worth noting. Include a final line:

```
GATE: implementer-B and implementer-C may proceed.
```

only if all four acceptance blocks and the full conformance suite (stdio + HTTP) exit 0.
Total report ≤ 300 words.
