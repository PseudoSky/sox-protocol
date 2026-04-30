---
phase_id: 02-build
title: Build app + integrate SDK
agent: react-specialist
profile: code-with-spec
estimated_effort: 5-7 days
prereqs: [01-plan]
unblocks: [03-polish]
parallelizable_with: []
writes: ["packages/ui/**", "packages/python/src/sox_protocol/cli/**", "packages/python/src/sox_protocol/ui_assets/**"]
reads:  [".workflow/plans/chat-webapp/implementation-plan.json", "spec/**", "packages/typescript/**"]
context_size: large
---

# 02 — Build

## Inputs

- `.workflow/plans/chat-webapp/implementation-plan.json`
- `packages/typescript/` (the SDK)
- `spec/protocol.md`, `spec/primitives/`

## Prompt (verbatim)

```text
Build the SOX Protocol web app per the plan.

READ:
1. .workflow/plans/chat-webapp/implementation-plan.json (contract)
2. packages/typescript/ (the SDK to consume)
3. spec/protocol.md, spec/primitives/

DELIVER:
- packages/ui/ workspace per plan
- All components in plan.component_tree
- All files in plan.files[]
- `sox ui` CLI subcommand wired in packages/python/src/sox_protocol/cli/ that starts HTTP transport + serves bundled static assets + opens browser
- Built static assets bundled with the Python package (so `pip install sox-protocol[ui]` ships them)
- Tests per plan.test_plan[]
- Live updates via watch() — no polling

HARD CONSTRAINTS:
- tsc --strict
- 100% coverage on logic (state, hooks, event handlers); rendering glue may be excluded with documented justification
- eslint --max-warnings=0
- No `any`
- Lighthouse performance ≥ 80, a11y ≥ 95 (run via `npx lhci autorun` against built bundle)
- Bundle ≤ 250KB gzipped

ACCEPTANCE:
- cd packages/ui && pnpm tsc --noEmit --strict
- cd packages/ui && pnpm vitest run --coverage --coverage.thresholds.100=true (with documented omits)
- cd packages/ui && pnpm eslint . --max-warnings=0
- cd packages/ui && pnpm build (succeeds; bundle size logged)
- python -m sox_protocol.cli ui --help (subcommand wired)
- npx lhci autorun (perf ≥ 80, a11y ≥ 95)

REPORT: ≤ 250 words. Bundle size, Lighthouse scores, the most non-obvious state-management decision.
```

## Exit criteria

Universal (`code-with-spec` / `code-typescript`):
- [ ] `cd packages/ui && pnpm tsc --noEmit --strict`
- [ ] `cd packages/ui && pnpm vitest run --coverage --coverage.thresholds.100=true`
- [ ] `cd packages/ui && pnpm eslint . --max-warnings=0`
- [ ] `cd packages/ui && ! grep -rn ': any' src/`
- [ ] `cd packages/ui && pnpm build`
- [ ] `python3 -c "import json,os; p=json.load(open('.workflow/plans/chat-webapp/implementation-plan.json')); missing=[f['path'] for f in p['files'] if not os.path.exists(f['path'])]; assert not missing"`

Engagement-specific:
- [ ] `cd packages/python && python -m sox_protocol.cli ui --help`
- [ ] `cd packages/ui && npx lhci autorun --collect.numberOfRuns=1 --assert.assertions.categories\\:performance=80 --assert.assertions.categories\\:accessibility=95`

## Outputs

- `packages/ui/`
- `sox ui` CLI subcommand
- Bundled static assets in `packages/python/src/sox_protocol/ui_assets/`

## Next state

Promote `03-polish` → READY.
