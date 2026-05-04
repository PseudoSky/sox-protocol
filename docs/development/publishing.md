# Publishing to PyPI

Operational checklist for cutting a SOX Protocol release. Run end-to-end the first time; subsequent releases follow the same flow with the names already reserved and trusted publishing already configured.

> Audience: maintainers with PyPI account access. CI does the actual publish via OIDC trusted publishing — no API tokens are stored anywhere.

---

## Packages

This repo publishes two PyPI distributions:

| Package | Source | Purpose |
|---|---|---|
| `sox-protocol` | `packages/python/` | Core protocol library + CLI (`sox-protocol`, `sox-mcp-server`) |
| `sox-plugin-schema-strict` | `plugins/sox-plugin-schema-strict/` | Reference plugin: schema-strict body validator. Required at install time — installs alongside core via the recommended `pip install sox-protocol sox-plugin-schema-strict` line. |

Both ship from the same workflow (`.github/workflows/python-publish.yml`) on a single tag.

---

## One-time setup

Done once per repo / once per maintainer. Skip if already in place.

### 1. Reserve names on PyPI and TestPyPI

Whoever publishes first owns the name. Do this **before** anyone else can squat:

```bash
# Manual: log into pypi.org and test.pypi.org and create the empty
# project namespaces by uploading a placeholder version, OR (cleaner)
# configure trusted publishing first which auto-creates the project
# on the first successful upload. Either works.
```

### 2. Configure trusted publishers

For each of the four targets:

- https://pypi.org/manage/account/publishing/ → "Add a new pending publisher"
  - Project name: `sox-protocol` (then again for `sox-plugin-schema-strict`)
  - Owner: `<github-org-or-user>`
  - Repository: `sox-protocol`
  - Workflow: `python-publish.yml`
  - Environment: `pypi`

- https://test.pypi.org/manage/account/publishing/ → same shape, environment `testpypi`.

PyPI mints a short-lived OIDC token at publish time; no tokens stored in GitHub.

### 3. Configure GitHub Environments

GitHub repo → Settings → Environments → New environment:

| Environment | Required reviewers | Wait timer | Purpose |
|---|---|---|---|
| `testpypi` | none | none | Auto-publishes on tag push or `target=testpypi` dispatch |
| `pypi` | **at least one maintainer** | none | Promotes only after manual approval — gates real PyPI publish |

The environment names must match the `environment.name` values in the workflow.

---

## Per-release checklist

### Pre-flight

1. **Decide the release scope.** Is this a patch (bug fixes only), minor (new features, backward-compatible), or major (breaking changes)? Pre-1.0, minor bumps are the right size for "first release with new visible features."

2. **Bump versions.** Core lives in `packages/python/pyproject.toml`; plugin in `plugins/sox-plugin-schema-strict/pyproject.toml`. The two version on independent cadences — only bump what changed.

3. **Update CHANGELOG.md.** Move entries from `## Unreleased` into a new `## [X.Y.Z] — YYYY-MM-DD` section. Include a "Migration from previous version" subsection if there are breaking changes (e.g. CLI rename, schema migration).

4. **Run all four invariants locally.**
   ```bash
   cd packages/python && python3 -m mypy --strict src/sox_protocol/ | tail -1
   cd ..
   timeout 600 python3 -m pytest packages/python/tests/ --tb=line -q -x \
     --ignore=packages/python/tests/transports/http/test_coverage2.py | tail -3
   python3 tools/conformance_runner.py --target packages/python --transport stdio --strict | tail -1
   python3 tools/conformance_runner.py --target packages/python --transport http --strict | tail -1
   ```
   All four must be green. mypy clean, pytest 0 failed, both conformance runs at the documented totals.

5. **Smoke-build wheels and verify package data.**
   ```bash
   pip install build twine
   rm -rf packages/python/dist plugins/sox-plugin-schema-strict/dist
   python -m build packages/python/
   python -m build plugins/sox-plugin-schema-strict/

   # Both must include their critical data files:
   unzip -l packages/python/dist/*.whl | grep -E "spec/discipline/discipline.md|spec/VERSION"
   unzip -l plugins/sox-plugin-schema-strict/dist/*.whl | grep "sox-plugin.yaml"

   twine check packages/python/dist/*
   twine check plugins/sox-plugin-schema-strict/dist/*
   ```
   The CI workflow runs these same checks — failing them locally first saves a round-trip.

6. **End-to-end smoke install** in a fresh tmp venv from the built wheels:
   ```bash
   T=$(mktemp -d); python3 -m venv $T/v
   $T/v/bin/pip install packages/python/dist/*.whl plugins/sox-plugin-schema-strict/dist/*.whl
   ls $T/v/bin/sox-protocol $T/v/bin/sox-mcp-server      # both bins present
   $T/v/bin/python -c "import sox_protocol, sox_plugin_schema_strict; print('ok')"

   # Installer smoke
   mkdir $T/proj
   $T/v/bin/python -m sox_protocol.adapters.runtimes.claude_code install --project-dir $T/proj
   ls $T/proj/.mcp.json $T/proj/.claude/settings.json $T/proj/.claude/skills/inter-agent-channels/SKILL.md
   ```

   If any step fails, fix before tagging.

### Release

7. **Commit version + CHANGELOG bumps** on `main`:
   ```bash
   git add packages/python/pyproject.toml plugins/sox-plugin-schema-strict/pyproject.toml CHANGELOG.md
   git commit -m "release: sox-protocol X.Y.Z + sox-plugin-schema-strict A.B.C"
   git push
   ```

8. **Tag and push.** The tag drives the workflow.
   ```bash
   git tag python-vX.Y.Z
   git push origin python-vX.Y.Z
   ```

   The workflow:
   - Builds both wheels + sdists.
   - Verifies critical data files are bundled.
   - Runs `twine check`.
   - Verifies the tag's version matches `packages/python/pyproject.toml` (fails the build if they drift).
   - Publishes to TestPyPI.
   - **Pauses at the `pypi` environment for manual approval.**

9. **Smoke-test from TestPyPI** in a fresh venv:
   ```bash
   T=$(mktemp -d); python3 -m venv $T/v
   $T/v/bin/pip install \
     --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ \
     "sox-protocol==X.Y.Z" "sox-plugin-schema-strict==A.B.C"
   $T/v/bin/sox-protocol --help
   ```

   The `--extra-index-url` is needed because TestPyPI doesn't mirror runtime dependencies (aiosqlite, fastmcp, etc.) — pip pulls those from real PyPI.

10. **Approve the `pypi` environment** in the GitHub Actions run UI. The workflow promotes both packages to real PyPI.

11. **Verify the public install:**
    ```bash
    T=$(mktemp -d); python3 -m venv $T/v
    $T/v/bin/pip install "sox-protocol==X.Y.Z" "sox-plugin-schema-strict==A.B.C"
    ```

12. **Create a GitHub release** at `python-vX.Y.Z`, paste the CHANGELOG section, mark it as the latest release.

---

## Manual / dry-run modes

The workflow accepts `workflow_dispatch` with a `target` input — useful when you want to:

- **Dry-run TestPyPI without tagging:** `target=testpypi`, builds + publishes to TestPyPI from whatever HEAD is on the chosen branch. No tag created. Catches version drift, packaging bugs, etc., before committing to a tag.
- **Re-promote after fixing TestPyPI metadata:** `target=pypi`, skips TestPyPI and goes straight to PyPI promotion. Use only if TestPyPI succeeded earlier on this version.

Trigger from the GitHub Actions UI (Actions → Publish to PyPI → Run workflow → pick target).

---

## Failure recovery

| Failure | Fix |
|---|---|
| Build fails the "wheel bundles spec/discipline/" verify step | The hatch `force-include` config in `packages/python/pyproject.toml` is wrong or got reverted. Fix and rebuild. |
| Build fails the "plugin wheel bundles sox-plugin.yaml" verify step | The plugin's `[tool.setuptools.package-data]` is missing or wrong. Fix and rebuild. |
| `twine check` fails with `RST` or `Markdown` parse error | Usually a malformed `readme = ...` reference, or a code fence without a language. Fix the `README.md` in the package root. |
| TestPyPI publish succeeds but real PyPI publish fails on "version already exists" | The version is already on PyPI from a prior release attempt. Bump the patch version and re-tag. |
| Trusted publishing rejects the OIDC token | Check the GitHub Environment name matches the publisher config on PyPI exactly (`testpypi` vs `pypi`, case-sensitive). |
| `pip install sox-protocol` works but `sox-protocol install` crashes with "Cannot locate spec/discipline/discipline.md" | The wheel did not bundle the spec data. The `[tool.hatch.build.targets.wheel.force-include]` block is the source of truth — if it's missing or the source path is wrong, the wheel ships without `sox_protocol/spec/`. Fix and re-release. |

---

## Yanking a release

If a published release is broken:

1. Yank on PyPI: https://pypi.org/manage/project/sox-protocol/release/X.Y.Z/ → "Yank release". Yanked releases stay installable for users who already pinned them but disappear from default `pip install` resolution.
2. Bump to the next patch version, fix, re-release.
3. Note the yank in CHANGELOG.md (`## [X.Y.Z+1] — yanks X.Y.Z; …`).

Do not delete a published release — that breaks anyone who pinned it. Yank, then ship a fix.

---

## Cross-reference

- Workflow: [`.github/workflows/python-publish.yml`](../../.github/workflows/python-publish.yml)
- Core build config: [`packages/python/pyproject.toml`](../../packages/python/pyproject.toml) — `[tool.hatch.build.targets.wheel.force-include]`
- Plugin build config: [`plugins/sox-plugin-schema-strict/pyproject.toml`](../../plugins/sox-plugin-schema-strict/pyproject.toml) — `[tool.setuptools.package-data]`
- Install smoke (`pip install` from local wheel): [`docs/INSTALL.md`](../INSTALL.md)
- Live e2e gate (separate workflow): [`docs/development/live-tests.md`](./live-tests.md)
