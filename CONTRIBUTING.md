# Contributing to SOX Protocol

Thank you for your interest in contributing! This guide covers three types of contributions: spec changes, language ports (TypeScript / Rust), and implementation improvements.

---

## 1. Spec changes (changes to `spec/`)

The spec is the contract between the protocol and all language implementations. Changes must be backward-compatible or involve coordination across implementations.

### Process

1. **Open an issue first** describing the change and rationale (e.g., "Add optional `priority` field to messages" or "Clarify ordering semantics for concurrent senders").
2. **Submit a PR against `spec/`** with:
   - Schema changes (JSON Schema files under `spec/schemas/`).
   - Updated prose contracts in `spec/ports/` if behaviour changes.
   - Updated `spec/discipline/discipline.md` if guidance changes.
   - Test scenarios in `spec/conformance/scenarios/` for new functionality.
3. **Merge gates:**
   - `spec-lint.yml` CI passes (schema validation, broken link detection, prose checks).
   - At least one language implementation is updated to match the spec change.
   - If a spec change breaks backward compatibility, file it under CHANGELOG.md with a migration guide.

### Bumping the protocol version

Protocol version lives in `spec/VERSION`. Bump policy:

- **Patch (1.0 → 1.0.1):** Clarifications only; no wire format change. Existing implementations remain conformant.
- **Minor (1.0 → 1.1):** Backward-compatible additions (new optional fields, new tools). Existing implementations remain conformant.
- **Major (1.0 → 2.0):** Breaking change to wire format or behaviour. Implementations must be updated.

Version bumps require a new entry in `CHANGELOG.md` with migration guidance.

---

## 2. Language ports (TypeScript / Rust)

The SOX protocol is designed to be language-portable. The TypeScript and Rust implementations are explicitly open to contributions.

### Conformance bar

Your implementation is SOX v1.0-compliant if and only if it **passes all scenarios in `spec/conformance/scenarios/` when run against your MCP server.**

The conformance suite is language-agnostic and lives in `spec/conformance/`. It runs via Docker, so your implementation's language is irrelevant to CI; we only care that your MCP server conforms to the wire contract.

### Suggested architecture

Mirror `packages/python/` layout:

```text
packages/<lang>/
├── src/
│   ├── core/
│   │   ├── enforcer/          # Pure-function cadence enforcer
│   │   │   ├── enforcer.rs    # decide(Event, State, Policy) → Decision
│   │   │   ├── event.rs       # Event dataclass
│   │   │   ├── decision.rs    # Decision dataclass
│   │   │   ├── state.rs       # Per-agent State
│   │   │   └── policy.rs      # Operator-tunable Policy
│   │   ├── mcp_server/        # MCP server
│   │   │   ├── server.rs      # Entrypoint; lifecycle setup
│   │   │   ├── tools.rs       # The four tools (send, recv, subscribe, list_channels)
│   │   │   └── listener.rs    # Background asyncio-like task maintaining store connection
│   │   └── ports/             # Abstract port definitions
│   │       ├── backing_store.rs  # BackingStore trait
│   │       ├── discipline_renderer.rs
│   │       └── enforcer_binding.rs
│   ├── adapters/
│   │   ├── runtimes/
│   │   │   ├── claude_code.rs  # Claude Code adapter
│   │   │   ├── openai_agents_sdk.rs (v0.1)
│   │   │   └── langgraph.rs (v0.1)
│   │   └── backing_stores/
│   │       ├── sqlite.rs       # Default backing store
│   │       ├── filesystem.rs   # Filesystem inbox
│   │       ├── memory.rs       # In-memory (tests only)
│   │       └── nats.rs (v0.1)
│   └── cli/
│       └── verify.rs           # CLI verification command
├── tests/
│   ├── conformance/
│   │   └── runner.rs           # Loads `spec/conformance/scenarios/` and runs against your MCP server
│   ├── unit/
│   │   ├── enforcer.rs         # Unit tests for enforcer decisions
│   │   └── ...
│   └── e2e/
│       └── ...                 # End-to-end tests (optional at v0)
├── Dockerfile                   # Builds the MCP server; used by conformance suite
├── Cargo.toml (Rust) or package.json (TS)
└── README.md                   # Status, suggested stack, contribution process, conformance-badge link
```

### Suggested tech stack

**TypeScript:**
- `@modelcontextprotocol/sdk` — MCP SDK
- `better-sqlite3` — Default backing store (synchronous SQLite)
- `zod` — JSON schema validation
- `tsx` or `ts-node` — TypeScript runtime
- `vitest` — Testing

**Rust:**
- `mcp-sdk` or similar Rust MCP SDK (if available; otherwise wrap gRPC)
- `rusqlite` — SQLite bindings
- `tokio` — Async runtime
- `serde` / `serde_json` — JSON (de)serialization
- `sqlx` or equivalent for type-safe queries
- `cargo test` — Testing

### Before you start

1. **Open an issue claiming the package directory.** This prevents duplication of effort. Example:
   ```
   Title: TypeScript port of SOX Protocol
   Body: I want to implement packages/typescript/. I'll aim for v1.0 conformance and plan to have a working MCP server by [date].
   ```

2. **Read the spec:**
   - `spec/README.md` — overview of the spec structure and conformance bar.
   - `spec/ports/*.md` — formal port contracts (BackingStore, DisciplineRenderer, EnforcerBinding).
   - `spec/schemas/` — wire definitions (JSON Schema).
   - `spec/discipline/discipline.md` — the full discipline (your runtime adapter will render this).

3. **Run the Python conformance suite locally** (optional but helpful):
   ```bash
   make conformance
   ```
   This shows you what the conformance tests expect your MCP server to do.

### Conformance checklist

Before submitting your PR, verify:

- [ ] Your MCP server builds and starts without errors.
- [ ] `spec/conformance/runner/run.sh` passes all scenarios against your server (you can run this locally if your Dockerfile is correct).
- [ ] All four tools (`channels__send`, `channels__recv`, `channels__subscribe`, `channels__list_channels`) are implemented per `spec/schemas/tools/`.
- [ ] The enforcer (`spec/schemas/event.schema.json` → `spec/schemas/decision.schema.json`) is implemented correctly.
- [ ] At least one backing-store adapter (SQLite is easiest to start with) is implemented per `spec/ports/backing-store.md`.
- [ ] The enforcer state (`spec/schemas/state.schema.json`) is correctly maintained across events.

### Submission checklist

Before opening your PR:

- [ ] Forked the repo and created a feature branch: `git checkout -b ports/typescript`
- [ ] Created `packages/typescript/README.md` with status, suggested stack, and conformance badge link.
- [ ] Created `packages/typescript/Dockerfile` that builds your MCP server.
- [ ] Created `packages/typescript/tests/conformance/runner.rs` (or equivalent) that loads and runs `spec/conformance/scenarios/`.
- [ ] Verified `make conformance` passes.
- [ ] Linted code with your language's standard tools.
- [ ] Updated the top-level [README.md](README.md) to reflect your port status (if it's production-ready).

### Merge gates

CI will verify:

1. **Conformance suite passes.** `spec/conformance/runner/run.sh` runs against your MCP server in Docker.
2. **Code style.** Language-standard linting (clippy for Rust, eslint for TypeScript, etc.).
3. **Documentation.** README.md present and linked; contribution guidance clear.

Your PR will not merge until all three pass.

---

## 3. Implementation improvements (Python reference impl)

Changes to `packages/python/` — new adapters, new backing stores, performance improvements, bug fixes.

### Process

1. **Fork the repo** and create a feature branch: `git checkout -b feat/openai-sdk-adapter`
2. **Implement your change:**
   - Write code.
   - Add unit tests in `packages/python/tests/unit/`.
   - Add integration tests if appropriate.
3. **Run the test suite:**
   ```bash
   make test
   ```
4. **Run type checking:**
   ```bash
   make type-check
   ```
5. **Run linting:**
   ```bash
   make lint
   ```
6. **Run conformance** (important if you touched the core):
   ```bash
   make conformance
   ```
7. **Submit a PR** with a clear description of what changed and why.

### Merge gates

CI will verify:

- All tests pass (`pytest`).
- Type checking passes (`mypy`).
- Linting passes (`black`, `isort`, `flake8`, etc.).
- Conformance suite still passes.
- Code coverage does not decrease significantly.

---

## Code of conduct

Be respectful, collaborative, and assume good intent. Disagreements about design are healthy; personal attacks are not.

---

## Questions?

- Open an issue with your question.
- Check [docs/FAQ.md](docs/FAQ.md) (if present) for common issues.
- Read [docs/RESEARCH.md](docs/RESEARCH.md) for context on design decisions.

---

## Recognition

Contributors are recognised in:

- [CHANGELOG.md](CHANGELOG.md) for significant changes.
- The repo's [contributors list](https://github.com/[owner]/sox-protocol/graphs/contributors).

Thank you for contributing to SOX!
