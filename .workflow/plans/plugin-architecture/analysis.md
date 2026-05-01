# SOX Protocol Plugin Architecture — Full Analysis

**Date:** 2026-05-01
**Author:** synthesis from codebase inventory + peer-framework research
**Status:** revised (v2) — see §7 for changes after workflow-optimizer review and 3 workflow-researcher findings

> **Revision notice:** §7 (Revisions, 2026-05-01) supersedes earlier sections where it conflicts. Key changes: kind taxonomy collapses 5→4 in 2 axes (wire vs lifecycle); plugin-manifest-spec splits into B1 (contract freeze) + B2 (spec polish); harness-cleanup folds into pipeline-integration; reference-plugins drops from 3 to 1; plugin-architecture-ts reduces from full port to 1-day contract spike. 7 missed risks now addressed normatively in §7.5.

---

## 0. TL;DR

The SOX Protocol middleware framework is **architecturally correct but unwired**.

- `core/middleware/` contains a transport-independent pipeline, a registry with entry-point discovery, ADR 0003, normative `spec/ports/middleware.md`, 192 isolated tests, and a sample logging plugin.
- **Zero production code paths invoke it.** Both transports (`core/mcp_server/tools.py` for stdio, `adapters/transports/http/routes.py` for HTTP) bypass the pipeline and call `BackingStore` directly. Identity is enforced ad-hoc per route or trusted from environment variables.
- The conformance suite's stdio "pass" rate is partially an artifact of the test harness rejecting unregistered agents *client-side* with the explicit comment *"This mirrors the middleware layer that will sit in front of the backing store in the full stack."* The harness is substituting for the missing integration.
- Five of seven `DEFAULT_ORDER` links (`namespace_resolver`, `rate_limit`, `schema_validator`, `idempotency`, `audit_log`) are placeholder names with zero implementations.

To deliver the modular architecture the project intends — Express/Fastify/Connect-style pluggability where logging, auth, DB connections, etc. live outside core — three things must change:

1. **Plug the pipeline into both transports** (one engagement, mostly mechanical).
2. **Promote the plugin contract from in-code to spec** with a portable manifest, version negotiation, and a typed taxonomy (one spec engagement, one code engagement per language).
3. **Ship at least three reference plugins** outside `core/` (logging, audit, rate-limit) to prove the contract.

Estimated total effort: **~3 weeks for one engineer**, parallelizable to ~1.5 weeks across two.

---

## 1. The Diagnosis (concrete)

### 1.1 Framework exists and is correct

`grep -rn "from sox_protocol.adapters\|import adapters" packages/python/src/sox_protocol/core/middleware/` returns zero hits. lint-imports `core must not import from adapters` is kept. `Pipeline.dispatch(operation, input, *, connection_id, metadata)` is fully transport-agnostic — `MiddlewareContext` doesn't know what produced it.

The framework includes:

- `Pipeline` (`pipeline.py:32-166`) — reentrant dispatch, `ShortCircuitResponse` handling, internal-error envelope on uncaught exceptions
- `MiddlewareRegistry` (`registry.py:96-212`) — programmatic `.register(name, factory)` plus `load_entry_points(group="sox_protocol.middleware")` via `importlib.metadata`
- `MiddlewareContext` (`context.py:42-154`) — write-once `agent_id`, frozen `correlation_id`, mutable `input` / `metadata`
- `HookDispatcher` (`hooks.py:112-167`) — observation-only fan-out; pre-hooks may deny via `HookDecision`, post-hooks are read-only
- `build_default_pipeline()` (`default_chain.py:63-101`) — auto-registers `auth` + `store_dispatch`; skips missing optional links with startup warning
- `AuthMiddleware` (`plugins/auth.py`) — verifies via `IdentityVerifier`, sets `ctx.agent_id`, appends `middleware_timings`
- `StoreDispatchMiddleware` (`plugins/store_dispatch.py`) — terminal; switch over 15 v1 ops to `BackingStore` methods
- `LoggingMiddleware` (`plugins/logging.py`) — sample observation-only JSONL logger

192 isolated middleware tests + 80 identity tests pass.

### 1.2 Framework is not invoked anywhere in production

```
grep -rn "Pipeline\|build_default_pipeline\|AuthMiddleware\|StoreDispatchMiddleware" \
  packages/python/src/sox_protocol/ --include="*.py" \
  | grep -v "/middleware/\|/identity/\|test_\|/tests/\|__pycache__"
```

Returns **zero matches**.

### 1.3 The two transports' actual auth paths

**Stdio MCP** (`core/mcp_server/server.py:228` and `tools.py:88-94`):

```python
# server.py — lifespan startup
agent_id_source = os.environ.get("SOX_AGENT_ID_SOURCE", "").strip()
if agent_id_source == "claude_code_agent_name":
    agent_id = (...env lookup...)
else:
    agent_id = (...env lookup...)
# stitched into lifespan_result, trusted for connection lifetime

# tools.py — channels__send
lc = ctx.fastmcp._lifespan_result or {}
store: BackingStore = lc["store"]
agent_id: str = lc["agent_id"]              # <-- env-derived, no verification
message_id, sent_at, seq, bp = await store.send(channel, agent_id, body, ...)
```

A code comment at `server.py:224-227` acknowledges: *"the runtime adapter is using to inject the verified identity"* — i.e. trust is delegated upward to whoever launched the MCP process.

**HTTP** (`adapters/transports/http/auth.py:54-68` and `routes.py`):

```python
class PassthroughIdentityResolver:
    """Any non-empty token is accepted and used verbatim as the agent_id."""
    def resolve(self, token: str) -> str:
        if not token:
            raise ValueError("Empty bearer token")
        return token

# routes.py — every endpoint
agent_id, body, err = await _auth_and_body(request)
if err: return err
val_err = _validate_body("send", body)       # inline schema validation
if val_err: return val_err
result = await store.send(channel, agent_id, body, ...)
```

Each of the 22 HTTP endpoints repeats this same pattern. There is no shared auth middleware, no schema_validator middleware, no audit, no rate limit — every concern is hardcoded into route handlers or absent.

### 1.4 Conformance harness papers over the gap

`tools/conformance_runner.py:805-813`:

```python
# Enforce identity: reject unknown agents when the fixture declared
# an agents[] list.  This mirrors the middleware layer that will sit
# in front of the backing store in the full stack.
if self._registered_agents is not None and agent_id not in self._registered_agents:
    return {
        "_rpc_error": {
            "error_code": "unknown_agent",
            "message": f"Agent {agent_id!r} is not registered in this fixture",
        }
    }
```

This is the smoking gun. The harness rejects unregistered agents *itself*, on the client side, because the production server doesn't. Stdio's `02-unknown-credential-rejected` passes because of this client-side substitution. HTTP's same fixture fails because the harness goes over the wire to a real server, where rejection has to come from the server, where there is no middleware to do it.

### 1.5 Five DEFAULT_ORDER links are placeholders

`DEFAULT_ORDER = ("namespace_resolver", "auth", "rate_limit", "schema_validator", "idempotency", "store_dispatch", "audit_log")`. Of these:

- `auth`, `store_dispatch` — implemented in `core/middleware/plugins/`
- `namespace_resolver`, `rate_limit`, `schema_validator`, `idempotency`, `audit_log` — **zero production code anywhere in the repo**, only string mentions

`build_default_pipeline()` skips missing links with `warnings.warn`. A user starting a SOX server today gets no warning that 5 of 7 normative links are absent — it just runs.

### 1.6 Plugin discovery exists but is not wired

`MiddlewareRegistry.load_entry_points()` exists. No production code calls it.

```bash
grep -rn "load_entry_points" packages/python/src/sox_protocol/ --include="*.py" \
  | grep -v test
```

Returns one match: the method definition itself. The mechanism is built and tested in isolation but never executed at server startup.

### 1.7 TypeScript SDK has no middleware story

`packages/typescript/README.md` plans `core/enforcer/`, `core/mcp_server/`, `core/ports/`. Conspicuously absent: `core/middleware/`. The decision has not been made for the second-language implementation. The window for getting it right before code lands is now.

### 1.8 The user's framing is exactly right

Express, Fastify, Connect, Koa, Django, FastAPI, NestJS, gRPC, and Next.js all keep cross-cutting concerns *out* of the core via a plugin contract. SOX has the contract and the framework. SOX does not yet *use* its own contract. This is the single most important architectural debt in the project.

---

## 2. Target Architecture

### 2.1 What "plugin" means in SOX

Drawing the taxonomy from NestJS (separation by intent) and FastAPI (separation of "around-the-handler" vs "injected dependency"), without their language-specific binding mechanisms:

| Kind | Contract | Examples | Can short-circuit? | Mutates context? |
|---|---|---|---|---|
| **Interceptor** | `async (ctx, next) -> response` (Koa-shaped) | logging, audit, metrics, tracing, rate-limit | Yes (return without `next()` — but explicit) | No (read-only ctx; emit via separate sink) |
| **Guard** | `async (ctx) -> Decision{allow|deny}` | auth, namespace authorization | Yes (deny → sox-error) | No (sets `ctx.agent_id` only on allow, via narrow API) |
| **Transformer** | `async (ctx) -> ctx'` | schema_validator, namespace_resolver, idempotency_dedupe | Yes (validation_failed → sox-error) | Yes (replaces `ctx.input` with normalized form) |
| **Provider** | factory `() -> Resource` | db_connection, identity_registry, key_cache | No | No (lifecycle: server-singleton, request-scoped, or per-tenant) |
| **Hook** | `async (immutable_ctx) -> None | HookDecision` | Pre-hooks: yes (deny). Post-hooks: no | No (immutable view enforced) |

The current codebase collapses interceptor + guard + transformer into one "middleware" concept and has hooks as a separate sugar layer. That's *one valid choice*; another (recommended) choice is to keep all four under a single Pipeline machinery but tag each plugin with its kind in the manifest, so the host can validate that a plugin declared `kind: guard` doesn't perform mutations, etc.

The advantage of the taxonomy is that it's expressible in spec and YAML without language-specific decorators or DI containers.

### 2.2 The plugin manifest

The single most replicable pattern from the research is Fastify's `fastify-plugin` metadata block. Adapted to a YAML-expressible spec form:

```yaml
# myorg-sox-jwt-auth/sox-plugin.yaml
sox_plugin:
  name: jwt-auth
  version: 1.2.0
  protocol_version: "1.x"           # SOX plugin-protocol semver range
  kind: guard                       # interceptor | guard | transformer | provider | hook
  applies_to:
    operations: ["send", "recv", "subscribe", "list_agents"]
    transports: ["*"]               # or a list — defaults to all
  requires:                         # other plugins this one depends on
    - identity_registry: "1.x"
  provides:                         # capabilities this plugin exposes
    - auth.method: "jwt-bearer"
  must_run_before: ["store_dispatch", "rate_limit"]
  must_run_after: ["namespace_resolver"]
  config_schema: ./config.schema.json
  entry:
    python: "myorg_sox_jwt_auth:make_plugin"
    typescript: "@myorg/sox-jwt-auth/dist/plugin.js#default"
```

The host validates this manifest at startup. Incompatible `protocol_version` is a refusal-to-load with a clear error. Missing `requires` is a startup error. The actual implementation in `entry.python` returns a `Middleware` instance compatible with the in-language Pipeline.

This is **declarative scope** (Next.js pattern: `applies_to` is data, not code), **versioned** (Fastify pattern: explicit `protocol_version`), **typed by intent** (NestJS pattern: `kind` is a closed set), and **language-agnostic** (gRPC pattern: the manifest is portable; per-language `entry` points to whatever's idiomatic).

### 2.3 The plugin runtime contract (Python)

Aligned with what already exists in `core/middleware/protocol.py` plus what the research shows must be added:

```python
class Middleware(Protocol):
    name: str
    kind: PluginKind                      # NEW — from manifest
    must_run_before: tuple[str, ...]
    must_run_after: tuple[str, ...]

    async def __call__(
        self,
        ctx: MiddlewareContext,
        next: CallNext,                   # explicit, never omitted
    ) -> dict[str, object]:
        ...

    # OPTIONAL hooks for lifecycle (Fastify pattern):
    async def on_startup(self, ctx: ServerContext) -> None: ...
    async def on_shutdown(self, ctx: ServerContext) -> None: ...
```

`ctx.next()` MUST be called explicitly (no implicit short-circuit by omission — that was the worst Express footgun). To skip downstream, the plugin returns a `ShortCircuitResponse` exception (already present) OR returns a tagged dict — whichever is cleaner; pick one and document.

### 2.4 The plugin runtime contract (TypeScript — designed alongside)

```typescript
export interface SoxMiddleware {
  readonly name: string;
  readonly kind: PluginKind;
  readonly mustRunBefore: readonly string[];
  readonly mustRunAfter: readonly string[];

  call(ctx: MiddlewareContext, next: CallNext): Promise<Response>;

  onStartup?(ctx: ServerContext): Promise<void>;
  onShutdown?(ctx: ServerContext): Promise<void>;
}

export type CallNext = (ctx: MiddlewareContext) => Promise<Response>;
```

Same shape, idiomatic TS naming. Both implementations consume the same YAML manifest.

---

## 3. Spec Changes

The spec at `spec/ports/middleware.md` defines middleware as an interface. It does not define the *plugin contract* — manifest, discovery, versioning, taxonomy. These need normative additions.

### 3.1 Promote `spec/ports/middleware.md` to `spec/ports/middleware/`

Convert single-file port doc to a directory:

```
spec/ports/middleware/
├── README.md                  # overview + table of contents
├── 01-context.md              # MiddlewareContext field-by-field, normative
├── 02-pipeline.md             # Pipeline semantics, ordering, short-circuit
├── 03-plugin-contract.md      # NEW — kind taxonomy, signatures, lifecycle
├── 04-manifest.md             # NEW — sox-plugin.yaml schema, normative
├── 05-discovery.md            # NEW — entry_points (Python) + package.json
│                              #       "sox" key (TS), normative
├── 06-versioning.md           # NEW — protocol_version semver rules
├── 07-default-chain.md        # current §4 content; chain order normative
└── 08-conformance.md          # current §9 content + new fixtures for plugins
```

### 3.2 New normative documents

**`03-plugin-contract.md`** — defines the five kinds (Interceptor, Guard, Transformer, Provider, Hook) with:
- Required signature for each
- What each kind MAY and MUST NOT do (mutation rules)
- How a host validates `kind` matches behavior (e.g. hosts MAY refuse if a `kind: guard` plugin returns a non-`Decision` value at runtime — this is testable in conformance)

**`04-manifest.md`** — JSON Schema for `sox-plugin.yaml`. Required fields: `name`, `version`, `protocol_version`, `kind`, `entry`. Optional: `applies_to`, `requires`, `provides`, `must_run_before`, `must_run_after`, `config_schema`. The schema lives at `spec/schemas/sox-plugin.schema.json` (parallel to the existing `spec/operations/*.input.schema.json`).

**`05-discovery.md`** — defines two parallel discovery mechanisms, both normative for their language:
- Python: `pyproject.toml` `[project.entry-points."sox_protocol.plugins"]` declarations. Host calls `importlib.metadata.entry_points(group="sox_protocol.plugins")` at startup.
- TypeScript / Node: `package.json` top-level `"sox"` key pointing to manifest path: `"sox": "./sox-plugin.yaml"`. Host scans `node_modules/*/package.json` for the key.
- Both: programmatic `register_plugin(name, factory)` API for in-tree composition / testing.

**`06-versioning.md`** — protocol_version is `MAJOR.MINOR`. Major bump = plugin contract breaks (signature changes). Minor bump = new optional fields / new kinds. Plugins declare a *range*: `"1.x"`, `"1.2-2.0"`, `">=1.1"`. Host refuses incompatible plugins at load with `protocol_version_mismatch` error.

### 3.3 ADR 0004 — Plugin Architecture

ADR 0003 picked "hybrid middleware + hooks." ADR 0004 builds on it: "Adopt manifest-driven discovery, kind taxonomy, and protocol_version negotiation." Cross-references 0003.

### 3.4 New conformance fixtures

Under `spec/conformance/plugin-contract/`:
- `01-plugin-loads-via-entry-point.yaml` — install a stub plugin via test fixture, confirm host discovers it
- `02-version-mismatch-refused.yaml` — plugin with incompatible `protocol_version` refuses to load with proper error
- `03-kind-taxonomy-enforced.yaml` — host rejects plugin whose runtime behavior contradicts declared `kind`
- `04-applies-to-scope.yaml` — plugin scoped to specific operations runs only for those
- `05-must-run-before-after.yaml` — ordering constraints honored
- `06-short-circuit-explicit.yaml` — pipeline halts on tagged short-circuit response

These run against any conforming implementation — Python, TypeScript, or future ones.

---

## 4. Code Changes

### 4.1 Engagement A — `pipeline-integration` (Python, both transports)

**Goal:** make `Pipeline` the only path to `BackingStore` in production code.

**Stdio (`core/mcp_server/`):**

1. `server.py` — at lifespan startup, build `pipeline = build_default_pipeline(verifier=..., store=...)`. Stash in `lifespan_result["pipeline"]` instead of (or alongside) `store`/`agent_id`.
2. `tools.py` — convert each of the 4 currently-shipped tool handlers (`channels__send`, `channels__recv`, `channels__subscribe`, `channels__list_channels`) plus the 11 new ones (groups, threading, presence, replay, ack, etc.) from direct `store.<op>(...)` calls to:
   ```python
   return await pipeline.dispatch(
       operation="<op_name>",
       input=<args_dict>,
       connection_id=lc["connection_id"],
       metadata={"_connection_credential": _resolve_credential(ctx)},
   )
   ```
3. The credential resolution helper `_resolve_credential()` builds a `SignedRequest` from MCP launch params (already half-wired per the salvage's spec §6 fix in `auth.py:102-104`). Today this code only fires if `AuthMiddleware` runs; after this engagement it actually runs.

**HTTP (`adapters/transports/http/`):**

1. `app.py` (or wherever `build_app` lives) — accept `pipeline` parameter, plumb to `routes.create_router(pipeline)`.
2. `routes.py` — replace the `_auth_and_body` + direct-store pattern in all 22 handlers with the same `pipeline.dispatch(...)` call.
3. `auth.py` — delete `PassthroughIdentityResolver` entirely. Reduce to ~5 lines of `extract_bearer_token(request)`. The actual verification happens in `AuthMiddleware`, same as stdio.

**Both:**

4. The conformance harness's client-side rejection block (`tools/conformance_runner.py:805-813`) gets *deleted*. The production server now enforces. If conformance regresses, the framework caught a real bug. If it goes green for both transports, the integration is done.

5. Decide credential-on-connection-seam for HTTP. Two options surveyed:
   - Each request is its own "connection" — verifier runs per request, no caching. Stateless, simple, slightly more CPU.
   - Optional `X-Sox-Connection-Id` header binds a credential to a server-side session — verifier caches the binding by connection_id. Faster, but requires session storage. Defer to a v1.1 feature.
   - **Recommended for v1: per-request, stateless.**

**Estimated effort:** 3-4 days. Mechanical refactor; the pipeline is already built and the credential resolution code is already in `AuthMiddleware`.

**Tests:**
- 22 existing HTTP tests + 80 stdio tests must still pass
- Conformance suite: 32/32 against both transports identically (currently 32/0/27 stdio, 22/10/27 HTTP)
- New regression tests: assert `Pipeline.dispatch` is called exactly once per HTTP request and per MCP tool call (would catch a future "did someone re-add a direct store call" regression)

### 4.2 Engagement B — `plugin-manifest-spec`

**Goal:** ship the spec changes from §3 above. Pure spec/docs engagement, no code.

**Deliverables:**
- `spec/ports/middleware/` directory with the 8 files
- `spec/schemas/sox-plugin.schema.json`
- `docs/adr/0004-plugin-architecture.md`
- `spec/conformance/plugin-contract/` fixtures (initially marked `pending: true` until Engagement C ships the implementation)

**Estimated effort:** 4-5 days. Spec writing is slow and important.

### 4.3 Engagement C — `plugin-discovery-py`

**Goal:** wire `MiddlewareRegistry.load_entry_points()` into server startup, with manifest validation.

**Deliverables:**
1. New `core/middleware/plugin_loader.py`:
   - Reads `sox-plugin.yaml` from a discovered package
   - Validates against `sox-plugin.schema.json`
   - Validates `protocol_version` against host's supported range
   - Constructs `Middleware` via the declared `entry.python` factory
   - Returns to caller as registered, ready-to-assemble plugin
2. `MiddlewareRegistry.load_plugins()` — calls `load_entry_points` AND validates manifests AND registers, all together.
3. Server bootstrap (`mcp_server/server.py` and `transports/http/app.py`) — calls `registry.load_plugins()` after `build_default_pipeline`, so out-of-tree plugins compose with the default chain.
4. CLI flag: `sox serve --no-discovery` to disable (testing, security audits).
5. Test: install a stub plugin into a temp venv, confirm it's discovered and runs.

**Estimated effort:** 3-4 days.

### 4.4 Engagement D — `reference-plugins`

**Goal:** ship 2-3 plugins outside `core/` to prove the contract.

**Candidates (pick 3 for v1):**
1. **`sox-plugin-audit-jsonl`** — separate package, kind: interceptor, writes JSONL audit log, demonstrates an interceptor with optional config (path, rotation).
2. **`sox-plugin-rate-limit-redis`** — kind: guard, requires `provider:redis_pool`. Demonstrates a guard with a `requires` dependency on a provider.
3. **`sox-plugin-schema-strict`** — kind: transformer, validates `input.body` against the operation's input schema. Migrates the inline `_validate_body` from `routes.py` to a real plugin.

Each plugin lives in its own directory under `plugins/` (sibling to `packages/`) or in a separate repo, with its own `pyproject.toml`, manifest, tests.

**Estimated effort:** 1-2 days per plugin once the framework lands. Run in parallel.

### 4.5 Engagement E — `plugin-architecture-ts`

**Goal:** mirror Python plugin architecture in the TypeScript SDK before TS code lands.

**Deliverables:**
- `packages/typescript/src/core/middleware/` — Pipeline, Registry, Context (port from Python)
- TS-side manifest reader with same JSON Schema validation
- `package.json` `"sox"` key discovery
- TS reference plugin (one of the three from Engagement D, ported)

**Estimated effort:** 1 week. Largely a port; the design decisions are made in Python first.

### 4.6 Engagement F — `harness-cleanup`

**Goal:** remove the conformance harness's client-side identity rejection (`tools/conformance_runner.py:805-813`) once Engagement A ships and both transports enforce server-side.

**Deliverables:**
- Delete the rejection block
- Confirm conformance suite still 32/32 against both transports
- Add a new fixture asserting that an unregistered agent's send is rejected by the *server*, not the harness

**Estimated effort:** 1 day. Strictly cleanup.

### 4.7 Critical path

```
A (pipeline-integration) ────────────┐
                                     │
B (plugin-manifest-spec) ─── C (discovery-py) ─── D (reference-plugins)
                                     │                           │
                                     └── E (architecture-ts) ────┘
                                                                  │
                                                                  └── F (harness-cleanup)
```

A is independent and unblocks F. B is independent. C requires B. D requires B and C. E can start as soon as B lands. F requires A.

**Parallel timeline:**
- Week 1: A + B (parallel)
- Week 2: C + start E
- Week 3: D + finish E + F

**Single-engineer timeline:** ~3 weeks sequential.

---

## 5. Risks & Open Questions

### 5.1 Already-released spec compatibility

`docs/adr/0003-extensibility-mechanism.md` is committed. `spec/ports/middleware.md` is normative. Promoting middleware.md to a directory + adding ADR 0004 is *additive*; no existing claim is broken. The kind-taxonomy split (Interceptor / Guard / Transformer / Provider / Hook) is new vocabulary but doesn't invalidate any existing plugin.

`AuthMiddleware` becomes an example of `kind: guard`; `StoreDispatchMiddleware` is `kind: provider` (terminal, infrastructural); `LoggingMiddleware` is `kind: interceptor`. All three already conform to the runtime shape; only their declared `kind` is new metadata.

### 5.2 Performance

Going from "store.send() direct call" to "pipeline.dispatch()" adds 5-7 middleware function calls per request. Each is negligible (microseconds), but worth measuring with `pytest-benchmark` against the existing baseline. The Pipeline already builds the call chain once per dispatch via recursion, which is fine but could be optimized to a flat compiled list if benchmarks show overhead. Defer the optimization until measured.

### 5.3 Concurrency

`Pipeline` is documented as reentrant — fresh `MiddlewareContext` per dispatch. This holds because `dispatch()` calls `MiddlewareContext(...)` on every call. The `_StoreTerminal` adapter (default_chain.py:44-60) wraps a single `StoreDispatchMiddleware` instance; the instance has no per-call mutable state, so it's safe. Confirmed in `test_pipeline_is_reentrant` (50 concurrent dispatches).

The verifier replay-cache TOCTOU flagged in the hooks-middleware review (`verifier.py:198-223`) becomes more relevant once auth runs per-request: under contention, two concurrent verifies of the same nonce can both pass. Engagement A should bundle the asyncio.Lock fix the reviewer recommended.

### 5.4 The `applies_to.transports` field

Some plugins make sense for both transports (auth, rate-limit, audit). Some only make sense for HTTP (CORS, body-size limit). Some only for stdio (MCP-specific concerns). The manifest's `applies_to.transports: ["http"]` filter solves this declaratively.

But: in our codebase, "transport" is not a first-class entity in `MiddlewareContext`. We'd need to either (a) add `ctx.transport: str` to context, (b) the host registers different pipelines per transport from the same plugin set, or (c) plugins themselves check `ctx.metadata["transport"]`. **Option (b) is cleanest** — it's a load-time decision, not a per-request branch.

### 5.5 Configuration

A real plugin needs config (e.g. rate-limit per-second number, audit log path). The manifest's `config_schema` field handles validation; the host needs to provide the config to the plugin factory. Three options:

1. Environment variables (`SOX_PLUGIN_<name>_<key>`) — works cross-language, ugly for nested config.
2. A `sox.yaml` config file in the working directory, with sections per plugin name. Cleaner.
3. CLI flags (`--plugin-config name.key=value`).

**Recommended: (2) for primary, (1) for overrides, (3) for ad-hoc.** Modeled after Fastify and Django.

### 5.6 The `provider` kind isn't in the existing pipeline

`Provider` plugins (db connections, key caches) don't fit the `(ctx, next) -> response` shape — they're injected dependencies, not pipeline links. Two options:

1. **Separate registration mechanism**: `registry.register_provider(name, factory)`. Pipeline gets read-only access via `ctx.providers[name]`. This is closer to FastAPI's `Depends`.
2. **Treat providers as just plugins with no `__call__`**: registered, lifecycle-managed (`on_startup`/`on_shutdown`), but never appear in DEFAULT_ORDER.

**Recommended: option 1**, separate concept, separate API. Clearer to spec, clearer to implement.

### 5.7 What happens to the existing `HookDispatcher`?

It's a useful pattern (observation-only fan-out with immutable view) but it overlaps with the proposed `Hook` kind. Either:

1. Keep `HookDispatcher` as the canonical implementation of `kind: hook` plugins — third-party hooks register through it.
2. Generalize: hooks become first-class plugins, no separate dispatcher.

**Recommended: option 1**. The dispatcher is built and tested; just relabel its inputs as `kind: hook` plugins from the manifest perspective.

### 5.8 Open spec question: composability of Decisions

`HookDecision` is a single structure today. With kind-typed plugins, each kind has its own decision shape:
- Guard: `Decision{allow: bool, reason: str}`
- Transformer: returns transformed `ctx` or raises
- Interceptor: returns response or raises `ShortCircuitResponse`
- Hook: `HookDecision{action: 'allow'|'deny'}`

These shapes are different; the spec must define them precisely so a TS implementation produces the same decisions a Python one does given the same inputs.

---

## 6. What I Recommend Doing First

If this analysis is approved, the order is:

1. **File ADR 0004** as a draft PR. Get architectural buy-in before code lands.
2. **Engagement A first** (pipeline-integration). Fixes the conformance HTTP failures, removes the harness substitution, makes the existing middleware framework actually do work. High visible value, mechanical work.
3. **Engagement B second** (plugin-manifest-spec). Specifies the contract before any out-of-tree plugin gets built — preventing the "now we have three plugins each with a different ad-hoc interface" failure mode.
4. **Engagements C, D, E in parallel.** C wires discovery; D proves the contract with real plugins; E ships the TypeScript side using the now-frozen contract.
5. **Engagement F last.** Cleanup; should be unblocked by A but better deferred until reference plugins (D) prove the contract holds end-to-end.

The single highest-value commit in the whole program is the deletion of `tools/conformance_runner.py:805-813`. When that block goes away and conformance still passes against both transports, we'll know the architecture is real, not aspirational.

---

## Appendix A: Files referenced in this analysis

Codebase:
- `packages/python/src/sox_protocol/core/middleware/{pipeline,registry,context,default_chain,protocol,hooks,errors}.py`
- `packages/python/src/sox_protocol/core/middleware/plugins/{auth,store_dispatch,logging}.py`
- `packages/python/src/sox_protocol/core/mcp_server/{server,tools,listener}.py`
- `packages/python/src/sox_protocol/adapters/transports/http/{app,routes,auth}.py`
- `packages/python/src/sox_protocol/core/identity/{verifier,keys,registry,envelope,audit}.py`
- `tools/conformance_runner.py:805-813`

Spec:
- `spec/ports/middleware.md`
- `docs/adr/0003-extensibility-mechanism.md`
- `spec/operations/*.input.schema.json`

Tests:
- `packages/python/tests/middleware/test_external_plugin.py`
- `packages/python/tests/middleware/test_default_chain.py`

Prior engagements:
- `.workflow/plans/hooks-middleware/` — built the framework
- `.workflow/plans/identity-primitive/` — built AuthMiddleware
- `.workflow/plans/http-transport/STATE.md` — flagged the integration gap

Research memory (peer frameworks):
- Express 4.x/5.x — `(req, res, next)` middleware contract
- Fastify 5.x — named hooks + `fastify-plugin` metadata block
- Connect — minimum-viable middleware substrate
- Koa — async/await onion model
- NestJS — Interceptor/Guard/Pipe taxonomy
- Next.js — declarative `matcher` config
- Django — settings-list discovery
- FastAPI — `Depends()` parameter injection
- gRPC — cross-language interceptor protocol with split inbound/outbound

---

## 7. Revisions (v2, 2026-05-01)

The original analysis (§§0–6) was reviewed by `workflow-optimizer` and triaged
against three new research findings dispatched to `workflow-researcher`:

- `~/.claude/plugins/workflow/memory/research/plugin-manifest-formats/cross-language-convergence.md`
- `~/.claude/plugins/workflow/memory/research/plugin-taxonomies/multi-kind-vs-unified-middleware.md`
- `~/.claude/plugins/workflow/memory/research/plugin-protocol-versioning/version-declaration-and-negotiation.md`

This section integrates both reviews and supersedes the earlier text where
conflicting. Sections referencing prior decisions are explicit about what
changed and why.

### 7.1 Kind taxonomy — revised from 5 kinds (§2.1) to 4 kinds in 2 axes

**Original (§2.1):** flat 5-kind taxonomy — Interceptor, Guard, Transformer,
Provider, Hook.

**Research finding** (`plugin-taxonomies/multi-kind-vs-unified-middleware.md`):
flat responsibility-bucket taxonomies (NestJS's 5-kind split) suffer
perennial "which kind do I need?" confusion in production
([nestjs#541](https://github.com/nestjs/nest/issues/541),
[#9269](https://github.com/nestjs/nest/issues/9269),
[#337](https://github.com/nestjs/nest/issues/337)). Mid-size NestJS apps
collapse usage to Guard+Interceptor only; Pipe and ExceptionFilter usage is
rare. Spring AOP's "least-powerful advice" doctrine — `@Around` is a superset
of `@Before`/`@After` — survived 20+ years; teams routinely use the most
powerful kind because the others don't add expressive power, only ceremony.

**Convergent finding across surveyed frameworks:** the *durable* axis is
**wire vs lifecycle** — per-message callbacks vs per-process callbacks.
Hapi, Fastify, gRPC, and River all separate these. Strapi v5 migrated
*from* lifecycle hooks *to* middleware because hooks didn't compose; the
lesson is that within one axis, kinds collapse, but the wire/lifecycle
boundary itself is real and durable.

**Decision:** adopt the 2-axis split.

| Axis | Kind | Contract | Replaces |
|---|---|---|---|
| **Wire** | `interceptor` | `async (ctx, next) -> response` | original Interceptor + Guard (a guard is just an interceptor that returns deny — Spring AOP doctrine) |
| **Wire** | `transformer` | `async (ctx) -> ctx'` | original Transformer (unchanged; sufficient distinct semantics — input rewrite is not response wrapping) |
| **Lifecycle** | `provider` | factory `() -> Resource` with `on_startup`/`on_shutdown` | original Provider (unchanged) |
| **Lifecycle** | `hook` | `async (immutable_ctx) -> None | HookDecision` | original Hook (unchanged) |

**`interceptor` capability flags** (research recommendation: capability lattice
declared via registration flags rather than separate kinds):

```yaml
kind: interceptor
capabilities:
  observe_only: true        # Spring's @AfterReturning equivalent — runtime asserts no short-circuit
  may_short_circuit: false  # explicit — host can elide call_next instrumentation
```

A plugin declared `observe_only: true` that returns a `ShortCircuitResponse`
at runtime is a contract violation; host MAY refuse to load on startup if the
contract can be statically inferred, MUST log and convert to `internal_error`
at runtime if not.

**Net effect:** 4 distinct contracts instead of 5. AuthMiddleware's existing
implementation in `core/middleware/plugins/auth.py` becomes
`kind: interceptor` (it returns deny via `ShortCircuitResponse`); the
"Guard is its own kind" decision the original analysis made was speculative
and the research consensus is to collapse it.

### 7.2 Manifest format — revised from §2.2 with research-grounded universals

**Original (§2.2):** speculative YAML manifest with `name`, `version`,
`protocol_version`, `kind`, `applies_to`, `requires`, `provides`,
`must_run_before/after`, `config_schema`, `entry`.

**Research finding** (`plugin-manifest-formats/cross-language-convergence.md`):
across 8 surveyed systems (Backstage, Envoy/xDS, OPA, gRPC, VS Code, Babel,
ESLint, Terraform), 5 fields are universal:

1. Stable string `id` — globally unique
2. Content `version` — SemVer
3. `kind`/`type` — closed enum (open strings are a JS-ecosystem anti-pattern)
4. `capabilities` — what the plugin provides/exposes
5. `scope`/`applies_to` — where the plugin runs

5 of 8 systems also separate the **schema/manifest version** from the
**content version** (Envoy `type-URL v3`, Terraform `version: 1`, VS Code
`engines.vscode`, Backstage `apiVersion`, gRPC proto `syntax`). The 3 that
don't (OPA, Babel, ESLint) rely on naming-convention-as-version, which is
JS-ecosystem-only and doesn't generalize. **Adopt the two-axis pattern.**

**Critical research finding:** keep `entry` (the language-specific loader
hint) **OUT of the manifest body.** Envoy and OPA both made this choice;
it is the *only* way to keep the manifest genuinely language-neutral.
Language-specific loading lives in the language's package metadata
(Python `pyproject.toml [project.entry-points]`, Node `package.json#exports`)
and the manifest references the plugin by ID only.

**Decision — revised manifest schema:**

```yaml
# sox-plugin.yaml — language-neutral
sox_plugin:
  apiVersion: sox.dev/v1                  # NEW — manifest schema version (Backstage pattern)
  kind: SoxPlugin                         # NEW — closed enum, distinguishes from other YAML
  metadata:
    id: org.example.sox-jwt-auth          # globally unique stable identifier
    version: 1.2.0                        # content SemVer
  spec:
    protocol_version: ">=1.0,<2.0"        # PEP 440 / npm-compatible semver range
    plugin_kind: interceptor              # one of: interceptor, transformer, provider, hook
    plugin_capabilities:
      - auth.method: jwt-bearer           # capability strings (research: primary mechanism)
      - observe_only: false
    applies_to:
      operations: [send, recv, subscribe, list_agents]
      transports: ["*"]
    requires:                             # capability strings, not plugin names (research)
      - identity.registry: ">=1.0,<2.0"
    must_run_before: [persistence.terminal]
    must_run_after: [namespace.resolver]
    config_schema_ref: ./config.schema.json
    signatures: []                        # NEW — reserved per research §5; unsigned in v1
                                          #       (research: reserve from day 1, harder to add later)
```

**Language-specific entry registration** (Python `pyproject.toml`):

```toml
[project.entry-points."sox_protocol.plugins"]
"org.example.sox-jwt-auth" = "myorg_sox_jwt_auth:make_plugin"
```

**Language-specific entry registration** (Node `package.json`):

```json
{
  "name": "@myorg/sox-jwt-auth",
  "sox": "./dist/sox-plugin.yaml",
  "exports": { "./plugin": "./dist/plugin.js" }
}
```

The host loads `sox-plugin.yaml` to validate schema, kind, capabilities, and
version. It then resolves the language-specific entry point (Python entry-point
group or Node package.json `sox` key) to actually instantiate the plugin.
**These two layers are deliberately decoupled.**

### 7.3 Protocol-version negotiation — research-grounded decision

**Original (§2.2 — option-a from earlier):** speculative `protocol_version:
"1.x"` semver range field. Optimizer's question 5 raised three candidates.

**Research finding** (`plugin-protocol-versioning/version-declaration-and-negotiation.md`):
single semver range with caret-range semantics is the convergent practice.
Multi-axis versioning (option c) is the precise maintenance burden Kubernetes
warns about — a 3-D compatibility cube no human reasons about correctly.
Integer + flags (option b) loses minor granularity and grows flag sets
monotonically.

**Decision — adopt option (a) augmented with capability flags as escape
hatch only:**

- `protocol_version` — single semver range, **PEP 440 form on the wire**
  (`>=1.0,<2.0`), parses cleanly in both Python (`packaging.specifiers.SpecifierSet`)
  and Node (`node-semver` accepts equivalent space-separated form).
- `plugin_capabilities` — small, named capability flags for genuinely optional
  features (modeled on VS Code `enabledApiProposals` — narrow scope, never a
  substitute for the primary version axis).
- **Boot-time refusal** with structured error envelope. Lazy refusal is
  forbidden — research shows it's only acceptable when the API surface is
  too large to enumerate (gRPC), which is not SOX's case.
- Pre-release markers normalized to PEP 440 form (`1.0.0a1`); manifest schema
  documents the equivalent npm form (`1.0.0-alpha.1`) for TS-side parsers.

**Refusal envelope** (boot time, structured):

```json
{
  "error_code": "plugin_protocol_version_mismatch",
  "plugin_id": "org.example.sox-jwt-auth",
  "plugin_declares": ">=1.0,<2.0",
  "host_supports": "2.1.0",
  "remediation": "upgrade plugin to a version supporting protocol >=2.0"
}
```

### 7.4 Signing / supply-chain — reserved field, deferred enforcement

The research finding flagged this independently: every mature manifest format
either ships signing from day 1 (Sigstore/Cosign for OCI, Helm provenance
files) or wishes it had. The retrofit cost is high — every plugin must be
re-published.

**Decision:** reserve `signatures: []` in the manifest schema from v1.0
(empty list permitted). v1 host enforcement: `--allow-plugins ID,ID,...` CLI
allowlist (per optimizer's risk #1). v1.x adds: optional manifest-hash
pinning (`sha256:...`); v2.0 considers: in-band signature verification.
The reserved field is cheap; the option to add real verification later
without breaking the manifest schema is valuable.

### 7.5 Risk addenda — 7 risks the original §5 missed (per optimizer)

| # | Risk | Decision | Where addressed |
|---|---|---|---|
| 1 | Plugin trust / supply-chain — `load_entry_points` is a code-execution boundary | **In scope B1.** `--allow-plugins ID,...` CLI flag (mandatory in production); `signatures: []` reserved field (per §7.4) | `plugin-contract-freeze:01-adr` + `plugin-discovery-py:02-build` |
| 2 | Plugin failure semantics per kind — what does an exception do? | **In scope B1.** Spec normative defaults: `interceptor` exception → `internal_error` envelope; `transformer` exception → `validation_failed` envelope; `provider` exception at startup → fail-fast (host refuses to start); `hook` exception → swallowed + logged with correlation_id (observation-only, never blocks) | `plugin-contract-freeze:03-plugin-contract` (new spec section) |
| 3 | Plugin ordering ambiguity / cycles in `must_run_before/after` | **In scope B1.** Algorithm: stable Kahn's topological sort; tie-break by lexicographic plugin id (deterministic across implementations); cycle → `plugin_ordering_cycle` error at startup with the cycle named in the message | `plugin-contract-freeze:03-plugin-contract` + spec/conformance/plugin-contract/05-must-run-before-after.yaml |
| 4 | Hot-reload / dynamic registration — locking in static-only is a forever spec hazard | **Out of scope v1; documented defensively.** Spec note: *"v1.x: composition is static at startup. Implementations MUST NOT depend on stable Pipeline identity across reloads. v2.x may relax to support add/remove."* This buys the freedom to relax later without breaking v1 contracts | `plugin-contract-freeze:01-adr` §"v1 limitations" |
| 5 | Conformance-suite coupling — risk of re-enabling substitution to keep CI green | **In scope A.** New CI matrix entry: `conformance-substitution-removed` mode, mandatory pass after A. The legacy mode (with substitution) is renamed `conformance-legacy` and slated for removal in v1.1. Both modes co-exist briefly to allow rollback if A regresses | `pipeline-integration:06-delete-harness-substitution` (new phase, absorbing F per §7.6) |
| 6 | `sox.yaml` config schema unbudgeted | **Descope for v1.** Configuration via environment variables only with conventional naming: `SOX_PLUGIN_<plugin_id>_<key>`. `sox.yaml` deferred to v1.x post-launch as a quality-of-life improvement, not a blocker. Rationale: env-var config has zero schema-evolution cost; `sox.yaml` introduces a new artifact requiring its own spec, validation, and migration story | analysis §5.5 superseded; documented in B1 ADR |
| 7 | Pipeline observability — debugging "why did request fail in plugin X?" | **In scope A, lightweight.** Extend existing `metadata["middleware_timings"]` to a structured `metadata["pipeline_trace"]` array: per-plugin `{plugin_id, kind, started_at, finished_at, verdict: continue\|short_circuit\|error, error_code?}`. OTel-compatible span shape later in v1.x; v1 ships the structured array only. Sufficient for `grep` and CI assertions | `pipeline-integration:02-build-stdio` + `:03-build-http` (extend existing AuthMiddleware timing emission to all plugins via Pipeline base) |

### 7.6 Engagement decomposition — revised per optimizer suggestions

**Original (§4.7):** 6 sub-engagements with the dependency graph
`A independent, B independent, C requires B, D requires B+C, E requires B,
F requires A`.

**Revised structure** (5 sub-engagements; F absorbed; B split; D narrowed; E
descoped):

| New slug | Replaces | Scope | Effort | Prereqs |
|---|---|---|---|---|
| `pipeline-integration` | A + F | Wire Pipeline into both transports; delete PassthroughIdentityResolver; **delete `tools/conformance_runner.py:805-813`** (was F); add structured `pipeline_trace` (was risk #7); ship asyncio.Lock for verifier replay race | 4-5d (was 3-4d for A alone) | — |
| `plugin-contract-freeze` | B1 (split from B) | ADR 0004 + JSON Schema for `sox-plugin.yaml` + 03-plugin-contract.md (with §7.5 risk addenda spec'd) + 06-versioning.md. **Sufficient to unblock C/D/E.** | 2-3d (was 4-5d for full B) | — |
| `plugin-spec-polish` | B2 (split from B) | Directory restructure (01/02/05/07/08), the 6 conformance fixtures, cross-references, README polish | 2-3d | `plugin-contract-freeze` (parallelizes with C/D/E) |
| `plugin-discovery-py` | C | Wire `load_entry_points` + manifest validation + `--allow-plugins` allowlist into both server bootstraps | 3-4d | `plugin-contract-freeze` (only) |
| `reference-plugins` | D-reduced | **One plugin only:** `schema-strict` (transformer) — migrates `routes._validate_body` out of core. The other two (audit-jsonl, rate-limit-redis) move to `reference-plugins-extended` post-v1 | 2d (was 3-6d) | `plugin-discovery-py` |
| `plugin-architecture-ts` | E-spike | **1-day contract spike:** ship `packages/typescript/src/core/middleware/protocol.ts` (interfaces only), validate `sox-plugin.yaml` round-trips through TS YAML+AJV. Full TS Pipeline runtime deferred to whenever TS production code lands | 1d (was 1w) | `plugin-contract-freeze` |
| ~~`harness-cleanup`~~ | — | **Removed** — folded into `pipeline-integration` as phases 06/07 | 0d (was 1d) | — |

**Critical-path compression:** original ~21 days → revised ~13 days (38%
reduction) under sequential single-engineer execution; ~10 days under
two-engineer with A‖B1 from day 0.

**Dependency graph (revised):**

```
pipeline-integration (A, 4-5d) ─────────────────────────────────┐
                                                                 │
plugin-contract-freeze (B1, 2-3d) ──┬─→ plugin-discovery-py (C, 3-4d) ──→ reference-plugins (D, 2d)
                                    │
                                    ├─→ plugin-architecture-ts (E-spike, 1d)
                                    │
                                    └─→ plugin-spec-polish (B2, 2-3d) [parallel w/ C/D/E]
```

A and B1 are independent; ship in parallel from day 0 if capacity allows.

### 7.7 The Backstage / Envoy / OPA prior art the original analysis missed

The original §2.2 cited Fastify / Next.js / gRPC / NestJS as the synthesis
sources. Optimizer flagged three additional sources whose patterns are
specifically incorporated in this revision:

- **Backstage `catalog-info.yaml`** ([RFC 18372](https://github.com/backstage/backstage/issues/18372))
  — closest match to SOX's needs. Adopted: `apiVersion`, `kind`, `metadata`,
  `spec` envelope structure (familiar to any Kubernetes user). Adopted: schema
  version (`apiVersion: sox.dev/v1`) separate from content version.

- **Envoy filter chain + xDS protocol**
  ([API_VERSIONING.md](https://github.com/envoyproxy/envoy/blob/main/api/API_VERSIONING.md))
  — gold standard for declarative ordered middleware with cross-language
  consumers. **Not adopted:** closed phase enum (`AUTHN`/`AUTHZ`/`RATE_LIMIT`)
  — too restrictive for SOX's plugin-author flexibility. **Adopted:** the
  permanent-no-field-removal rule post-v1 (Envoy's "ecosystem coordination
  cost is too high" finding). **Adopted:** boot-time hard-reject on
  type-URL/version mismatch.

- **OPA bundles**
  ([open-policy-agent.org](https://www.openpolicyagent.org/docs/latest/management-bundles/))
  — battle-tested signed-bundle format. **Adopted:** `signatures: []`
  reserved field even in unsigned v1 (cheap to reserve, expensive to retrofit).
  **Considered but not adopted:** OPA's decision-point + policy-bundle
  separation — `kind: guard` collapsing into `kind: interceptor` (per §7.1)
  makes the OPA structure overkill for v1.

### 7.8 Open decisions for the project owner

After this revision, the following remain explicit choices the owner should
ratify before workflow-planner generates phase prompts:

1. **§7.1 — kind taxonomy collapse.** The 4-kind 2-axis split (collapsing
   Guard into Interceptor) is research-grounded but inverts the original
   §2.1 proposal. Owner decision: ratify or reject.

2. **§7.2 — entry point out of manifest body.** Language-specific loader
   hints live in `pyproject.toml` / `package.json`, not in `sox-plugin.yaml`.
   This is the "genuinely language-neutral" choice but requires plugin
   authors to maintain two files. Owner decision: ratify or accept the
   single-file alternative (less neutral, simpler authoring).

3. **§7.3 — PEP 440 wire form.** `>=1.0,<2.0` is parseable by both Python
   and Node libraries with light translation. The alternative is npm-style
   `^1.0.0`, which is *more* idiomatic for TS plugin authors but requires a
   PEP 440 → npm-semver translation in Python. Owner decision: pick one
   canonical wire form.

4. **§7.5 risk #6 — `sox.yaml` descope.** Env-vars-only for v1 is shipped
   advice from optimizer; some plugin authors will want a config file. Owner
   decision: env-vars-only OR add `sox.yaml` schema to B1 scope (adds ~1d).

5. **§7.6 — `plugin-architecture-ts` reduces from 1w to 1d.** Contentious
   per optimizer; owner originally said "Mirror Python design in TS SDK
   before TS code lands" but the spike satisfies the contract-freeze goal
   without the runtime port. Owner decision: ratify spike or restore full
   port.

6. **§7.5 risk #2 — failure semantics defaults.** Hook exceptions swallowed
   vs surfaced as fail-closed. The proposal is "swallow + log" because hooks
   are observation-only by spec. Owner decision: ratify or pick fail-closed.

### 7.9 What this revision did NOT change

- Core diagnosis (§1) — still correct: framework exists, no transport uses it,
  harness substitutes for missing layer.
- Pipeline contract semantics (`(ctx, next) -> response`) — unchanged.
- Continuation-passing style — unchanged.
- Performance / concurrency / HookDispatcher decisions in §5 — unchanged.
- The harness-substitution-deletion as the highest-symbolic milestone —
  unchanged, just relocated to `pipeline-integration` phase 06.

The original §§0–6 remain readable as "first-pass thinking"; §7 is the
authoritative current decision set. workflow-planner will generate phase
prompts from §7's revised engagement decomposition.
