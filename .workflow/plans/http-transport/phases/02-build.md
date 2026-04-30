---
phase_id: 02-build
title: Build adapter + serve subcommand
agent: python-pro
profile: code-with-spec
estimated_effort: 3-5 days
prereqs: [01-plan]
unblocks: [03-conformance]
parallelizable_with: []
writes: ["packages/python/src/sox_protocol/adapters/transports/http/**", "packages/python/tests/transports/http/**", "spec/transports/http/**", "tools/openapi_gen.py", "packages/python/src/sox_protocol/cli/**"]
reads:  [".workflow/plans/http-transport/implementation-plan.json", "spec/**", "packages/python/src/**"]
context_size: large
---

# 02 — Build

## Inputs

- `.workflow/plans/http-transport/implementation-plan.json`
- `spec/ports/transport.md`
- `spec/operations/*.json`

## Prompt (verbatim)

```text
Build the SOX Protocol HTTP transport adapter per the plan.

READ:
1. .workflow/plans/http-transport/implementation-plan.json (contract)
2. spec/ports/transport.md
3. spec/operations/*.json
4. packages/python/src/sox_protocol/adapters/transports/stdio/ (model)

DELIVER:
- packages/python/src/sox_protocol/adapters/transports/http/ per plan.files[]
- spec/transports/http/openapi.yaml generated from operation schemas
- tools/openapi_gen.py if codegen is needed
- `sox serve --transport http` CLI subcommand wired
- SSE or WebSocket for live recv (per plan.wire_format)
- Identity middleware integrated (Authorization: Bearer header → credential check)
- GET /health endpoint
- CORS configurable

HARD CONSTRAINTS:
- 100% coverage on adapters/transports/http/
- mypy --strict
- lint-imports clean (this is an adapter — can import from core, not vice versa)
- ruff clean
- OpenAPI valid: openapi-spec-validator spec/transports/http/openapi.yaml passes

ACCEPTANCE:
- pytest tests/transports/http/ --cov=src/sox_protocol/adapters/transports/http --cov-fail-under=100 -q
- mypy --strict src/sox_protocol/adapters/transports/http/
- lint-imports
- python -m sox_protocol.cli serve --transport http --port 8765 starts and responds to GET /health within 5s
- python -m openapi_spec_validator spec/transports/http/openapi.yaml exits 0

REPORT: ≤ 250 words. File list, wire-format choice, OpenAPI endpoint count.
```

## Exit criteria

Universal (`code-with-spec` / `code-python`):
- [ ] `cd packages/python && pytest tests/transports/http/ --cov=src/sox_protocol/adapters/transports/http --cov-fail-under=100 -q`
- [ ] `cd packages/python && mypy --strict src/sox_protocol/adapters/transports/http/`
- [ ] `cd packages/python && lint-imports`
- [ ] `cd packages/python && ruff check src/sox_protocol/adapters/transports/http/`
- [ ] `python3 -c "import json,os; p=json.load(open('.workflow/plans/http-transport/implementation-plan.json')); missing=[f['path'] for f in p['files'] if not os.path.exists(f['path'])]; assert not missing"`

Engagement-specific:
- [ ] `test -f spec/transports/http/openapi.yaml`
- [ ] `python3 -m openapi_spec_validator spec/transports/http/openapi.yaml`

## Outputs

- `packages/python/src/sox_protocol/adapters/transports/http/`
- `spec/transports/http/openapi.yaml`
- `tools/openapi_gen.py` (if used)
- `sox serve --transport http` CLI

## Next state

Promote `03-conformance` → READY.
