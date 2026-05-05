# sox-protocol

[![PyPI](https://img.shields.io/pypi/v/sox-protocol.svg)](https://pypi.org/project/sox-protocol/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/pypi/pyversions/sox-protocol.svg)](https://pypi.org/project/sox-protocol/)

**Runtime-agnostic peer messaging for LLM agents.** SOX Protocol gives multi-agent systems a documented, conformant pattern for *speculative-execute-while-awaiting-clarification*: when agent A needs input from agent B, A posts the question, continues working under a best-guess interpretation, and non-destructively integrates B's late-arriving answer into its in-progress reasoning — without blocking.

Existing frameworks offer turn-taking schedulers, handoffs, or actor primitives. None ship a packaged discipline for the speculate-then-reconcile pattern. SOX does.

This package is the reference Python implementation. It's [SOX v1.0-conformant](https://github.com/PseudoSky/sox-protocol/blob/main/spec/conformance/) on both stdio and HTTP transports (33/33 fixtures pass on each).

---

## Install

```bash
pip install sox-protocol sox-plugin-schema-strict
sox-protocol install                  # in your Claude Code project root
```

The installer writes:
- `.mcp.json` — registers the SOX MCP server with Claude Code
- `.claude/settings.json` — allows the server + adds cadence hooks
- `.claude/skills/inter-agent-channels/SKILL.md` — the discipline document
- `tools/sox-hooks/{post_tool_use,stop}.sh` — inbox-cadence reminder hooks

Verify:

```bash
claude mcp list           # → sox: ... ✓ Connected
sox-protocol verify       # full backing-store / MCP / hook / skill probe
```

> **Install the schema-strict plugin non-editable** (no `-e`). Its `sox-plugin.yaml` manifest isn't exposed via editable installs and the MCP server fails plugin discovery without it.

---

## CLI surface

```text
sox-protocol --help
  serve            Start the SOX server (stdio | http transport)
  chat             Launch the interactive Textual TUI
  install          Install the SOX adapter into a Claude Code project
  upgrade          PyPI check + pip-upgrade + file refresh + SQLite migration
  verify           Health-check the project's SOX install
  lint-discipline  Validate a discipline markdown file
  version          Print the installed version

  -V, --version    Print the installed version and exit
```

### Two practical recipes

**Boot a long-running agent companion.** Two terminals against the same project:

```bash
# Terminal 1 — interactive TUI; auto-discovers the project's .mcp.json
sox-protocol chat --agent-id $(whoami) --channel agent/companion

# Terminal 2 — Claude Code as the agent
SOX_AGENT_ID=companion claude
```

The TUI and Claude Code share the same SQLite store automatically.

**One-step skill activation.** When you want the skill itself to subscribe an agent on load (instead of needing a follow-up prompt), use `--auto-subscribe`:

```bash
sox-protocol install --auto-subscribe --channel team/eng
```

The installed `SKILL.md` then includes an Activation block that tells the LLM to subscribe to `agent/<your-id>` + `team/eng`, drain pending messages once, and emit a heartbeat — all on first skill load.

### Upgrade-in-place

```bash
sox-protocol upgrade
# Step 1/3: checking PyPI for newer versions…
#   sox-protocol             local=0.1.5  latest=0.1.6  → upgrade available
#   sox-plugin-schema-strict local=1.0.0  latest=1.0.0
#   Upgrading 1 package(s) via pip…
# (auto re-execs with the new code)
# Step 2/3: refreshing installed files…
# Step 3/3: SQLite schema migration…
```

Single command from "I just heard there's a new release" to "everything aligned": pip packages, project files, schema migrations, all converged in one run. Add `--check-only` for drift detection without changes.

---

## What's in the box

- **Four MCP tools** — `channels__send`, `channels__recv`, `channels__subscribe`, `channels__list_channels`. All non-blocking; the discipline + cadence enforcer keep the pull-based design from causing starvation.
- **Three backing stores** — SQLite (default, WAL mode), filesystem, in-memory (tests only). NATS / Redis pluggable via the `BackingStore` port.
- **Two transports** — stdio (Claude Code default) and HTTP (`sox-protocol serve --transport http`). Both pass the same conformance suite.
- **Plugin contract** — third-party plugins extend the pipeline (schema validation, audit logging, rate limiting) via the `sox_protocol.plugins` entry-point group. The schema-strict reference plugin proves the contract end-to-end.
- **Cadence enforcer** — pure-function decision engine that injects "drain your inbox" reminders after N tool calls without a recv, and blocks agent exit while the inbox is non-empty. Operator-tunable via env vars.
- **Live install e2e test** — `pytest -m live` spawns two real `claude` CLI subprocesses against a tmp venv, has them exchange messages via the protocol, asserts on the SQLite state. Verified end-to-end on both Anthropic API and Claude Max subscription auth paths.

---

## Project layout

The `sox-protocol` PyPI distribution is one component of the [pseudosky/sox-protocol](https://github.com/PseudoSky/sox-protocol) monorepo:

| Path | Contents |
|---|---|
| `packages/python/` | this package — reference Python implementation |
| `plugins/sox-plugin-schema-strict/` | the canonical reference plugin, published as `sox-plugin-schema-strict` on PyPI |
| `spec/` | language-neutral protocol artefacts (JSON Schema for tools/events, conformance fixtures, discipline markdown, port behaviour contracts) |
| `docs/` | design rationale, integration guide, ADRs |
| `tools/conformance_runner.py` | language-neutral conformance harness — runs `spec/conformance/*.yaml` against any implementation |

For full design rationale and the formal spec see the [GitHub repo](https://github.com/PseudoSky/sox-protocol) and especially [`docs/DESIGN.md`](https://github.com/PseudoSky/sox-protocol/blob/main/docs/DESIGN.md), [`docs/USAGE.md`](https://github.com/PseudoSky/sox-protocol/blob/main/docs/USAGE.md), and [`docs/INSTALL.md`](https://github.com/PseudoSky/sox-protocol/blob/main/docs/INSTALL.md).

---

## Status & conformance

| Component | Status | Conformance |
|---|---|---|
| **Spec (v1.0)** | Frozen; language-neutral | n/a |
| **Python (this package)** | Production-ready | 33/33 stdio · 33/33 HTTP |
| **TypeScript** | Placeholder; open to contributions | Must pass conformance suite to merge |
| **Rust** | Placeholder; open to contributions | Same |

```bash
python -m pytest -q
# 1300+ passed
python tools/conformance_runner.py --target packages/python --transport stdio --strict
# Results: 33 passed, 0 failed, 34 skipped / 67 total
```

---

## License

[Apache 2.0](https://github.com/PseudoSky/sox-protocol/blob/main/LICENSE), including the express patent grant in §3. Contributors and adopters are protected from patent assertions on the protocol primitives they help build or use. See the repo's [`docs/ip/`](https://github.com/PseudoSky/sox-protocol/tree/main/docs/ip) for the IP strategy and OIN application tracker.
