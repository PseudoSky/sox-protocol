# SOX Protocol — Rust implementation

**Status:** Not implemented; open to contributions.

This directory is a placeholder for a Rust implementation of SOX Protocol. The Python reference implementation in `packages/python/` is complete and production-ready; Rust is explicitly open to contributors.

---

## Conformance bar

Your Rust implementation is SOX v1.0-compliant if and only if it **passes all scenarios in `spec/conformance/scenarios/` when run against your MCP server.**

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
packages/rust/
├── src/
│   ├── core/
│   │   ├── enforcer/
│   │   │   ├── mod.rs              # Enforcer module
│   │   │   ├── enforcer.rs         # decide(Event, State, Policy) → Decision
│   │   │   ├── event.rs            # Event struct from schema
│   │   │   ├── decision.rs         # Decision struct from schema
│   │   │   ├── state.rs            # Per-agent State
│   │   │   ├── policy.rs           # Operator-tunable Policy
│   │   │   └── tests.rs            # Unit tests
│   │   ├── mcp_server/
│   │   │   ├── mod.rs
│   │   │   ├── server.rs           # MCP server entrypoint + lifecycle
│   │   │   ├── tools.rs            # The four MCP tools
│   │   │   └── listener.rs         # Background task maintaining store connection
│   │   └── ports/
│   │       ├── mod.rs
│   │       ├── backing_store.rs    # BackingStore trait
│   │       ├── discipline_renderer.rs
│   │       └── enforcer_binding.rs
│   ├── adapters/
│   │   ├── runtimes/
│   │   │   ├── mod.rs
│   │   │   ├── claude_code.rs
│   │   │   ├── openai_agents_sdk.rs (v0.1)
│   │   │   └── langgraph.rs (v0.1)
│   │   └── backing_stores/
│   │       ├── mod.rs
│   │       ├── sqlite.rs           # Default, using rusqlite
│   │       ├── filesystem.rs
│   │       ├── memory.rs           # Tests only
│   │       └── nats.rs (v0.1)
│   ├── cli/
│   │   ├── mod.rs
│   │   └── verify.rs               # Verification command
│   └── lib.rs                       # Crate root
├── tests/
│   ├── conformance/
│   │   └── conformance_runner.rs    # Conformance test runner
│   ├── unit/                        # (alt: use src/*/tests.rs)
│   └── e2e/
├── Dockerfile                       # Builds and runs the MCP server
├── Cargo.toml
├── Cargo.lock
└── README.md (this file)
```

---

## Suggested tech stack

- **Rust:** 1.70+ (MSRV)
- **Async runtime:** `tokio` (widely used, well-documented)
- **MCP SDK:** Rust MCP SDK if available; otherwise wrap with `prost` + gRPC or HTTP client
- **SQLite:** `rusqlite` (synchronous) or `sqlx` (async)
- **JSON validation & serialization:** `serde` + `serde_json`
- **Schema validation:** `jsonschema` or hand-written validation
- **Testing:** `tokio::test` for async tests, `criterion` for benchmarks (optional)
- **Linting:** `clippy` (built-in to cargo)
- **Type checking:** `cargo check` (built-in)

### Cargo.toml skeleton

```toml
[package]
name = "sox-protocol"
version = "0.0.1"
edition = "2021"
rust-version = "1.70"

[dependencies]
tokio = { version = "1", features = ["full"] }
rusqlite = { version = "0.29", features = ["bundled"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
uuid = { version = "1", features = ["v4", "serde"] }
chrono = { version = "0.4", features = ["serde"] }
anyhow = "1"
tracing = "0.1"
tracing-subscriber = "0.3"

[dev-dependencies]
tokio-test = "0.4"
tempfile = "3"

[[bin]]
name = "sox-mcp-server"
path = "src/bin/mcp_server.rs"
```

---

## Key design patterns

The Rust implementation should follow the Python reference closely:

1. **Core agnostic of runtime.** The enforcer, MCP server, and backing-store abstractions live in `core/` and have zero runtime-specific dependencies.

2. **Runtime adapters are thin.** ~100 lines each. The Claude Code adapter reads `spec/discipline/discipline.md`, substitutes {{placeholders}} with concrete tool names, and writes a SKILL.md file.

3. **BackingStore is a trait.** Implement once per store type (SQLite, filesystem, NATS). The MCP server is agnostic of the backing store implementation.

4. **Enforcer is a pure function.** `enforcer::decide(event, state, policy) → Decision`. Pure functions are testable, reusable, and deterministic.

5. **Conformance runner loads JSON from `spec/conformance/scenarios/`.** Do not redefine scenarios. Load them at test time.

6. **Error handling:** Use `anyhow::Result<T>` for application errors, `thiserror` for custom error types if needed.

---

## Getting started

### 1. Clone and setup

```bash
git clone https://github.com/[owner]/sox-protocol.git
cd sox-protocol/packages/rust
cargo init --name sox-protocol
```

### 2. Implement the three ports

Read:
- `spec/ports/backing-store.md` — how to implement a message store.
- `spec/ports/runtime-discipline-renderer.md` — how to render discipline into a runtime's prompt surface.
- `spec/ports/runtime-enforcer-binding.md` — how to wire lifecycle events into the enforcer.

Start with the SQLite backing store. Use `rusqlite`:

```rust
pub trait BackingStore: Send + Sync {
    fn send(&self, message: Message) -> Result<SentMetadata>;
    fn recv(&self, subscriber_id: &str, timeout_ms: u32) -> Result<Vec<Message>>;
    fn subscribe(&mut self, subscriber_id: &str, channel_glob: &str) -> Result<()>;
    fn list_channels(&self) -> Result<Vec<String>>;
}

pub struct SqliteBackingStore {
    db: Connection,
}
```

### 3. Implement the MCP server

The MCP server exposes four tools. If no Rust MCP SDK exists, wrap the MCP protocol:

```rust
pub struct McpServer {
    backing_store: Arc<Box<dyn BackingStore>>,
    listener: Arc<Mutex<McpListener>>,
}

impl McpServer {
    pub async fn channels_send(&self, channel: String, message: String) -> Result<SentMetadata> {
        // Call backing_store.send()
    }

    pub async fn channels_recv(&self, subscription: String, timeout_ms: u32) -> Result<Vec<Message>> {
        // Call backing_store.recv()
    }

    // ... channels_subscribe, channels_list_channels
}
```

### 4. Build and test

```bash
cargo build
cargo test --lib       # Unit tests (enforcer logic)
cargo test --test '*'  # Integration tests
```

For conformance, you'll need a conformance runner:

```rust
#[tokio::test]
async fn test_conformance() {
    let scenarios = load_scenarios("../../spec/conformance/scenarios/");
    for scenario in scenarios {
        let result = run_scenario(&scenario).await;
        assert!(result.passed, "Scenario {} failed", scenario.name);
    }
}
```

### 5. Create a Dockerfile

The conformance suite runs your MCP server inside Docker. Create a `Dockerfile` that:

1. Installs Rust.
2. Copies your source.
3. Runs `cargo build --release`.
4. Runs the binary.

Example:

```dockerfile
FROM rust:1.75-alpine
WORKDIR /app
COPY Cargo.* ./
COPY src src
RUN cargo build --release
CMD ["./target/release/sox-mcp-server"]
```

### 6. Run conformance locally

```bash
spec/conformance/runner/run.sh
```

All seven scenarios must pass.

---

## Advantages of Rust

- **Single-binary deployment:** Cargo produces a statically-linked binary; easy to deploy as a daemon.
- **Performance:** Native compiled code; lower latency than Python or TypeScript.
- **Memory safety:** No null pointers, no data races (enforced at compile time).
- **Long-running stability:** Ideal for daemon-shaped MCP servers that run 24/7.

---

## Contribution process

1. **Open an issue** claiming this package: "I'm implementing the Rust port. Target: [date]."
2. **Implement the three ports and MCP server** (see above).
3. **Create a Dockerfile** so the conformance suite can test you.
4. **Run conformance locally** and verify all scenarios pass.
5. **Submit a PR** with:
   - Implemented code under `packages/rust/src/`.
   - Unit and conformance tests passing.
   - README.md updated with status and tech stack choices.
   - `packages/rust/Dockerfile` present and functional.

Merge gates:
- Conformance suite passes.
- `cargo clippy` passes with no warnings.
- `cargo fmt` shows no changes needed.
- Type checking passes (`cargo check`).

Once merged, you can iterate on improvements (additional backing stores, additional runtime adapters, performance optimizations, observability) in follow-up PRs.

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

Once the Rust implementation passes conformance:

- **v0.1:** Additional backing stores (NATS, Redis), additional runtime adapters (OpenAI Agents SDK, LangGraph).
- **v0.2:** Performance optimizations, observability tooling, metrics collection.
- **v1.0+:** Breaking changes to spec (if any) will be coordinated with the Python ref impl.

Thank you for contributing to SOX!
