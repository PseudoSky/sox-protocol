# RESUME — pick up where the prior session left off

**You are reading this because:** a previous Claude Code session is being handed off to you. The work is ongoing; the tree is in a coherent committed state. Read this end-to-end before doing anything else.

**Date written:** 2026-05-01
**Tree state at handoff:** clean working tree on `main`, 932 tests pass / 0 skip / 0 fail, 100% line coverage, mypy --strict clean.

---

## What this project is

The SOX Protocol — an inter-agent message-passing protocol with ports + adapters architecture. Five language-agnostic ports (`BackingStore`, `Transport`, `Identity`, `Middleware`, plus a few smaller ones) under `packages/python/src/sox_protocol/core/ports/`. Multiple concrete adapters (memory/sqlite/filesystem stores; stdio/http transports). The spec at `spec/` is the product; the Python package is one reference implementation.

Engagement state machines live at `.workflow/plans/<slug>/STATE.md`. Every change goes through a phased state machine (`01-plan` → `02-build` → `04-review`-ish). The orchestrator contract is documented at `.workflow/templates/ORCHESTRATOR-CONTRACT.md`.

---

## What just shipped — read these in order

1. **`.workflow/plans/SALVAGE-AUDIT-2026-04-30.md`** — full context for the spec-realignment salvage. Five spec drifts identified, all reconciled. Read this before touching anything in `core/identity/`, `core/middleware/`, `adapters/transports/http/`, or `core/ports/backing_store.py`.

2. **Recent commit log** (run `git log --oneline -10`) — the salvage shipped in 6 commits between `00d3d21` and `0fde9b3`:
   - `00d3d21` chore(salvage): bookkeeping + audit + state-machine reconciliation
   - `64e4535` feat(salvage): atomic spec realignment (identity + middleware + http + BackingStore 4-tuple + list_agents migration)
   - `47daa78` feat(conformance-suite): 32 new fixtures
   - `6fcf173` fix(conformance-suite): drain self-send threading fixture
   - `d82e775` fix(installer): SOX_AGENT_ID_SOURCE plumbing per spec §6
   - `0fde9b3` feat(backing-store): SQLite schema migration framework + v1.0→v1.1 migration

3. **`TODO.md`** — `## Implementation — post-v1 → ### adapter framework / runtime composition root` is a new section flagging six post-v1 items about runtime extensibility (entry-point discovery, store registry, transport registry, etc.). Do NOT start on these as v1 work; they are explicitly post-v1.

---

## Punch list — what's next, in priority order

### Priority 1: close out the queued reviews (parallelizable)

These three phases are READY and gated only on dispatch. The salvage shipped the code; the reviews never ran. Run them in parallel — they don't conflict.

| Engagement | Phase | Suggested agent |
|---|---|---|
| `identity-primitive` | `04-review` | code-reviewer |
| `hooks-middleware` | `04-review` | code-reviewer |
| `http-transport` | `03-conformance` | test-automator |

Each STATE.md has the phase prompt. For `04-review`, key things to verify:
- **identity:** spec §6 credential-on-connection-seam (signed_request NOT in tool-call inputs); §7 origin_server in envelope (always null in v1); list_agents in `_IDENTITY_ENFORCED_OPERATIONS`; `middleware_timings` in `_meta`.
- **hooks-middleware:** all 15 v1 ops in `Operation` literal; full `StoreDispatchMiddleware` op-table; default-chain order preserved (auth → store_dispatch terminal); no pragmas in `core/middleware/`.
- **http-transport:** conformance harness against HTTP target — `python3 tools/conformance_runner.py --target <http-binding> --strict` should match the stdio result (32 pass / 0 fail / 27 skip).

### Priority 2: v1 demo + adoption surface (parallelizable)

| Engagement | Phase | Suggested agent | Notes |
|---|---|---|---|
| `chat-tui-demo` | `02-build` | python-pro | **Highest leverage.** The 30-second TUI demo that sells the pitch. Independent. Drives launch-narrative. |
| `reference-agent` | `02-build` | python-pro | Canonical copy-paste agent for adopters. Independent. |

Both have implementation-plan.json regenerated against current spec (commit `a79c9e0`). Safe to dispatch in parallel.

### Priority 3: v1 launch wrapping

| Engagement | Phase | Suggested agent | Notes |
|---|---|---|---|
| `defensive-publication` | `02-preprint` | content-marketer | License + arXiv + Software Heritage. Independent of code. |
| `launch-narrative` | `01-narrative` | content-marketer | Final gate before public. **Soft-depends on `chat-tui-demo`** for the demo recording embedded in README. Run defensive-publication first if chat-tui-demo isn't done. |

`launch-narrative` reads from `TODO.md` (which now includes the adapter-framework post-v1 section) and from `bucket-classification/result.md` to produce `docs/roadmap.md`. Both inputs are in place.

### Post-v1 — DO NOT START

Filed for later, explicitly out of v1 scope:

- `ts-sdk:02-build` and `chat-webapp:02-build` — `milestone: post-v1` in their STATE.md frontmatter.
- The 6 adapter-framework items in `TODO.md` (`### adapter framework / runtime composition root`). Real architecture gap (ports exist, runtime registry doesn't) but explicitly post-v1.
- `conformance-suite:03` 27 skipped fixtures — they self-document as `pending: true` because they're gated on post-v1 features (typed channels, idempotency, namespace isolation, etc.). They will un-skip automatically as features land.

---

## Hard-won lessons from the prior session — read carefully

### Agent dispatch is unreliable — agents truncate at 50–400k tokens

Every Task-dispatched agent in the prior session truncated mid-flight, often after doing useful work but before completing exit criteria or updating STATE.md. Pattern: agent message ends with "Now run X" with no further output.

**Implications for you:**
- After dispatching an agent, **always verify exit criteria with bash before trusting STATE.md**: run pytest, run mypy, grep for the marker tokens listed in the phase prompt. The agent may say it finished and not have.
- For mechanical work (signature harmonization, simple test fixtures, pragma additions), **do it inline** rather than dispatching. Token cost is 10× lower and you don't lose context to truncation.
- For substantive work (a full phase deliverable per the phase prompt), dispatching is still right — but write the prompt to be tight, with exit criteria the agent verifies before claiming completion.

### Scope-creep risk: parallel agents over the same files

If you dispatch two agents in parallel and they both modify `core/identity/middleware.py`, you get a working-tree race. The `hooks-middleware:05` agent in the prior session touched files outside its scope (an unrelated coverage agent in another shell was running concurrently). Pattern to avoid:

- Don't run a global "100% coverage" agent in parallel with focused phase agents. Either focused phases first, then coverage close, or vice versa.
- Phase prompts should explicitly list "DO NOT modify <other-engagement-territory>".

### Migration discipline — the salvage's hidden bug

The salvage bumped `BackingStore.send()` to a 4-tuple including `BackpressureInfo` and added `seq` to the SQLite schema. `schema.sql` uses `CREATE TABLE IF NOT EXISTS` which is a **no-op on existing tables** — meaning every existing deployment's `messages.db` would silently break on next message. Found by checking the actual production `.sox/messages.db` after the salvage.

**Fixed in commit `0fde9b3`** with a proper migration runner. Going forward:
- Any change to `schema.sql` MUST also add a versioned `.sql` migration in `adapters/backing_stores/sqlite/migrations/`, append to `_MIGRATION_CHAIN` in `migration_runner.py`, and bump `SqliteStore.schema_version`.
- Spec at `spec/ports/backing-store.md §2.6` codifies the migration contract for all future adapters (Postgres, etc.).

### The SOX channels inbox is real and matters

The PostToolUse hook reminder "you have not checked the channels inbox" looks like noise but isn't. Stale messages in `.sox/messages.db` are real inter-agent traffic. The prior session ignored these reminders for hours, then discovered 7 unread messages from prior orchestrator runs (1 stale orchestrator signal + a 6-message product↔engineering conversation about FUTURE.md). They were aged out and didn't need response, but they were real.

Periodically check the inbox via:
```python
# from the project root
python3 -c "
import asyncio
from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore
async def main():
    s = SqliteStore('/Users/nix/dev/ai/sox-protocol/.sox/messages.db')
    await s.initialize()
    chans = await s.list_channels()
    print('channels:', chans)
asyncio.run(main())
"
```

### Don't waste tokens on coverage agents

The prior session burned ~130k tokens dispatching a coverage agent for a 23-line gap. The same work inline took ~10k. Coverage gap closure is mechanical: get the missing-lines report, write targeted unit tests, pragma the unreachable defensive paths. Do not delegate.

---

## Hard invariants to preserve

Before any commit:

```bash
cd /Users/nix/dev/ai/sox-protocol
python3 -m pytest packages/python/tests/ --tb=no -q | tail -2
# expect: 932+ passed, 0 failed
cd packages/python && python3 -m mypy --strict src/sox_protocol/ | tail -1
# expect: Success: no issues found in 65 source files
python3 -m pytest packages/python/tests/ --cov=packages/python/src/sox_protocol --cov-report=term -q 2>&1 | grep TOTAL
# expect: 100%
python3 tools/conformance_runner.py --target packages/python --strict | tail -1
# expect: 32 passed, 0 failed, 27 skipped / 59 total  (exit 0)
```

If any of these regress, stop and investigate before continuing.

---

## Quick start for the next session

1. Read this file (you're doing it).
2. Read `.workflow/plans/SALVAGE-AUDIT-2026-04-30.md` for context.
3. `git log --oneline -10` to see recent commits.
4. `git status --short` to confirm clean tree.
5. Run the four-invariant block above to confirm green tree.
6. Pick from the punch list (Priority 1 recommended start: dispatch the three reviews in parallel).
7. After each engagement closes, update its `STATE.md` and `git commit` per the orchestrator contract trailer rules.

Ask the user for direction if anything in this file is unclear or out of date. Trust the user's "continue" / "next" pattern: they want autonomous execution from the punch list.
