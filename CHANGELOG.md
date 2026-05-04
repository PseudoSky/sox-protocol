# SOX Protocol Changelog

All notable changes to SOX Protocol are documented here. This file follows the [Keep a Changelog](https://keepachangelog.com/) format.

---

## [0.0.1] — 2026-04-29 — v0 launch (SOX v1.0-compliant Python reference implementation)

### Added

**Spec (v1.0 — frozen)**
- Protocol specification in `spec/`:
  - JSON Schemas for wire definitions (Event, Decision, Policy, State, Message, MCP tools).
  - Markdown discipline document with {{placeholder}} tokens for tool names.
  - Port behaviour contracts in prose (BackingStore, DisciplineRenderer, EnforcerBinding).
  - Language-neutral conformance test harness with 7 scenarios.

**Python reference implementation (v0.0.1)**
- Complete implementation of all three ports:
  - `BackingStore` port with three adapters: SQLite (default, WAL mode), filesystem inbox, in-memory (tests only).
  - `DisciplineRenderer` — renders `spec/discipline/discipline.md` into Claude Code SKILL.md with {{placeholder}} substitution.
  - `EnforcerBinding` — wires Claude Code lifecycle hooks into the cadence enforcer.
- MCP server (asyncio-based) with four tools:
  - `channels__send` — non-blocking message send.
  - `channels__recv` — pull-based message drain with optional timeout.
  - `channels__subscribe` — subscribe to a channel or glob pattern.
  - `channels__list_channels` — list all channels.
- Cadence enforcer (pure function):
  - Decides when to inject reminders (after N tool calls without a recv).
  - Decides when to block agent exit (if inbox non-empty and `SOX_FORCE_DRAIN_ON_STOP` is true).
  - Operator-tunable policy (thresholds, flags) via environment variables.
- Installation CLI (`python -m sox_protocol.adapters.runtimes.claude_code install`):
  - Reads spec/discipline/discipline.md from package.
  - Writes skill to `.claude/skills/`.
  - Initialises SQLite backing store.
  - Updates `.claude/settings.json` with MCP server registration and hooks.
- Verification CLI (`python -m sox_protocol.cli verify`):
  - Checks backing store reachable.
  - Checks MCP server registered.
  - Checks all four tools surfaced.
  - Checks skill present and discipline anchors correct.

**Documentation**
- Comprehensive design document (`docs/DESIGN.md`):
  - Problem statement and gap analysis (§1).
  - Related-work survey covering 40+ frameworks and protocols (§2).
  - Full requirements table (§3).
  - Five-layer architecture (§4).
  - Design decisions with trade-off rationale (§5).
  - Explicit non-goals for v0 (§6).
  - Open problems requiring community input (§7).
  - Relationship to existing standards (§8).
- Usage guide (`docs/USAGE.md`):
  - Quickstart for Claude Code integration.
  - Configuration reference (7 environment variables).
  - Channel naming conventions.
  - Full MCP tool reference with examples.
  - Anti-patterns and troubleshooting.
- Formal contracts (`docs/CONTRACTS.md`):
  - Discipline section anchors for stable adapter references.
  - Enforcer Event/Decision JSON schemas.
  - Policy and State schemas.
  - MCP tool input/output schemas.
  - BackingStore, DisciplineRenderer, EnforcerBinding port specifications.
  - Adapter conformance checklist.
- Architecture overview (`docs/IMPLEMENTATION-PLAN.md`):
  - Milestone breakdown (M0–M8 completed).
  - Repo layout and tech-stack choices.
  - Testing strategy.
  - Port implementation examples.
- Future roadmap (`docs/FUTURE.md`):
  - Additional language ports (TypeScript, Rust — open to contributions).
  - Additional runtime adapters (OpenAI Agents SDK, LangGraph v0.1).
  - Additional backing stores (NATS, Redis v0.1).
  - Stronger delivery semantics (v0.1+).
  - Pattern library for reconciliation strategies (v0.2+).
- Annotated bibliography (`docs/RESEARCH.md`):
  - 40+ sources covering actor models, multi-agent frameworks, protocols, substrates.
  - How each source informed SOX design.
- Term definitions (`docs/GLOSSARY.md`):
  - Agent, channel, mailbox, discipline, enforcer, adapter, backing store, and more.
- Repository README (`README.md`):
  - One-paragraph hook (the gap and what SOX adds).
  - Quickstart (pip install + CLI verification).
  - Repo navigation with directory structure.
  - Status and conformance table.
  - Documentation index with reading order.

**Placeholder language ports**
- `packages/typescript/README.md`:
  - Conformance bar.
  - Suggested architecture mirroring `packages/python/`.
  - Suggested tech stack (@modelcontextprotocol/sdk, better-sqlite3, zod, vitest).
  - Getting-started guide and contribution checklist.
- `packages/rust/README.md`:
  - Conformance bar (same 7 scenarios).
  - Suggested architecture.
  - Suggested tech stack (tokio, rusqlite, serde, criterion).
  - Getting-started guide and contribution checklist.

**Examples**
- Two end-to-end walkthroughs in `examples/`:
  - `two-agent-clarification/` — Agent A posts a question to a group channel; Agent B answers; A integrates the reply.
  - `group-broadcast/` — Agent A broadcasts status to all agents on a ticket channel.
  - Each includes agent prompts, backing-store output, and a runnable `run.sh` script.

**Contributing guide**
- `CONTRIBUTING.md`:
  - Process for proposing spec changes (issue + PR + spec-lint + at-least-one-impl-updated).
  - Contribution process for new language ports (conformance bar, architecture, checklist).
  - Standard PR process for implementation improvements (Python package).
  - Merge gates (conformance, linting, type checking, coverage).

**Build automation**
- `Makefile`:
  - `make test` — run Python unit tests.
  - `make type-check` — mypy type checking.
  - `make lint` — black, isort, flake8.
  - `make conformance` — run spec/conformance/scenarios/ against Python MCP server.
  - `make install` — install sox-protocol from packages/python/ locally.

### What this enables

1. **Use SOX in Claude Code projects immediately:**
   ```bash
   pip install sox-protocol
   python -m sox_protocol.adapters.runtimes.claude_code install
   ```

2. **Understand the protocol design with a reference implementation** that all language ports must conform to.

3. **Contribute TypeScript or Rust ports** with fixed conformance criteria (pass `spec/conformance/scenarios/` against your MCP server).

4. **Build additional runtime adapters** (OpenAI Agents SDK, LangGraph, AutoGen) using the documented DisciplineRenderer and EnforcerBinding contracts.

5. **Extend with custom backing stores** (NATS, Redis, Kafka) by implementing the BackingStore port.

### Technical details

**Spec version:** 1.0 (frozen; no breaking changes expected for v0.x)

**Python version:** 0.0.1

**Conformance:** Python implementation passes all 7 scenarios:
- send-and-recv-single-message
- multi-subscriber-on-channel
- late-reply-reconciliation
- enforcer-reminder-on-drain-miss
- enforcer-force-drain-on-stop
- filesystem-backing-store
- subscriber-glob-patterns

**Known limitations (deliberate v0 non-goals):**
- No push-based message interrupts (pull-only with optional cadence enforcer reminders).
- No authoritative ordering or causal consistency (best-effort per channel).
- No authentication, authorization, or encryption.
- No observability tooling (WIP post-v0).
- Only Claude Code runtime adapter in v0 (OpenAI Agents SDK and LangGraph adapters v0.1).
- Only SQLite, filesystem, and memory backing stores in v0 (NATS/Redis v0.1).

### Migration notes

This is the v0 release. No prior version exists. Future 0.x releases will be backward-compatible. Major version bumps (1.0 → 2.0) will be announced in this changelog with migration guidance.

---

## Unreleased

(No unreleased changes yet.)

---

## [0.1.0] — 2026-05-04 — first PyPI release; v1.0-conformant on both transports

This is the first release intended for PyPI. The reference Python implementation now passes 33/33 v1.0 conformance fixtures on **both** stdio and HTTP transports, with end-to-end live verification against the real `claude` CLI.

### Added

**Plugin architecture (post-v0 sub-engagements P1–P6)**
- New plugin contract for SOX middleware. Reference plugin `sox-plugin-schema-strict` ships separately on PyPI; SOX core discovers it via the `sox_protocol.plugins` entry-point group.
- Pipeline middleware infrastructure: schema-strict body validation, identity verification, store dispatch, observability tracing.
- Plugin-discovery loader with manifest validation, allowlist (`SOX_ALLOWED_PLUGINS` / `--allow-plugins`), and discovery-disable switch (`SOX_NO_DISCOVERY` / `--no-discovery`).
- `BackingStore.send` gained a keyword-only `reply_to: str | None = None` parameter for threading; `MemoryStore`, `SqliteStore`, and `FilesystemStore` all persist + return it.
- SQLite schema migration v1.1 → v1.2 adds `reply_to` column. Migration is idempotent and additive — existing v1.0 / v1.1 databases upgrade in place with zero downtime.
- HTTP transport: pipeline integration with auth middleware, server-side error envelope normalization, async nonce-prune lock.
- Reference plugin `sox-plugin-schema-strict` (1.0.0) — proves the plugin contract end-to-end, validates send/recv/group/replay/heartbeat bodies against `spec/operations/*.input.schema.json`.

**Live end-to-end test infrastructure**
- New `tests/integration/test_live_install_e2e.py` (3 tests: 1 happy-path + 2 negative): builds a fresh tmp venv, pip-installs SOX, runs the installer against a tmp Claude Code project, spawns 2 real `claude` CLI subprocesses (alice + bob), exercises group-create/invite/join/send/recv/ack, asserts on the SQLite state.
- New `live` pytest marker (gated on `ANTHROPIC_API_KEY` or OAuth keychain). Default `pytest` runs deselect it; opt in with `-m live`.
- New CI workflow `python-live-e2e.yml` — runs on push-to-main + workflow_dispatch + weekly cron, gated on `secrets.ANTHROPIC_API_KEY`.
- Verified locally on Max subscription: 3/3 tests pass in 138s, ~$0.10–0.20 per agent.

**`sox chat` interactive TUI**
- New Textual-based TUI shipped as a CLI subcommand. Three-pane layout: channels (left) · messages (center) · agents (right). Spawns its own MCP server on stdio by default; `--no-spawn` to attach to an existing one.

**Documentation**
- New `docs/INSTALL.md` — practical install + first-run walkthrough based on a real e2e debug pass. Includes the seven gotchas surfaced during live testing.
- New `docs/development/sox-chat.md` — TUI usage guide, all flags, spawn/attach connection model, two practical patterns.
- New `docs/development/live-tests.md` — live e2e test ops manual.
- New `docs/development/publishing.md` — PyPI publish operational checklist.

### Changed

**BREAKING — CLI bin renamed**
- The `sox` console script is **renamed to `sox-protocol`** to avoid conflict with the [SoX audio toolkit](http://sox.sourceforge.net/), which ships under the same name on most Unix systems.
- Migration: `sox chat …` → `sox-protocol chat …`. Module form `python -m sox_protocol.cli` is unaffected.
- The `sox-mcp-server` bin name is unchanged.
- The MCP server name `sox` inside `.mcp.json` (server-registry identifier, not a CLI bin) is unchanged.

**Conformance harness realignment**
- 9 HTTP conformance fixtures that previously passed via stdio simulator masking now pass via the real wire on both transports. Fixture field-name changes:
  - `replay`: `since_seq` → `since` (matches `spec/operations/replay.input.schema.json`).
  - `unsubscribe`: `patterns` → `channels` (matches `spec/operations/unsubscribe.input.schema.json`).
  - `group_invite` output: `{group_id, invited_agent}` → `{invited, agent_id}` (matches `spec/operations/group_invite.output.schema.json`, canonical post-2fb72ac).
- 7 simulator branches removed from `tools/conformance_runner.py` (the harness no longer hand-implements `reply_to`, `since`, `unsubscribe-discard`, `heartbeat-presence-emit`, `list_channels-version-block`, `replay`, or `group_invite-output-remap`).
- Stdio + HTTP both reach **33 passed / 0 failed / 34 skipped** at v1.0 conformance.

### Fixed

- **PyPI wheel was missing `spec/discipline/`.** The hatch `[tool.hatch.build.targets.wheel.sources]` mapping with a `../../spec` source path silently no-opped because the source was outside the project root. Switched to `[tool.hatch.build.targets.wheel.force-include]` which is the documented mechanism for files outside the package. The wheel now bundles `spec/discipline/discipline.md`, the worked-example markdown files, and `spec/VERSION` — without these, `python -m sox_protocol.adapters.runtimes.claude_code install` would fail at install time on a published wheel.
- **Identity-middleware nonce race.** `IdentityVerifier` now wraps nonce prune+check+insert in an `asyncio.Lock` (P1 phase 05).
- **Pipeline observability gap.** Every dispatch now emits a structured `pipeline_trace` with `correlation_id` (P1 phase 04).
- **Conformance harness identity substitution.** Server-side rejection fixture proves `AuthMiddleware` is exercised by the real wire, not synthesized client-side (P1 phases 06 + 07).

### Migration from 0.0.1

- **Update CLI invocations:** `sox chat` → `sox-protocol chat`, `sox serve` → `sox-protocol serve`. Module form unchanged.
- **Reinstall:** `pip install --upgrade sox-protocol` followed by `python -m sox_protocol.adapters.runtimes.claude_code install` to refresh `.mcp.json` and `.claude/settings.json` in your project.
- **SQLite databases auto-upgrade.** The v1.1 → v1.2 migration runs on first connect. The migration is additive (`ALTER TABLE messages ADD COLUMN reply_to TEXT DEFAULT NULL`) and rolls forward with no data loss. There is no rollback path; back up `.sox/messages.db` before upgrading if rollback matters to your deployment.
- **Plugin install:** The `sox-plugin-schema-strict` reference plugin is now part of the recommended install. **Install it non-editable** (no `-e`) — editable install does not expose the plugin's `sox-plugin.yaml` manifest, so the MCP server fails plugin discovery at boot. See `docs/INSTALL.md` for details.
