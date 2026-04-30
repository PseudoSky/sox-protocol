# SOX Protocol — backlog

## 🔴 agent identity verification (top priority)

The entire trust model rests on `agent_id` being an env var string any process can set to anything. `send()` accepts whatever `sender` the server passes with no verification. All threading, pending tracking, enforcer logic, and ACLs are only as trustworthy as the identity claim.

- [ ] **Per-agent credential registry** — each agent registered with a `SOX_AGENT_SECRET` alongside `SOX_AGENT_ID`; the MCP server maintains a credential store; `send()` and all mutating operations are rejected if the secret does not match the claimed id; minimum viable fix with no protocol changes
- [ ] **Identity bound at connection, not claimed by client** — server assigns identity from a credential presented at startup rather than trusting `SOX_AGENT_ID`; agent never gets to name itself; credential options: shared secret, asymmetric keypair, or server-issued token
- [ ] **Signed messages** — server signs each persisted message with a per-agent key stored in the credential registry; `recv()` includes the signature; recipients can verify provenance independently without trusting the server's honesty
- [ ] **Channel ACLs backed on verified identity** — restrict which verified agent IDs can send to or subscribe to which channels; impersonation becomes useless even if credentials are bypassed, because the impersonated agent's channels are locked
- [ ] **Identity verification as middleware** — implement as the first middleware in the chain so all four tools (send, recv, subscribe, list_channels) go through identity check before any backing store access; unverified callers are rejected before touching data
- [ ] **Credential rotation** — agents can rotate their secret without losing their identity or message history; old credential has a configurable grace period before rejection
- [ ] **Audit log for identity failures** — every rejected send/recv due to identity mismatch is written to a tamper-evident log with timestamp, claimed agent_id, and operation; surfaced in the admin API
- [ ] **Q (architect):** What is the right credential primitive — shared secret (simple, no PKI required), asymmetric keypair (strong, verifiable by recipients without server involvement), or server-issued JWT (flexible, short-lived, revocable)? For the Claude Code runtime where agents are subprocesses, shared secret per agent in `.mcp.json` env is the lowest-friction path; keypairs are stronger but require key management tooling.

## recv / inbox

- [ ] Self-send exclusion — agents currently receive their own sent messages; filter `sender == agent_id` in `recv()` and `watch()`
- [ ] `since` parameter on `recv()` — accept a Unix timestamp so agents resuming after a pause skip stale messages without re-draining
- [ ] TTL / message expiry — `max_age_seconds` filter on `recv()` using the existing `sent_at` column (no schema change needed); optional per-message `ttl_seconds` column for hard expiry
- [ ] Inbox clear — explicit `flush_inbox(agent_id)` operation to mark all pending messages delivered without returning them

## discovery

- [ ] `list_agents` tool — return `[{agent_id, channels}]` from the subscriptions table; no schema change needed; enables peer discovery before sending
- [ ] Agent can list groups (channels) they belong to — `list_channels(agent_id=self)` filter showing only channels the calling agent is subscribed to
- [ ] Agent can request another agent to join a group — send an invite message with a standard envelope (`type: "sox/invite"`, `channel`) that the receiving agent can act on; convention over forced server-side subscription

## threading

- [ ] `reply_to` field on send — store parent `message_id` so replies form a chain; backed by a new nullable `reply_to` column
- [ ] Filter recv by `reply_to` and `sender` — `recv(reply_to="msg-123", sender="agent-X")` for precise answer retrieval; enables structured Q&A without full inbox scan
- [ ] `list_pending` tool — returns both sides of unresolved threads: `awaiting_reply` (sent by me, no reply yet) and `unreplied` (received by me, I haven't replied); fully computable from `reply_to` + `delivered_to`, no new schema
- [ ] Thread hydration on recv — walk `reply_to` chain to root and include ancestors inline as `thread: [...]`; agent gets full conversation context in one call without relying on context window continuity or separate lookups
  - **Q (architect):** What is better for agent context continuity — including the full ancestor thread inline on every message, returning only the immediate `reply_to` message ID so the agent can page back on demand, or supporting both via a `thread_depth` parameter (0 = ID only, n = n levels, -1 = full chain)? Suspected answer: support both — full thread for short chains and recovery scenarios, ID-only for high-volume channels where hydrating every message would bloat context.
- [ ] Auto-prioritize `recv()` — unreplied directs first, then awaiting-reply context, then general inbox; server-side, no agent logic needed
- [ ] Enforcer uses `unreplied` as stop signal — block stop when `unreplied` is non-empty instead of the coarser "any unread message" check

## middleware / hooks / auth

- [ ] Evaluate whether to build a middleware adapter layer, a hooks system, or pluggable auth — or some combination
  - A middleware layer (request/response pipeline) is the most general: every tool call passes through a chain of middleware that can inspect, mutate, block, or enrich it
  - A hooks system (pre/post tool call events) is lighter and familiar from the Claude Code runtime adapter — lower overhead, easier to reason about, less power
  - Pluggable auth is a specific capability (verify caller identity, check permissions before a tool executes) that could be built on top of either
  - **Preferred direction:** if auth can be modeled as a capability of hooks or middleware rather than a first-class layer, that is the right design — auth becomes one hook/middleware implementation rather than a separate port; the system gains extensibility for free (logging, rate limiting, audit trails, token metering all follow the same pattern)
  - **Q (architect):** Can all auth requirements (identity verification, channel-level ACLs, per-agent rate limits) be expressed as middleware or hook implementations, or is there a case where auth must be a first-class port? If middleware, what is the minimal interface a middleware unit must implement (inspect only vs. mutate vs. short-circuit)?

## transport adapter layer

- [ ] Define `spec/ports/transport.md` — transport port interface following the same structure as `BackingStore`; defines start/stop contract and what a conformant transport must expose
- [ ] Standardize transport env vars across all implementations — `SOX_MCP_TRANSPORT` (stdio|http), `SOX_HTTP_HOST`, `SOX_HTTP_PORT`; mandatory stdio, optional http
- [ ] Refactor Python server to satisfy the transport port — `adapters/transports/stdio/` and `adapters/transports/http/` wrapping FastMCP, selected by `_build_transport()` the same way `_build_store()` dispatches backing stores
- [ ] Add transport conformance tests to the harness — a conformant transport must pass the same tests regardless of implementation language
- [ ] Document that a Rust (or other language) implementation must satisfy the transport port, not just use whatever MCP library is convenient; stdio is the drop-in replacement guarantee

## presence / heartbeat

- [ ] Agent heartbeat — periodic lightweight ping written to the backing store so peers can distinguish a live subscribed agent from a dead one; `list_agents` should surface last_seen_at
- [ ] Presence-aware recv — optionally skip sending to or waiting on agents whose last heartbeat exceeds a configurable staleness threshold; prevents indefinite waits on dead peers
- [ ] **Q (architect):** Should heartbeat be a dedicated SOX tool (`channels__heartbeat`) or a convention on a reserved system channel (e.g. `sox/presence`)? Dedicated tool is explicit and measurable; reserved channel reuses existing primitives but adds noise to channel listings

## direct messages

- [ ] First-class DM primitive — `send(to=agent_id, ...)` addressing without requiring a manually named channel; server routes to a reserved `dm:<sender>:<recipient>` channel internally
- [ ] `recv()` surfaces DMs separately from channel messages — agents should not have to scan channel traffic to find messages addressed specifically to them
- [ ] **Q (architect):** Is a DM just a channel with a naming convention enforced server-side, or does it warrant a distinct message type with different delivery semantics (e.g. exactly-once, no wildcard subscription)?

## ACK / processing signal

- [ ] Explicit ACK signal — a lightweight `channels__ack(message_id)` tool that marks a message as accepted-and-in-progress; distinct from delivery (drained from inbox) and reply (work complete); bridges the gap between "peer read it" and "peer replied"
- [ ] `list_pending` surfaces ACK state — `awaiting_reply` entries show `status: unread | acked | replied | nacked` so senders can distinguish in-progress work from silence
- [ ] ACK clears the enforcer's stop-block — an agent that has ACKed a message is committed to replying; the enforcer should allow stop only after reply or NACK, not just ACK
- [ ] **Q (architect):** Should ACK be a dedicated tool or a reserved `body` envelope shape (`type: "sox/ack"`) sent via the normal `channels__send`? A dedicated tool is lower token cost and explicit in the spec; a reserved envelope reuses existing primitives but costs a full send round-trip and adds a message to the thread.

## error / NACK

- [ ] Standard error envelope — a reserved `body` shape (`type: "sox/error"`, `code`, `message`, `reply_to`) so agents can signal "cannot handle" without free-form text; part of the spec, not convention
- [ ] `list_pending` surfaces NACKs — a NACK on a sent message should close the awaiting_reply entry so the sender doesn't wait indefinitely
- [ ] Enforcer awareness — a NACK on an unreplied message should clear it from the unreplied list; agents should not be blocked on stop for messages they explicitly rejected

## fan-out / collect

- [ ] `broadcast_and_collect` pattern — send to a channel and gather replies up to a quorum count or timeout; returns `{replies: [...], timed_out: bool}`
- [ ] **Q (architect):** Should fan-out/collect be a first-class tool or a higher-level SDK convenience built on send + recv? A tool gives atomicity guarantees the SDK cannot; the SDK is simpler to spec and implement. Consider whether the backing store needs any new primitives to support a quorum query efficiently.

## backpressure

- [ ] Inbox depth signal — `list_agents` or a dedicated `inbox_depth` tool returns how many undelivered messages are queued for each agent; senders can check before flooding a slow peer
- [ ] Configurable inbox limit — optional per-agent cap on undelivered message count; send returns a `backpressure: true` flag when the recipient is at capacity rather than silently enqueuing
- [ ] **Q (architect):** Should backpressure be advisory (flag on send response) or enforced (send blocks / errors when recipient is over limit)? Enforced is safer but changes the non-blocking guarantee that is central to SOX's design.

## client SDK

- [ ] Higher-level Python client wrapping the four MCP tools — `ask_and_wait(channel, body, timeout)`, `broadcast(channel, body)`, `reply(message_id, body)`, `drain()` — reduces discipline burden and makes common patterns one-liners
- [ ] SDK handles reply_to threading automatically — `ask_and_wait` sets `reply_to` on the response and polls `recv(reply_to=...)` internally; callers never touch message IDs directly
- [ ] SDK tracks pending questions in-process — maintains an in-memory registry of sent message IDs and their status so agents don't rely on context window for this

## channel lifecycle

- [ ] Explicit channel create — optional metadata (owner, description, created_at, max_message_age); channels without explicit create remain implicitly created on first send
- [ ] Channel delete / archive — marks a channel inactive; future sends return an error; existing messages remain queryable
- [ ] Channel listing shows lifecycle state — `list_channels` returns `status: active | archived` so agents know before sending

## typed channels / schema validation

- [ ] Channel schema registry — optional JSON Schema registered per channel; the backing store validates `body` against it on send and rejects non-conformant messages
- [ ] `register_schema(channel, json_schema)` tool — idempotent; schema version stored alongside channel metadata
- [ ] **Q (architect):** Should schema validation be enforced at the backing store layer (all implementations must validate) or the middleware layer (validation is a middleware plugin)? Middleware is more flexible; backing store enforcement gives cross-language consistency guarantees.

## distributed tracing

- [ ] Conversation trace ID — a `trace_id` field on every message that flows through an entire multi-agent exchange unchanged; distinct from `correlation_id` (per-request) and `reply_to` (per-thread); set by the originating agent, propagated automatically by the SDK on replies
- [ ] `list_channels` and `list_pending` filterable by `trace_id` — operators can pull a full conversation graph for a single trace
- [ ] Tracing adapter — optional middleware that emits OpenTelemetry spans per send/recv using `trace_id` as the trace root; no-op if OTel not configured

## observability

- [ ] Static token floor benchmark — tokenize the four tool schemas + one empty send/recv cycle (`body: {}`, `messages: []`) using `anthropic.count_tokens`; publish as a reference cost table in docs so operators know the irreducible per-loop overhead
- [ ] Runtime envelope annotation — each tool response includes `_sox_meta: {envelope_tokens: N}` where N is the token count of the response with `body` fields replaced by a fixed-size stub; lets agents and operators accumulate per-call protocol cost separately from message content cost
  - **Q (architect):** Should `_sox_meta` be opt-in (via a request flag) or always present? Always-present is simpler but adds a small fixed overhead to every response; opt-in avoids that but requires callers to remember to ask.
- [ ] Synthetic benchmark harness — run N send/recv cycles via the Anthropic API with `body: {}`, measure total input+output tokens, subtract a no-SOX baseline (same prompt, no tools registered); produces a "protocol cost per loop" number for the docs and for regression testing across versions

## idempotent send / deduplication

- [ ] Caller-supplied idempotency key on `channels__send` — if a message with the same key already exists in the backing store, return the original `message_id` and `sent_at` without inserting a duplicate; makes send safe to retry after timeout or crash
- [ ] Idempotency key stored in a dedicated column with a unique index — fast lookup, no full-table scan on every send
- [ ] **Q (architect):** What is the right TTL for idempotency key retention? Keeping keys forever prevents all duplicates but grows the table unboundedly; a rolling window (e.g. 24h) covers practical retry windows without unbounded growth

## multi-server / federation

- [ ] Define federation model in spec — how do two SOX server instances share a channel namespace? Options: shared backing store (simplest, SQLite → Postgres), gossip/replication, or a dedicated federation broker
- [ ] Backing store port extended for remote stores — `PostgresStore` adapter as the natural path to multi-process deployments; SQLite remains the single-node default
- [ ] **Q (architect):** Is federation in scope for v1 or a post-v1 concern? The backing store adapter layer already isolates the change surface — a Postgres adapter could be added without touching the spec. But the channel namespace and agent identity model need to be federation-aware from the start or retrofitting will be painful.

## message ordering

- [ ] Logical clock / sequence number — a monotonically increasing `seq` per channel assigned by the server on insert; gives deterministic ordering within a channel independent of sender wall clock
- [ ] Thread ordering guarantee — messages within a `reply_to` chain are always returned in `seq` order regardless of `sent_at` skew
- [ ] **Q (architect):** Should `seq` be global (across all channels, simple counter) or per-channel (resets per channel, cheaper at scale)? Global gives total ordering across channels; per-channel gives partial ordering but is more scalable and avoids a hot global counter

## replay / audit log

- [ ] `channels__replay(channel, from_seq, to_seq)` tool — returns all messages in a channel between two sequence numbers regardless of delivery state; read-only, does not affect `delivered_to`
- [ ] Replay filterable by `trace_id`, `sender`, and time range — enables full conversation reconstruction for debugging and post-mortems
- [ ] Replay access control — **Q (architect):** should replay be gated by the same auth/middleware as recv, or is it a separate capability (e.g. only admin agents can replay)?

## channel namespacing / tenant isolation

- [ ] Namespace prefix enforcement — optional server-side config that restricts agents to channels within a declared namespace (e.g. `team-a/*`); cross-namespace sends are rejected
- [ ] Namespace isolation in `list_channels` and `list_agents` — agents only see channels and peers within their namespace unless explicitly granted cross-namespace access
- [ ] **Q (architect):** Should namespaces be a backing store concept (separate tables or databases per namespace) or a middleware enforcement layer (single store, filtered queries)? Separate stores give hard isolation; middleware is simpler to operate but relies on correct filter application everywhere

## rate limiting

- [ ] Per-agent send rate limit — configurable max messages per second per agent; excess sends return a `rate_limited: true` flag rather than blocking or erroring (preserves non-blocking guarantee)
- [ ] Per-channel rate limit — channel-level cap to prevent any single channel from being flooded regardless of which agent is sending
- [ ] Rate limit state in `list_agents` — surface current send rate and limit so operators and agents can observe pressure before it becomes a problem
- [ ] Natural home is middleware — rate limiting should be implementable as a middleware plugin rather than baked into the backing store or tools directly

## admin / management API

- [ ] Admin tool set (separate from agent tools) — `admin__list_agents`, `admin__drain_agent(agent_id)`, `admin__delete_channel(channel)`, `admin__vacuum`; gated by an admin capability so normal agents cannot call them
- [ ] Stale subscription cleanup — automatically or on-demand remove subscriptions for agents whose last heartbeat exceeds a threshold
- [ ] Admin API surfaced via the same MCP server or a separate process — **Q (architect):** co-locating admin tools in the same server is operationally simpler; a separate admin process avoids any risk of agents calling admin tools even with ACL in place

## test harness for agent authors

- [ ] Mock SOX server — in-process test double that implements the full MCP tool surface; no subprocess, no SQLite; lets agent authors write unit tests without spinning up infrastructure
- [ ] Conversation fixture format — a declarative format for scripting a multi-agent exchange (agent A sends X, agent B receives Y, assert Z); playable against real or mock server
- [ ] Assertion helpers — `assert_received(agent_id, channel, body_matcher)`, `assert_pending(agent_id)`, `assert_no_unreplied(agent_id)`; composable with pytest or any test framework

## graceful degradation

- [ ] Circuit breaker on backing store — if the store is unavailable, tools return a structured `{"error": "backing_store_unavailable", "retryable": true}` rather than an unhandled exception; agents can decide to wait and retry
- [ ] In-memory send buffer — when the backing store is unavailable, `channels__send` optionally buffers to an in-memory queue and flushes on reconnect; configurable max buffer size
- [ ] Health check tool — `channels__health` returns backing store status, listener queue depth, and last successful operation timestamp; agents and operators can poll before committing to a long operation

## reference agent

- [ ] Canonical reference agent implementation — a fully-annotated example agent that demonstrates: subscribing on startup, the recv loop, reply threading, ACK/NACK, graceful stop with unreplied check, and heartbeat; runnable as a Claude Code agent or standalone script
- [ ] Reference agent covers recovery — shows how to use `list_pending` and replay to reconstruct state after a context reset or restart
- [ ] Published in `examples/reference-agent/` alongside the existing two-agent demo

## groups (first-class, distinct from channels)

Channels are an open broadcast bus — anyone can subscribe, there is no roster, no ownership, no membership enforcement. Groups are a bounded named set of agents with explicit membership, an owner, and the ability to address all members as a unit. Currently approximated by channel naming conventions with no enforcement.

- [ ] `channels__create_group(name, members)` — creates a named group with an explicit member list and an owning agent; group names live in a separate namespace from channels to avoid collision
- [ ] `channels__join_group(group_id)` / `channels__leave_group(group_id)` — membership operations; join requires either an invite token or owner approval depending on group policy; leave is always permitted
- [ ] `channels__send` extended to accept `group_id` as an alternative to `channel` — message is delivered to all current members of the group; membership is resolved at send time so late-joining members do not receive prior messages by default
- [ ] `channels__list_groups` — returns groups the calling agent belongs to with member roster, owner, and creation time; distinct from `list_channels`
- [ ] `channels__group_members(group_id)` — returns current member list with presence and pending state per member
- [ ] Group invite flow — owner sends an invite (standard `sox/invite` envelope already in discovery TODO); invitee calls `join_group` with the invite token; uninvited agents cannot join a closed group
- [ ] Group admin operations — owner can add/remove members, transfer ownership, set group policy (open vs invite-only, require ACK from all before thread closes)
- [ ] Group message history — `recv` and `replay` work on groups the same as channels; a group is backed by an internal channel that only members can subscribe to
- [ ] Group presence — `list_agents` filterable by group; group panel in the chat UI shows member roster with live presence indicators
- [ ] **Q (architect):** Is a group best modeled as a managed channel (server creates and owns the backing channel, enforces membership on send/subscribe) or as a first-class entity with its own table and separate delivery semantics? Managed channel reuses the existing message path; a separate entity is more flexible but doubles the delivery surface to maintain.

## unsubscribe

- [ ] `channels__unsubscribe(pattern)` tool — removes a subscription from the backing store; agent stops receiving messages on matching channels; idempotent (unsubscribing from a non-existent pattern is a no-op)
- [ ] Unsubscribe cleans up pending messages — messages already buffered in the listener queue for that pattern are discarded on unsubscribe; messages already in `delivered_to` are unaffected
- [ ] Subscription expiry — optional `ttl_seconds` on `channels__subscribe` so agents can register a temporary listener that auto-expires without an explicit unsubscribe call

## deadlock detection

- [ ] Cycle detection in `list_pending` — when computing `awaiting_reply`, detect if agent A is waiting on B and B is waiting on A (or any longer cycle); surface as `deadlock: [{agent_id, waiting_on_message_id}, ...]` in the response
- [ ] Enforcer deadlock signal — if the enforcer detects a deadlock on stop, emit a warning rather than blocking indefinitely; the agent can then decide to NACK its pending messages and break the cycle
- [ ] **Q (architect):** Deadlock detection across agents requires the server to know who is waiting on whom — this means `list_pending` state must be server-authoritative, not derived on-the-fly. Does this warrant a dedicated `waiting_on` column in the backing store, or is it computable from `reply_to` + `delivered_to` at query time?

## pagination

- [ ] Cursor-based pagination on `recv()` — `recv(cursor=<opaque_token>, max_messages=50)` returns the next page of undelivered messages and a `next_cursor`; agents can page through large backlogs without losing position
- [ ] Cursor-based pagination on `channels__replay` — same pattern for audit log queries
- [ ] `inbox_depth(agent_id)` — returns total count of undelivered messages so agents can decide how aggressively to paginate before starting work

## JS / TS client SDK

- [ ] TypeScript SDK wrapping the four MCP tools — `send()`, `recv()`, `subscribe()`, `listChannels()`; typed request/response shapes generated from the spec JSON schemas
- [ ] TS SDK includes higher-level helpers — `askAndWait(channel, body, timeout)`, `reply(messageId, body)`, `drain()`, `listPending()`
- [ ] Published as `@sox-protocol/client` on npm alongside the Python package on PyPI
- [ ] Claude Code skill updated to reference the TS SDK for JS/TS agent authors

## protocol versioning

- [ ] Formal version negotiation on connection — client declares supported protocol versions; server responds with the version it will use; mismatch results in a structured error not a silent failure
- [ ] Deprecation policy in spec — fields marked `@deprecated(since="X.Y")` continue to be returned for N minor versions; removal only on major version bump
- [ ] Changelog and migration guide per version — automated diff between schema versions surfaced in docs; breaking changes flagged explicitly
- [ ] **Q (architect):** Should version negotiation be a dedicated handshake tool (`channels__negotiate`) or embedded in the `list_channels` response which is already the conventional first call? Embedding avoids an extra round-trip but couples discovery and negotiation.

## CLI tooling

- [ ] `sox` CLI — `sox send <channel> <json-body>`, `sox recv <agent-id>`, `sox list-agents`, `sox list-channels`, `sox drain <agent-id>`, `sox replay <channel>`; wraps the Python client for operator use without writing code
- [ ] `sox monitor` — live tail of all messages on a channel or across all channels; useful for debugging multi-agent exchanges in real time
- [ ] `sox health` — prints backing store status, connected agents, queue depths; single command for operator triage
- [ ] Installable as `pipx install sox-protocol` alongside the library

## SOX chat UI (TUI + web app)

A full interactive interface for SOX — both for operators debugging live agent conversations and as a showpiece demo of the protocol. Dogfoods every feature in this list: channels, threads, agents, presence, pending, ACK/NACK.

### TUI (`sox chat` — terminal, no browser needed)

- [ ] Channel browser pane — list all channels with subscriber counts and unread indicators; arrow keys to select, enter to open
- [ ] Message feed pane — live-tailing the selected channel via `watch()`; new messages appear in real time; threads collapsed by default, expand with enter
- [ ] Thread view — expand a message to see its full `reply_to` chain inline; show ACK/NACK/pending state per message
- [ ] Agent roster pane — list connected agents with presence indicator (live / stale / unknown) and unread DM count
- [ ] Compose bar — type and send messages on the current channel; `/reply <message_id>` to thread; `/dm <agent_id>` for direct messages
- [ ] Built with `textual` (Python) — ships as `sox chat` subcommand; no external dependencies beyond the SOX package
- [ ] **Q (architect):** Should the TUI connect to the MCP server over stdio (spawning a subprocess) or talk directly to the backing store? Direct store access is simpler for a local tool; subprocess keeps the same code path as agents and catches more bugs

### Web app (`sox-ui`)

- [ ] React + TypeScript frontend using the TS SDK (`@sox-protocol/client`) — connects to a local SOX HTTP transport instance
- [ ] Channel sidebar — browsable channel list with live unread counts; click to open; search/filter bar
- [ ] Message thread view — full conversation threads with reply chains rendered as nested bubbles; sender identity badge; ACK/NACK/pending status icons
- [ ] Agent panel — roster of known agents, presence dot, last seen timestamp, pending message counts; click to open DM thread
- [ ] Live updates via `watch()` — no polling; messages appear instantly as agents send them
- [ ] Conversation graph view — optional force-directed graph showing agents as nodes and messages as edges; `trace_id` highlighted as a subgraph; useful for visualizing complex multi-agent coordination
- [ ] Replay mode — scrub through a channel's history using the replay API; pause/play; useful for post-mortems
- [ ] Shipped as `sox-protocol/packages/ui`; launchable via `sox ui` CLI subcommand which starts the HTTP transport and opens the browser
- [ ] **Q (architect):** Should the web app be a static build that talks directly to the SOX HTTP endpoint, or a thin Node server that proxies? Static is simpler to ship; a proxy layer could add auth and avoid CORS issues

## cold start / bootstrap

- [ ] Formalize the agent bootstrap sequence in the spec — subscribe → list_agents → list_pending → drain unreplied → begin work loop; each step's purpose and expected output documented
- [ ] Bootstrap helper in the SDK — `await sox.bootstrap()` executes the full sequence and returns a structured startup context `{peers, pending, unreplied}`; agents start with full situational awareness in one call
- [ ] Bootstrap covered in the reference agent and skill — the discipline doc references the bootstrap sequence; the reference agent demonstrates it end-to-end
