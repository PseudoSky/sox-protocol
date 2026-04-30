---
phase_id: 02-build
title: Build SDK + codegen + helpers
agent: typescript-pro
profile: code-with-spec
estimated_effort: 4-6 days
prereqs: [01-plan]
unblocks: [03-conformance]
parallelizable_with: []
writes: ["packages/typescript/**", "tools/ts_codegen.ts"]
reads:  [".workflow/plans/ts-sdk/implementation-plan.json", "spec/**", "packages/python/src/**"]
context_size: large
---

# 02 — Build

## Inputs

- `.workflow/plans/ts-sdk/implementation-plan.json`
- `spec/operations/*.json`, `spec/envelopes/*.json`
- `spec/transports/http/openapi.yaml`

## Prompt (verbatim)

```text
Build the SOX Protocol TypeScript SDK per the plan.

READ:
1. .workflow/plans/ts-sdk/implementation-plan.json (contract)
2. spec/ (the spec)
3. packages/python/src/sox_protocol/ (Python SDK to mirror)

DELIVER:
- packages/typescript/ workspace per plan.package_layout
- Codegen tool per plan.codegen — JSON Schemas → TS types
- All files in plan.files[]
- ESM + CJS builds; .d.ts type definitions
- Browser-compatible (use eventsource shim or native EventSource)
- Node-compatible (use undici or native fetch)
- Higher-level helpers from plan.files (askAndWait, reply, drain, bootstrap)
- Tests per plan.test_plan[]; integration tests against running Python HTTP server
- npm publish config: package.json, .npmignore, README

HARD CONSTRAINTS:
- tsc --strict --noEmit clean
- 100% coverage via vitest
- eslint --max-warnings=0 clean
- No `any` in net-new code (grep ': any' in src/, allow only in generated/ where unavoidable)
- npm pack --dry-run succeeds
- Bundle size ≤ 50KB minified (browser concern)

ACCEPTANCE:
- cd packages/typescript && pnpm tsc --noEmit --strict
- cd packages/typescript && pnpm vitest run --coverage --coverage.thresholds.100=true
- cd packages/typescript && pnpm eslint . --max-warnings=0
- cd packages/typescript && ! grep -rn ': any' src/ --exclude-dir=generated
- cd packages/typescript && pnpm pack --dry-run

REPORT: ≤ 250 words. File count, generated-types count, bundle size, integration test pass count.
```

## Exit criteria

Universal (`code-with-spec` / `code-typescript`):
- [ ] `cd packages/typescript && pnpm tsc --noEmit --strict`
- [ ] `cd packages/typescript && pnpm vitest run --coverage --coverage.thresholds.100=true`
- [ ] `cd packages/typescript && pnpm eslint . --max-warnings=0`
- [ ] `cd packages/typescript && ! grep -rn ': any' src/ --exclude-dir=generated`
- [ ] `cd packages/typescript && pnpm pack --dry-run`
- [ ] `python3 -c "import json,os; p=json.load(open('.workflow/plans/ts-sdk/implementation-plan.json')); missing=[f['path'] for f in p['files'] if not os.path.exists(f['path'])]; assert not missing"`

## Outputs

- `packages/typescript/`
- `tools/ts_codegen.ts`

## Next state

Promote `03-conformance` → READY.
