---
phase_id: 02-build
title: Build TUI + demo script + recording
agent: python-pro
profile: code-with-spec
estimated_effort: 3-5 days
prereqs: [01-plan]
unblocks: []
parallelizable_with: []
writes: ["packages/python/src/sox_protocol/tui/**", "packages/python/tests/tui/**", "packages/python/src/sox_protocol/cli/**", "examples/two-agents-talking/**", "docs/media/**", "README.md"]
reads:  [".workflow/plans/chat-tui-demo/implementation-plan.json", "spec/**", "packages/python/src/sox_protocol/**"]
context_size: large
---

# 02 — Build

## Objective

Build the TUI, demo script, and capture the recording per `implementation-plan.json`.

## Inputs

- `.workflow/plans/chat-tui-demo/implementation-plan.json`
- `spec/protocol.md`, `spec/primitives/`
- `packages/python/src/sox_protocol/` (client API)

## Prompt (verbatim)

```text
Build the SOX Protocol `sox chat` TUI per the structured plan.

READ:
1. .workflow/plans/chat-tui-demo/implementation-plan.json (your contract)
2. spec/protocol.md, spec/primitives/
3. packages/python/src/sox_protocol/ (existing client)

DELIVER:
- TUI app per plan.files[] under packages/python/src/sox_protocol/tui/
- `sox chat` CLI subcommand wired up
- examples/two-agents-talking/demo.py — runnable, reproducible, scripted
- docs/media/demo.cast (asciinema) AND docs/media/demo.gif (vhs render or equivalent)
- README.md updated to embed the .gif near the top (minor README change; major rewrite is launch-narrative engagement)
- Tests per plan.test_plan[] under packages/python/tests/tui/

HARD CONSTRAINTS:
- 100% coverage on TUI logic (state, event handlers); rendering glue may be excluded with documentation in conftest
- mypy --strict on src/sox_protocol/tui/
- lint-imports clean
- Demo script does not require manual input; running it twice produces the same recording
- Recording is ≤ 60 seconds and ≤ 5 MB on disk

ACCEPTANCE:
- pytest tests/tui/ --cov=src/sox_protocol/tui --cov-fail-under=100 -q (with documented omits if any)
- mypy --strict src/sox_protocol/tui/
- lint-imports
- python -m sox_protocol.cli chat --help (the new subcommand is wired)
- python examples/two-agents-talking/demo.py runs to completion in ≤ 60s

REPORT: ≤ 250 words. File list, recording duration, recording size, the most non-obvious choreography choice.
```

## Exit criteria

Universal (`code-with-spec` / `code-python`):
- [ ] `cd packages/python && pytest tests/tui/ --cov=src/sox_protocol/tui --cov-fail-under=100 -q`
- [ ] `cd packages/python && mypy --strict src/sox_protocol/tui/`
- [ ] `cd packages/python && lint-imports`
- [ ] `cd packages/python && ruff check src/sox_protocol/tui/`
- [ ] `python3 -c "import json,os; p=json.load(open('.workflow/plans/chat-tui-demo/implementation-plan.json')); missing=[f['path'] for f in p['files'] if not os.path.exists(f['path'])]; assert not missing"`

Engagement-specific:
- [ ] `test -f docs/media/demo.gif || test -f docs/media/demo.cast`
- [ ] `test -f examples/two-agents-talking/demo.py`
- [ ] `grep -q 'docs/media/demo' README.md` (recording embedded in README)
- [ ] `cd packages/python && python -m sox_protocol.cli chat --help` (subcommand wired)

## Outputs

- `packages/python/src/sox_protocol/tui/`
- `examples/two-agents-talking/`
- `docs/media/demo.gif` and/or `.cast`
- README update

## Next state

Leaf. Engagement complete on DONE.
