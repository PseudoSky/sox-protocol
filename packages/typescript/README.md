# SOX Protocol — TypeScript implementation

**Status:** Not implemented; open to contributions.

This directory is a placeholder for a TypeScript implementation of SOX Protocol. The Python reference implementation in `packages/python/` is complete and production-ready; TypeScript is explicitly open to contributors.

---

## Conformance bar

Your TypeScript implementation is SOX v1.0-compliant if and only if it **passes all scenarios in `spec/conformance/scenarios/` when run against your MCP server.**

The conformance suite is language-agnostic and lives in `spec/conformance/`. It runs via Docker:

```bash
# From repo root, after your Dockerfile is in place:
spec/conformance/runner/run.sh
```

All seven scenarios must pass:

1. **send-and-recv-single-message** — one agent sends, another receives.
2. **multi-subscriber-on-channel** — multiple agents subscribe to one channel.
3. **late-reply-reconciliation** — agent A sends question, continues, integrates late answer.
4. **enforcer-reminder-on-drain-miss** — enforcer injects reminder after N tool calls without recv.
5. **enforcer-force-drain-on-stop** — enforcer blocks agent exit if inbox is non-empty.
6. **filesystem-backing-store** — backing store works correctly with filesystem persistence.
7. **subscriber-glob-patterns** — subscription with wildcards (e.g., `ticket:*`).

---

## Suggested architecture

Mirror `packages/python/` structure:

```text
packages/typescript/
├── src/
│   ├── core/
│   │   ├── enforcer/
│   │   │   ├── enforcer.ts         # decide(Event, State, Policy) → Decision
│   │   │   ├── event.ts            # Event type definitions
│   │   │   ├── decision.ts         # Decision type definitions
│   │   │   ├── state.ts            # Per-agent State
│   │   │   ├── policy.ts           # Operator-tunable Policy
│   │   │   └── __tests__/          # Unit tests for enforcer
│   │   ├── mcp_server/
│   │   │   ├── server.ts           # MCP server entrypoint
│   │   │   ├── tools.ts            # The four MCP tools
│   │   │   └── listener.ts         # Background task maintaining store connection
│   │   └── ports/
│   │       ├── backing-store.ts    # BackingStore interface
│   │       ├── discipline-renderer.ts
│   │       └── enforcer-binding.ts
│   ├── adapters/
│   │   ├── runtimes/
│   │   │   ├── claude-code.ts
│   │   │   ├── openai-agents-sdk.ts (v0.1)
│   │   │   └── langgraph.ts (v0.1)
│   │   └── backing-stores/
│   │       ├── sqlite.ts           # Default, using better-sqlite3
│   │       ├── filesystem.ts
│   │       ├── memory.ts           # Tests only
│   │       └── nats.ts (v0.1)
│   └── cli/
│       └── verify.ts               # Verification command
├── tests/
│   ├── conformance/
│   │   └── runner.ts               # Conformance test runner
│   ├── unit/
│   │   ├── enforcer.test.ts
│   │   └── ...
│   └── e2e/
│       └── ...
├── Dockerfile                      # Builds and runs the MCP server
├── package.json
├── tsconfig.json
├── vitest.config.ts
└── README.md (this file)
```

---

## Suggested tech stack

- **TypeScript:** 5.0+
- **MCP SDK:** `@modelcontextprotocol/sdk` (now the industry standard)
- **SQLite:** `better-sqlite3` for synchronous, default backing store
- **JSON validation:** `zod` for schema validation
- **Runtime:** `tsx` or `ts-node` for development; built binary for production
- **Testing:** `vitest` + `@testing-library/...` for unit and integration tests
- **Linting:** `eslint` + TypeScript plugin
- **Type checking:** `tsc --noEmit` (built-in to TypeScript)

### Installation

```bash
npm create vite@latest sox-typescript -- --template vanilla-ts
cd sox-typescript
npm install @modelcontextprotocol/sdk better-sqlite3 zod
npm install -D typescript vitest @types/node
```

---

## Key design patterns

The TypeScript implementation should follow the Python reference closely:

1. **Core agnostic of runtime.** The enforcer, MCP server, and backing-store abstractions live in `core/` and have zero runtime-specific dependencies.

2. **Runtime adapters are thin.** The Claude Code adapter (`adapters/runtimes/claude-code.ts`) reads `spec/discipline/discipline.md`, substitutes {{placeholders}} with concrete tool names, and writes a SKILL.md file. The enforcer binding registers MCP listen hooks in `.claude/settings.json`. Total: ~100 lines.

3. **BackingStore is an interface.** Implement once per store type (SQLite, filesystem, NATS). The MCP server is agnostic of the backing store implementation.

4. **Enforcer is a pure function.** `enforcer.decide(event, state, policy) → Decision`. Pure functions are easy to test, reusable across runtimes, and deterministic. All decision logic lives here.

5. **Conformance runner loads JSON from `spec/conformance/scenarios/`.** Do not redefine scenarios in TypeScript. Load them from the spec directory at test time.

---

## Getting started

### 1. Clone and setup

```bash
git clone https://github.com/[owner]/sox-protocol.git
cd sox-protocol
npm install  # from packages/typescript/ (once the package.json exists)
```

### 2. Implement the three ports

Read:
- `spec/ports/backing-store.md` — how to implement a message store.
- `spec/ports/runtime-discipline-renderer.md` — how to render discipline into a runtime's prompt surface.
- `spec/ports/runtime-enforcer-binding.md` — how to wire lifecycle events into the enforcer.

Start with the SQLite backing store (simplest, well-documented, no external services needed).

### 3. Implement the MCP server

The MCP server exposes four tools:

- `channels__send(channel, message)` → `{sent_at, message_id}`
- `channels__recv(subscription, timeout_ms)` → `[Message]`
- `channels__subscribe(channel_glob)` → `{subscribed_to}`
- `channels__list_channels()` → `{channels: [...]}`

Use `@modelcontextprotocol/sdk` to define tools with the input/output schemas from `spec/schemas/tools/`.

### 4. Build and test

```bash
npm run build
npm run test:unit    # Unit tests (enforcer logic, etc.)
npm run test:e2e     # End-to-end tests (two agents on a channel)
npm run test:conformance  # Conformance against spec/conformance/scenarios/
```

### 5. Create a Dockerfile

The conformance suite runs your MCP server inside Docker. Create a `Dockerfile` that:

1. Installs Node.js.
2. Copies your source.
3. Runs `npm install && npm run build`.
4. Exposes the MCP server on `stdio` (or HTTP if you prefer).

Example:

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY src src
RUN npm run build
CMD ["node", "dist/cli/mcp-server.js"]
```

### 6. Run conformance locally

```bash
spec/conformance/runner/run.sh
```

All seven scenarios must pass.

---

## Contribution process

1. **Open an issue** claiming this package: "I'm implementing the TypeScript port. Target: [date]."
2. **Implement the three ports and MCP server** (see above).
3. **Create a Dockerfile** so the conformance suite can test you.
4. **Run conformance locally** and verify all scenarios pass.
5. **Submit a PR** with:
   - Implemented code under `packages/typescript/src/`.
   - Unit and conformance tests passing.
   - README.md updated with status and tech stack choices.
   - `packages/typescript/Dockerfile` present and functional.

Merge gates:
- Conformance suite passes.
- Code linting passes.
- Type checking passes (`tsc --noEmit`).

Once merged, you can iterate on improvements (additional backing stores, additional runtime adapters, performance optimizations) in follow-up PRs.

---

## References

- **Spec overview:** [spec/README.md](../../spec/README.md)
- **Port contracts:** [spec/ports/](../../spec/ports/)
- **Wire definitions:** [spec/schemas/](../../spec/schemas/)
- **Conformance bar:** [spec/conformance/README.md](../../spec/conformance/README.md)
- **Python reference impl:** [packages/python/](../python/)
- **Design context:** [docs/DESIGN.md](../../docs/DESIGN.md)
- **Contributing guide:** [CONTRIBUTING.md](../../CONTRIBUTING.md)

---

## Questions?

- Read [docs/CONTRACTS.md](../../docs/CONTRACTS.md) for interface details.
- Check [spec/ports/](../../spec/ports/) for port-specific contracts.
- Open an issue on the repo.

---

## Roadmap (post-v0)

Once the TypeScript implementation passes conformance:

- **v0.1:** Additional backing stores (NATS, Redis), additional runtime adapters (OpenAI Agents SDK, LangGraph).
- **v0.2:** Performance optimizations, observability tooling.
- **v1.0+:** Breaking changes to spec (if any) will be coordinated with the Python ref impl.

Thank you for contributing to SOX!
