# Universal constraints — per-profile

Every phase declares a `profile:` in its frontmatter. The profile determines the **mandatory exit-criteria checks** the phase must include. Phase authors MAY add additional checks; they MUST NOT remove the profile's universal checks (or must explicitly document a justified exemption in the phase's `Notes` section).

This file is referenced by `templates/PHASE.md`. Profiles are the canonical contract — update here, not in individual phase files.

---

## Universal scope rule (applies to every profile)

**Workers MUST NOT modify any files outside the repository root** (`<repo-root>` = `git rev-parse --show-toplevel`). This is absolute and applies to every profile, every phase, every agent dispatched by the orchestrator.

What this means:

- **Edit / Write / NotebookEdit tool calls**: target paths must resolve under `<repo-root>`. No edits to `~/`, `/tmp/`, `/opt/`, `/etc/`, system directories, other repositories, parent directories of the repo, or any user-home or system path.
- **Bash tool calls**: must not perform file writes (`>`, `>>`, `tee`, `cp`, `mv`, `rm`, `mkdir`, `touch`, `sed -i`, etc.) on paths outside `<repo-root>`. Read-only operations (status checks, version probes) on system paths are permitted.
- **Subprocess spawning**: any `python`, `node`, `make`, etc. invocations must not have side effects outside `<repo-root>` for the duration of the phase. Long-running daemons / installers / system-level changes are forbidden.
- **No `git config --global`** or any other operation that mutates global git/shell/system state.

What this does NOT prohibit:

- **Source code that, when later executed, writes to runtime paths.** A phase may produce a Python module that opens `~/.sox/logs/identity-failures.jsonl` for append at runtime — that's a *runtime* effect of the deployed code, not the agent's *tool-call* effect during the phase. The agent writes the source file inside `<repo-root>`; the source file's behaviour at runtime is its own concern.
- **Read-only access to system paths.** `git --version`, `which python`, `cat /etc/os-release` etc. are fine. The constraint is on *writes*, not reads.

### Verification

The orchestrator captures the working-tree-clean state at phase entry and at phase exit. Any file modified during the phase that is not under `<repo-root>` is detectable post-hoc by:

```bash
# At phase entry
find ~/.sox ~/.config /tmp /opt -newer /tmp/phase_start_marker -type f 2>/dev/null > /tmp/touched_outside_repo
```

Heuristic, not airtight. Strong enforcement requires sandboxing the orchestrator (bwrap, firejail, devcontainer, or running under a dedicated user account). The protocol assumes the agent obeys; sandboxing is the operator's defence in depth.

### Why this is a universal rule

- **Reproducibility.** A phase that writes to `~/.cache/` cannot be re-run cleanly on a fresh machine. Repo-local writes are the only ones the engagement can replay.
- **Provenance.** Git tracks repo-internal changes; system writes are invisible to the audit trail. The commit-trailer story breaks if work happens outside git's view.
- **Isolation.** Multiple orchestrator sessions running in different worktrees of the same repo must not collide via shared system state. Repo-local discipline guarantees they don't.
- **Security.** A subagent that can write `~/.ssh/authorized_keys` or `~/.bashrc` has effectively rooted the developer machine. Repo-scope is the simplest principle that prevents this.

---

## Profile: `meta`

For synthesis, classification, doc-restructuring work that produces no executable artifacts.

Required exit criteria:
- All declared output files exist
- Any JSON outputs validate as JSON
- No new untracked files outside the engagement directory unless explicitly listed in Outputs

No coverage / type / architecture rules apply.

---

## Profile: `spec`

For phases that produce or modify the protocol spec (`spec/`).

Required exit criteria:
- All JSON Schemas validate as JSON Schema 2020-12: `npx ajv compile -s 'spec/**/*.json' --spec=draft2020`
- `scripts/lint-discipline.sh` passes (if discipline is touched)
- No `packages/` references appear in `spec/`: `! grep -rn 'packages/' spec/`
- All markdown files in `spec/` pass markdown-lint. The repo standardizes on **`markdownlint-cli2`** (note the `-cli2` suffix; the bare `markdownlint` is a different package): `npx markdownlint-cli2 'spec/**/*.md'`. If `markdownlint-cli2` is not installed, fall back to `npx --yes markdownlint-cli2@latest 'spec/**/*.md'`.
- All cross-references to other spec files resolve: `npx markdown-link-check 'spec/**/*.md'`

---

## Profile: `code-python`

For phases that write or modify Python code in `packages/python/`.

Required exit criteria:
- **100% line coverage on every Python module touched (created or modified) in this phase.** The check covers both net-new and edited files. `cd packages/python && pytest <touched-test-paths> --cov=<touched-src-paths> --cov-fail-under=100`
- `mypy --strict` passes: `cd packages/python && mypy --strict src/`
- `lint-imports` passes (architecture rule): `cd packages/python && lint-imports`
- `ruff check` passes: `cd packages/python && ruff check src/ tests/`
- No secrets committed: `! grep -rE '(SECRET|PASSWORD|API_KEY)\s*=\s*["\047][^"\047]+' packages/python/src/`
- All tests pass (existing + new): `cd packages/python && pytest -q`

100% means 100% — including edited files. If the phase legitimately cannot reach 100% on a specific file (trivial `__init__.py`, abstract base, generated code), the phase author MUST:
- List the excluded files with explicit rationale in the phase's Notes section
- Configure pytest's `omit` directive for them
- The exemption is auditable in git history

---

## Profile: `code-typescript`

For phases that write or modify TypeScript code in `packages/typescript/` or `packages/ui/`.

Required exit criteria:
- `tsc --noEmit --strict` passes
- **100% line coverage on every TS/TSX module touched (created or modified) in this phase.** Vitest or Jest: `--coverage --coverage.thresholds.100=true`
- `eslint` passes with no warnings: `pnpm eslint . --max-warnings=0`
- No `any` in any touched code (created or modified): `! grep -rn ': any' <touched-paths>`
- Bundle-size delta within budget (specify in phase Notes; default ≤ 10% increase)
- No secrets: same grep as code-python

100% means 100% on touched modules. Same exemption rules as code-python — list excluded files with rationale in Notes; configure coverage `exclude:` directive.

---

## Profile: `code-with-spec`

For phases that implement against an existing spec file. Inherits ALL `code-python` or `code-typescript` checks AND requires:

- An upstream `sox-cto-system:planner` phase has produced `<plan_dir>/implementation-plan.json` AND `<plan_dir>/reservations/<phase_id>.json`
- The implementing phase's prompt cites `implementation-plan.json` in its Inputs and instructs the agent to follow it
- The implementing phase's exit criteria include verifying every file the planner predicted was created: `python3 -c "import json; p=json.load(open('<plan_dir>/implementation-plan.json')); files=[f['path'] for f in p['files']]; import os; missing=[f for f in files if not os.path.exists(f)]; assert not missing, f'planner predicted files missing: {missing}'"`
- **Implementer stayed within reservations** (planner-fidelity check): `git diff --name-only HEAD~1 HEAD | python3 -c "import sys,json; mods={l for l in sys.stdin.read().strip().split() if l}; res=set(json.load(open('<plan_dir>/reservations/<phase_id>.json'))['files']); extra=mods - res - {'<plan_dir>/STATE.md'}; assert not extra, f'wrote outside reservations: {extra}'"`
- The implementing phase's commit includes the `Spec-version:` trailer recording the git rev of `spec/` at dispatch time

**Planner-gate rule:** every `code-with-spec` profile phase MUST be preceded by a `planning` profile phase using `sox-cto-system:planner` against the relevant spec sections. Phase order:

```
spec → sox-cto-system:planner (planning profile) → implementer (code-with-spec profile) → reviewer (review profile, optional)
```

---

## Profile: `planning`

For phases that produce structured implementation plans from a spec. Always uses `sox-cto-system:planner`.

Required exit criteria:
- Plan output exists at `<plan_dir>/implementation-plan.json` (or `.md` if a downstream consumer requires it; JSON is preferred — planner is JSON-native)
- Plan validates as JSON: `python3 -c "import json; json.load(open('<plan_dir>/implementation-plan.json'))"`
- Plan contains required fields: `python3 -c "import json; p=json.load(open('<plan_dir>/implementation-plan.json')); assert all(k in p for k in ['summary','files','test_plan','risks','dependencies'])"`
- Plan cites at least one specific spec section per planned file: `python3 -c "import json; p=json.load(open('<plan_dir>/implementation-plan.json')); assert all('spec_ref' in f for f in p['files'])"`
- **Reservations block present in agent return.** Orchestrator extracts and persists at `<plan_dir>/reservations/<downstream_phase_id>.json`.
- **Reservations match plan.files[].path byte-identically:** `python3 -c "import json; p=json.load(open('<plan_dir>/implementation-plan.json')); r=json.load(open('<plan_dir>/reservations/<downstream_phase_id>.json')); assert set(f['path'] for f in p['files']) == set(r['files']), 'reservations diverge from plan.files'"`

The planner phase prompt MUST explicitly:
- Cite the spec files the plan should reference
- Demand JSON output by default with the schema: `{summary, files: [{path, spec_ref, purpose, public_api}], test_plan: [{spec_section, test_cases}], risks, dependencies}`
- Note that markdown output is acceptable when explicitly requested by a downstream consumer (rare)
- **End the agent return with a fenced RESERVATIONS block** (see PHASE.md "Reservations protocol"). The block is mandatory; an empty block is acceptable for genuinely-dynamic plans (e.g. fixture-generation).

---

## Profile: `test-harness`

For phases that build conformance suites or integration test harnesses.

Required exit criteria:
- All fixtures parse: `python3 -c "import yaml; [yaml.safe_load(open(f)) for f in glob.glob('spec/conformance/**/*.yaml', recursive=True)]"`
- Harness runs against the reference Python implementation and all fixtures pass: `python3 tools/conformance_runner.py --target packages/python --strict`
- CI workflow file exists and is referenced from `.github/workflows/`
- Harness has its own unit tests with 100% coverage on the runner code

---

## Profile: `docs`

For phases that produce user-facing prose (README, why-X, blog posts, launch narrative).

Required exit criteria:
- `markdownlint-cli2` passes on touched files: `npx markdownlint-cli2 '<paths>'`
- `markdown-link-check` passes (no broken links)
- Spell-check passes: `cspell '<touched-files>'` (or equivalent)
- For phases producing the README specifically: an embedded image / asciicast / video reference exists (the demo asset)
- For phases citing the spec: every cited section anchor resolves

---

## Profile: `review`

For optional review-gate phases using `code-reviewer` or `qa-expert`.

Required exit criteria:
- Review report exists at `<plan_dir>/reviews/<phase-being-reviewed>.md`
- Report contains a Pass/Fail verdict and at least one specific file:line citation per concern (or explicit "no concerns")

Review phases are non-blocking by default — a Fail verdict surfaces to the user but does not auto-fail the engagement. The user decides whether to spawn a remediation phase.

---

## Profile: `release`

For phases that cut releases (tagging, package publication, defensive-publication submission).

Required exit criteria:
- All preceding non-release phases in the engagement DONE
- Working tree clean before the release commit
- Git tag created with semver: `git tag <vX.Y.Z>`
- Tag pushed (or explicitly held for review)
- For PyPI / npm publication phases: package builds locally and `twine check` / `npm pack --dry-run` passes
- For defensive-publication: SWHID recorded; arXiv submission ID recorded; OIN application submitted (or explicitly deferred with rationale in Notes)

---

## How to use

1. Phase author picks the profile matching the work shape.
2. Adds `profile: <name>` to phase frontmatter.
3. Includes the profile's required exit criteria in the phase's Exit Criteria section (verbatim or adapted to the engagement's specific paths).
4. Phase author MAY add engagement-specific checks beyond the universal set.
5. Phase author MAY NOT remove a universal check without explicit Notes-section justification.
