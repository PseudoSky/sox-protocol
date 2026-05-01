---
phase_id: 01-plan
title: SDK + codegen plan
agent: sox-cto-system:planner
profile: planning
estimated_effort: 2-3 hours
prereqs: []
unblocks: [02-build]
parallelizable_with: []
writes: [".workflow/plans/ts-sdk/implementation-plan.json"]
reads:  ["spec/**", "packages/python/src/**"]
context_size: medium
---

# 01 — Plan

## Inputs

- `spec/operations/*.json`, `spec/envelopes/*.json` (the schemas to codegen from)
- `spec/ports/transport.md`, `spec/transports/http/openapi.yaml`
- `packages/python/src/sox_protocol/` (Python SDK to mirror)

## Prompt (verbatim)

```text
JSON plan for the SOX Protocol TypeScript client SDK.

READ:
- spec/protocol.md (authoritative v1 operation table — 14 ops; every op needs a TS binding)
- spec/operations/*.json, spec/envelopes/*.json (codegen sources)
- spec/transports/http/openapi.yaml (HTTP wire format)
- packages/python/src/sox_protocol/ (Python SDK to mirror in shape)
- .workflow/plans/ts-sdk/phases/02-build.md (downstream build phase — read it so your package layout, codegen tool path, public_api shapes, and test_plan match what the builder expects)

OUTPUT: /Users/nix/dev/ai/sox-protocol/.workflow/plans/ts-sdk/implementation-plan.json

SHAPE:
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
    "output": "packages/typescript/src/generated/"
  },
  "files": [
    {"path": "tools/ts_codegen.ts", "spec_ref": "spec/operations/", "purpose": "codegen script: spec JSON schemas → TS types"},
    {"path": "packages/typescript/package.json", "purpose": "npm package manifest"},
    {"path": "packages/typescript/tsconfig.json", "purpose": "tsc --strict config"},
    {"path": "packages/typescript/vitest.config.ts", "purpose": "vitest config"},
    {"path": "packages/typescript/.eslintrc.json", "purpose": "eslint config"},
    {"path": "packages/typescript/src/client.ts", "spec_ref": "spec/protocol.md", "purpose": "low-level client — one method per v1 MUST operation", "public_api": [...]},
    {"path": "packages/typescript/src/helpers.ts", "purpose": "askAndWait, reply, drain, bootstrap", "public_api": [...]},
    {"path": "packages/typescript/src/generated/", "purpose": "schemas → TS types (directory entry covers all generated files)"},
    {"path": "packages/typescript/src/index.ts", "purpose": "barrel re-export"},
    ...
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
    "eslint --max-warnings=0 clean",
    "no `any` in net-new code",
    "npm pack --dry-run succeeds",
    "TS conformance harness passes"
  ]
}

END YOUR REPORT WITH A RESERVATIONS BLOCK.

The orchestrator extracts this block to gate parallel dispatch of the downstream 02-build phase. After your prose REPORT, output (no other text after):

RESERVATIONS:
- <path>
- <path>
END_RESERVATIONS

Rules:
- One path per line, prefixed with `- `
- Plain string paths, no globs, no quotes
- The list MUST equal plan.files[].path exactly (the codegen tool and all config files are already in the files[] shape above).

REPORT: file count, codegen approach, key public-API differences from Python SDK. Then the RESERVATIONS block.
```

## Exit criteria

Universal (`planning`):
- [ ] `test -f .workflow/plans/ts-sdk/implementation-plan.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/ts-sdk/implementation-plan.json')); assert all(k in p for k in ['summary','package_layout','codegen','files','test_plan','exit_signals'])"`
- [ ] `test -f .workflow/plans/ts-sdk/reservations/02-build.json`
- [ ] `python3 -c "import json; p=json.load(open('.workflow/plans/ts-sdk/implementation-plan.json')); r=json.load(open('.workflow/plans/ts-sdk/reservations/02-build.json')); assert set(f['path'] for f in p['files']) == set(r['files'])"`

## Outputs

- `.workflow/plans/ts-sdk/implementation-plan.json`

## Next state

Promote `02-build` → READY.
