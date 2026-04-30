---
phase_id: 01-housekeeping
title: License switch + SWHID + signed commits + OIN tracker
agent: general-purpose
profile: release
estimated_effort: 4-6 hours
prereqs: []
unblocks: [02-preprint]
parallelizable_with: []
writes: ["LICENSE", "NOTICE", "README.md", "CONTRIBUTING.md", "docs/ip/**", "packages/**/*.py", "packages/**/*.ts", "spec/**/*.md", ".githooks/**", ".pre-commit-config.yaml"]
reads:  ["LICENSE", "README.md", "CONTRIBUTING.md"]
context_size: small
---

# 01 — Housekeeping

## Objective

Mechanical IP-posture work: license to Apache 2.0, source headers, SWHID submission, contribution policy, OIN tracker.

## Inputs

- `~/.claude/plugins/workflow/memory/research/patent-landscape/agent-communication-protocols.md` — strategy memo
- Current `LICENSE` file
- All source files (Python + JS once it exists)
- `CONTRIBUTING.md`

## Prompt (verbatim)

```text
Execute the IP-posture housekeeping for SOX Protocol.

READ:
- ~/.claude/plugins/workflow/memory/research/patent-landscape/agent-communication-protocols.md (strategy)
- Current LICENSE
- README.md
- CONTRIBUTING.md

DELIVER:

1. Replace LICENSE with Apache 2.0 (full text from https://www.apache.org/licenses/LICENSE-2.0.txt). NOTICE file with copyright + attribution.

2. Add SPDX headers to every source file:
   - Python: `# SPDX-License-Identifier: Apache-2.0`
   - TypeScript (when it exists): `// SPDX-License-Identifier: Apache-2.0`
   - Markdown spec files: comment HTML at top with the SPDX line

3. Update README.md (minor change only — bigger rewrite is launch-narrative):
   - License badge (Apache 2.0)
   - One-line note explaining the patent-grant rationale and linking docs/ip/

4. Update CONTRIBUTING.md:
   - DCO sign-off requirement (`Signed-off-by:` trailer on commits)
   - Signed-commit policy (Sigstore cosign or GPG)
   - Note that the Apache 2.0 patent grant applies to all contributions

5. Submit the repo to Software Heritage via https://archive.softwareheritage.org/save/ (instruct the user; this requires browser interaction). Once submitted, record the SWHID in docs/ip/swhid.txt with the date.

   Template:
   ```
   SOX Protocol Software Heritage record
   Submitted: <YYYY-MM-DD>
   SWHID: swh:1:dir:<hash>;origin=<repo-url>;visit=<visit-id>;anchor=<commit-hash>
   ```
   If the submission requires manual user action, write docs/ip/swhid.txt with placeholder TODO and surface to the user as a manual step.

6. Create docs/ip/oin-application.md with:
   - Application URL
   - Date drafted
   - Status: drafted | submitted | approved
   - Whoever's name is on it
   This is a tracker; the actual application submission is a manual user action.

7. Configure git for signed commits in the repo:
   - Update CONTRIBUTING.md with the exact `git config` commands users need
   - Optionally add a pre-commit hook that warns on unsigned commits

HARD CONSTRAINTS:
- Do NOT change any code logic. License header additions are the only source-file edits.
- Apache 2.0 verbatim — do not edit the license text.
- Every existing .py file gets the SPDX header. Use a script if necessary.

ACCEPTANCE:
- LICENSE matches the official Apache 2.0 text byte-for-byte (modulo any year/holder line you fill in)
- find packages/python/src -name '*.py' | xargs grep -L 'SPDX-License-Identifier' returns nothing
- test -f docs/ip/swhid.txt && test -f docs/ip/oin-application.md
- README has license badge; CONTRIBUTING has DCO + signed-commit instructions

REPORT: ≤ 200 words. Files modified count, SWHID submission status, OIN application status.
```

## Exit criteria

Universal (`release`):
- [ ] `git status --porcelain` was empty before this phase started (orchestrator pre-flight)
- [ ] `test -f LICENSE && head -5 LICENSE | grep -q 'Apache License'`
- [ ] `test -f NOTICE`
- [ ] `find packages/python/src -name '*.py' | xargs grep -L 'SPDX-License-Identifier' | wc -l | grep -q '^[[:space:]]*0$'`
- [ ] `test -f docs/ip/swhid.txt`
- [ ] `test -f docs/ip/oin-application.md`
- [ ] `grep -q 'Signed-off-by' CONTRIBUTING.md && grep -q -iE 'signed[- ]commit|GPG|Sigstore' CONTRIBUTING.md`
- [ ] `grep -q 'Apache' README.md`

## Outputs

- `LICENSE`, `NOTICE`
- SPDX headers across every source file
- `docs/ip/swhid.txt`, `docs/ip/oin-application.md`
- `CONTRIBUTING.md` updates
- `README.md` minor update

## Next state

Promote `02-preprint` → READY.
