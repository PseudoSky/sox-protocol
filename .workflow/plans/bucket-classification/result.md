# bucket-classification — result

## Counts

| Bucket | v1 | post-v1 | deferred | Total |
|---|---|---|---|---|
| protocol | 37 | 35 | 1 | 73 |
| pitch | 6 | 5 | 0 | 11 |
| implementation | 18 | 21 | 0 | 39 |
| **Total** | **61** | **61** | **1** | **123** |

## Architect questions queue

1. **agent identity verification (top priority)** — What is the right credential primitive — shared secret (simple, no PKI required), asymmetric keypair (strong, verifiable by recipients without server involvement), or server-issued JWT (flexible, short-lived, revocable)? For the Claude Code runtime where agents are subprocesses, shared secret per agent in `.mcp.json` env is the lowest-friction path; keypairs are stronger but require key management tooling.
2. **threading** — What is better for agent context continuity — including the full ancestor thread inline on every message, returning only the immediate `reply_to` message ID so the agent can page back on demand, or supporting both via a `thread_depth` parameter (0 = ID only, n = n levels, -1 = full chain)? Suspected answer: support both — full thread for short chains and recovery scenarios, ID-only for high-volume channels where hydrating every message would bloat context.
3. **middleware / hooks / auth** — Can all auth requirements (identity verification, channel-level ACLs, per-agent rate limits) be expressed as middleware or hook implementations, or is there a case where auth must be a first-class port? If middleware, what is the minimal interface a middleware unit must implement (inspect only vs. mutate vs. short-circuit)?
4. **presence / heartbeat** — Should heartbeat be a dedicated SOX tool (`channels__heartbeat`) or a convention on a reserved system channel (e.g. `sox/presence`)? Dedicated tool is explicit and measurable; reserved channel reuses existing primitives but adds noise to channel listings
5. **direct messages** — Is a DM just a channel with a naming convention enforced server-side, or does it warrant a distinct message type with different delivery semantics (e.g. exactly-once, no wildcard subscription)?
6. **ACK / processing signal** — Should ACK be a dedicated tool or a reserved `body` envelope shape (`type: "sox/ack"`) sent via the normal `channels__send`? A dedicated tool is lower token cost and explicit in the spec; a reserved envelope reuses existing primitives but costs a full send round-trip and adds a message to the thread.
7. **fan-out / collect** — Should fan-out/collect be a first-class tool or a higher-level SDK convenience built on send + recv? A tool gives atomicity guarantees the SDK cannot; the SDK is simpler to spec and implement. Consider whether the backing store needs any new primitives to support a quorum query efficiently.
8. **backpressure** — Should backpressure be advisory (flag on send response) or enforced (send blocks / errors when recipient is over limit)? Enforced is safer but changes the non-blocking guarantee that is central to SOX's design.
9. **typed channels / schema validation** — Should schema validation be enforced at the backing store layer (all implementations must validate) or the middleware layer (validation is a middleware plugin)? Middleware is more flexible; backing store enforcement gives cross-language consistency guarantees.
10. **observability** — Should `_sox_meta` be opt-in (via a request flag) or always present? Always-present is simpler but adds a small fixed overhead to every response; opt-in avoids that but requires callers to remember to ask.
11. **idempotent send / deduplication** — What is the right TTL for idempotency key retention? Keeping keys forever prevents all duplicates but grows the table unboundedly; a rolling window (e.g. 24h) covers practical retry windows without unbounded growth
12. **multi-server / federation** — Is federation in scope for v1 or a post-v1 concern? The backing store adapter layer already isolates the change surface — a Postgres adapter could be added without touching the spec. But the channel namespace and agent identity model need to be federation-aware from the start or retrofitting will be painful.
13. **message ordering** — Should `seq` be global (across all channels, simple counter) or per-channel (resets per channel, cheaper at scale)? Global gives total ordering across channels; per-channel gives partial ordering but is more scalable and avoids a hot global counter
14. **replay / audit log** — Should replay be gated by the same auth/middleware as recv, or is it a separate capability (e.g. only admin agents can replay)?
15. **channel namespacing / tenant isolation** — Should namespaces be a backing store concept (separate tables or databases per namespace) or a middleware enforcement layer (single store, filtered queries)? Separate stores give hard isolation; middleware is simpler to operate but relies on correct filter application everywhere
16. **admin / management API** — Co-locating admin tools in the same server is operationally simpler; a separate admin process avoids any risk of agents calling admin tools even with ACL in place
17. **groups (first-class, distinct from channels)** — Is a group best modeled as a managed channel (server creates and owns the backing channel, enforces membership on send/subscribe) or as a first-class entity with its own table and separate delivery semantics? Managed channel reuses the existing message path; a separate entity is more flexible but doubles the delivery surface to maintain.
18. **deadlock detection** — Deadlock detection across agents requires the server to know who is waiting on whom — this means `list_pending` state must be server-authoritative, not derived on-the-fly. Does this warrant a dedicated `waiting_on` column in the backing store, or is it computable from `reply_to` + `delivered_to` at query time?
19. **protocol versioning** — Should version negotiation be a dedicated handshake tool (`channels__negotiate`) or embedded in the `list_channels` response which is already the conventional first call? Embedding avoids an extra round-trip but couples discovery and negotiation.
20. **SOX chat UI (TUI + web app) / TUI** — Should the TUI connect to the MCP server over stdio (spawning a subprocess) or talk directly to the backing store? Direct store access is simpler for a local tool; subprocess keeps the same code path as agents and catches more bugs
21. **SOX chat UI (TUI + web app) / Web app** — Should the web app be a static build that talks directly to the SOX HTTP endpoint, or a thin Node server that proxies? Static is simpler to ship; a proxy layer could add auth and avoid CORS issues

## Surprises and contradictions

The backlog is heavily protocol-weighted (73 of 123 items, 59%), reflecting the spec-first posture stated in the vision doc. Two surprises: (1) The 'groups' section placed 6 items in protocol-v1, which is ambitious given the vision doc explicitly flags threading/DMs/groups as "three half-coherent abstractions" needing a unification pass — these may need to be partially deferred once the addressable-destinations design pass happens. (2) Federation was classified as deferred/protocol (just the spec definition) while the Postgres adapter became post-v1/implementation; this split is intentional because the federation identity and namespace model affects v1 spec decisions even if no implementation ships until later. The pitch bucket is surprisingly lean (11 items, 9%) — much of what feels like marketing is actually protocol (the reference agent is pitch, but the bootstrap sequence formalization is protocol). The v1/post-v1 split landed exactly 50/50 at 61 each, which suggests the v1 scope may be ambitious without further triage in the groups and threading areas.

## Recommended question-resolution order

1. **Credential primitive** (identity verification section) — blocks everything else: middleware design, ACL model, audit log, and the entire identity surface. Resolve this before writing any spec sections beyond message envelopes.
2. **Middleware vs. hooks interface** (middleware / hooks / auth section) — once identity primitive is chosen, the middleware contract is the second unlock: auth, rate limiting, schema validation, tracing, and namespacing all become middleware plugins once this interface is defined.
3. **DM semantics** (direct messages section) — the DM/channel/group unification problem the vision doc flags is downstream of this decision; answering "is a DM a channel with a naming convention" resolves whether groups need a separate entity or can reuse the channel path.
4. **seq global vs. per-channel** (message ordering section) — affects the federation model, the replay tool design, and whether the Postgres adapter can be a simple drop-in; needs to be locked before spec-extraction begins.
5. **Federation in/out of v1 spec** (multi-server / federation section) — the vision doc explicitly calls this "dangerous" because identity and namespacing need to be federation-aware from the start; a "no federation in v1 spec" decision lets the team lock the identity model faster and reduces scope pressure on the groups design.
