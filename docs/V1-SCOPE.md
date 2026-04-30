<!-- SPDX-License-Identifier: Apache-2.0 -->
# SOX Protocol — v1 Scope Reference

**Status:** Authoritative
**Source:** `spec/` (this document summarises; `spec/` wins on conflict)
**Last updated:** 2026-04-30

---

## Protocol operations (8 tools)

| Tool | Status | Brief |
|---|---|---|
| `{{send_tool}}` | v1 MUST | Append a message to a named channel. Non-blocking. Returns `{sent_at, message_id, seq, backpressure}`. Supports `reply_to` for threading and `idempotency_key` for dedup (24h TTL default). |
| `{{recv_tool}}` | v1 MUST | Drain the calling agent's mailbox. Non-blocking. Returns messages in ascending `seq` order per channel. Supports `thread_depth` (0/n/-1) for inline ancestor expansion and `include_meta` for observability metadata toggle. |
| `{{subscribe_tool}}` | v1 MUST | Register interest in channels matching a glob pattern. Persists across server restarts. Idempotent. Cannot glob-match reserved prefixes `dm/` or `group/`. |
| `{{list_tool}}` | v1 MUST | Discover active channels. Returns the mandatory `_sox_protocol` version negotiation block (`server_version`, `supported_versions`, `min_client_version`). Clients MUST read this on first call and fail-fast on version mismatch. |
| `channels__ack` | v1 MUST | Signal ACK/NACK for a received message. Control-plane only: does NOT enter channel history, does NOT consume a `seq` slot. Updates server-side pending-state record. Statuses: `received → processing → done | nack`. |
| `channels__heartbeat` | v1 MUST | Update the server-side liveness record for the calling agent. Control-plane only. Status: `online | busy | offline`. Server derives `stale` (30s) and `offline` (90s) from timeout. Triggers events on `sox/presence`. |
| `replay` | v1 MUST | Replay historical messages from a channel using a per-channel `seq` cursor. Parameters: `channel`, `since` (seq), `until` (seq or null), `limit`. Access gated by `replay_policy` (default: `subscriber`). Paginates via `has_more`. |
| `channels__collect` | planned | Server-side fan-in aggregation: block until `count` ACKs/replies arrive for a broadcast `reply_to` message, or `timeout` seconds elapse. Returns `{received[], missing[], timed_out}`. See post-v1 section. |

---

## Wire envelope

Every message stored and returned by SOX has this shape:

| Field | Type | Assigned by | Notes |
|---|---|---|---|
| `channel` | string | Sender (input) | Target channel name |
| `sender` | string | Server | Server-certified from verified connection identity; NOT self-reported |
| `body` | object | Sender (input) | Opaque JSON payload |
| `correlation_id` | string or null | Sender (input) | Caller-supplied; echoed verbatim |
| `sent_at` | number | Server | Unix epoch seconds (float); retained for backward compat |
| `message_id` | string | Server | Backing-store-assigned unique ID |
| `seq` | integer ≥ 1 | Server | Per-channel monotone counter; authoritative ordering key; replay cursor |
| `ts` | integer or null | Server | Nanosecond monotonic timestamp; advisory cross-channel tiebreaker; NOT globally total-ordered |
| `reply_to` | string or null | Sender (input) | `message_id` of parent message; null if not a reply; used for threading and deadlock wait-graph |
| `delivered_to` | string[] or null | Server | Agent IDs that have `recv`'d this message; used for deadlock detection (SHOULD-implement) |
| `origin_server` | string or null | Server | Always `null` in v1.0 single-server; populated in federated v2 |

### Observability extension `_meta`

Present on `recv` responses when `include_meta: true` (default):

```json
{
  "_meta": {
    "trace_id": "<string>",
    "middleware_timings": ["<middleware_name:Nms>"],
    "server_node_id": "<string>"
  }
}
```

Absent when `include_meta: false`. Per-request flag overrides server-level default.

---

## Reserved channel prefixes

| Prefix | Purpose | Enforcement |
|---|---|---|
| `dm/` | Direct messages (`dm/<sorted-pair>` using `~` separator) | Server-enforced two-party; wildcard glob blocked |
| `group/` | Managed group channels | Server-enforced membership table; lifecycle verbs required |
| `sox/` | Server-emitted derived channels (`sox/presence`, `sox/acks`) | Agents cannot write; server-emitted only |

---

## Key architecture decisions

| Concern | Decision | Spec location |
|---|---|---|
| Identity primitive | Ed25519 keypair (reference impl); spec describes guarantee only: server-certified `sender` | `spec/ports/identity.md`, `docs/adr/0002` |
| Extensibility | Middleware-primary hybrid; hooks are observation-only sugar; normative default chain order | `spec/ports/middleware.md`, `docs/adr/0003` |
| DM routing | `dm/<sorted-pair>` naming, `~` separator, server-enforced two-party constraint | `spec/primitives/dms.md`, `docs/decisions/dm-semantics.md` |
| Groups model | Managed channels under `group/<id>` with server membership table; lifecycle verbs | `spec/primitives/groups.md`, `docs/decisions/groups-model.md` |
| ACK/NACK | Dedicated `channels__ack` tool; control-plane only; no channel history; `sox/acks` for audit | `spec/primitives/ack-nack.md`, `docs/decisions/ack-mechanism.md` |
| Sequence numbers | Per-channel monotone `seq` (starts at 1); advisory `ts` for cross-channel display | `spec/primitives/sequence-numbers.md`, `docs/decisions/seq-ordering-scope.md` |
| Presence/heartbeat | Dedicated `channels__heartbeat` tool; `sox/presence` derived channel for observers | `spec/primitives/presence.md`, `docs/decisions/heartbeat-mechanism.md` |
| Backpressure | Advisory by default; per-channel `enforced` opt-in; `backpressure` object always in send output | `spec/primitives/channels.md`, `docs/decisions/backpressure-model.md` |
| Replay access | Per-channel `replay_policy`: `subscriber` (default) / `admin_only` / `custom` | `spec/primitives/channels.md`, `docs/decisions/replay-access-control.md` |
| Namespaces | Store-level enforcement; `shared` or `isolated` mode; `namespace_resolver` middleware required | `spec/primitives/namespace.md`, `docs/decisions/namespace-isolation-layer.md` |
| Schema validation | Registry in backing store (`get/set_channel_schema`); enforcement in `schema_validator` middleware (default-on) | `spec/ports/middleware.md`, `docs/decisions/schema-validation-layer.md` |
| Idempotency | `idempotency_key` on send; 24h default TTL; `sweep_idempotency_cache` mandatory on store | `spec/ports/backing-store.md`, `docs/decisions/idempotency-ttl.md` |
| Version negotiation | `_sox_protocol` block in `list_channels` output; no separate negotiation tool | `spec/operations/list_channels.output.schema.json`, `docs/decisions/version-negotiation-mechanism.md` |
| Deadlock detection | Wait-graph computed from `reply_to` + `delivered_to` at query time (SHOULD-implement) | `spec/protocol.md`, `docs/decisions/deadlock-detection-approach.md` |
| Federation | Out of v1 implementation; spec is federation-aware: `origin_server` slot, `<server-id>/<agent-id>` form, per-channel `seq` | `spec/ports/identity.md`, `spec/protocol.md`, `docs/decisions/federation-scope.md` |
| Threading | `reply_to` on envelope; `thread_depth` on `recv` (0/n/-1); server-side ancestor walk | `spec/primitives/threads.md`, `docs/decisions/threading-depth.md` |
| Fan-out | Send to `group/<id>` channel IS the fan-out primitive; no separate verb | `spec/primitives/groups.md`, `docs/decisions/fanout-collect.md` |
| Admin API | Co-located but opt-in (`--admin` flag); not registered in default server mode | `docs/decisions/admin-api-colocation.md` |
| TUI connection | Stdio subprocess; TUI is an MCP client like any agent | `docs/decisions/tui-connection-model.md` |
| Web app | Static SPA (Vite+React); bundled into Python wheel; HTTP transport serves `/ui/` | `docs/decisions/webapp-deployment-model.md` |

---

## Middleware default chain (normative order)

```
namespace_resolver → auth → rate_limit → schema_validator → idempotency → store_dispatch → audit_log
```

Each link is independently removable. Removing `namespace_resolver` or `auth` is a security misconfiguration. `schema_validator` is default-on; operators may disable it with documented risk.

---

## Port contract summary

| Port | Key requirements for implementers |
|---|---|
| `BackingStore` | All ops parameterised by `namespace`. Per-channel atomic `seq` increment. `get/set_channel_schema`. `sweep_idempotency_cache` (mandatory). Range queries by `seq` for replay. Ancestor-walk for thread depth. Two isolation modes: `shared` (WHERE clause) or `isolated` (separate schema/file). |
| `Transport` | HTTP binding: CORS preflight + configurable origin allow-list (localhost default). Long-poll or SSE for `channels__collect`. Stdio binding: asyncio blocking satisfies collect. TLS for remote store connections. |
| `Identity` | Server-certifies `sender` on every `send`; client does not supply it. Connection-time binding. Verified `agent_id` injected into context by `auth` middleware. Reference impl: Ed25519 (ADR 0002). |
| `Middleware` | Normative default chain order. `schema_validator` default-on. `namespace_resolver` mandatory. Each link declares `must_run_after`/`must_run_before` constraints validated at startup. |

---

## Post-v1 (explicitly deferred)

- **`channels__collect`** — schema exists (`x-status: planned`); implementation deferred. Open questions: quorum semantics (ACKs vs. any reply vs. configurable `status_filter`), cancel verb, multiple-collector semantics. Transport requires long-poll/SSE for HTTP; stdio satisfies via asyncio blocking.
- **Cryptographic DM confidentiality** — end-to-end encryption using Ed25519 keypairs (ADR 0002 enables key derivation; envelope spec deferred).
- **Signed messages** — per-message server signature for recipient-side provenance verification.
- **Channel ACLs** — restricting send/subscribe by verified `agent_id`.
- **Credential rotation** — keypair rotation without identity or history loss.
- **Member roles in groups** — owner/admin/member/observer; middleware/hook layer concern.
- **Namespace deletion** — create-only in v1; eviction protocol deferred.
- **`waiting_on` index in backing store** — optional v1.x upgrade for O(1) deadlock detection; v1 uses O(n) query-time traversal.
- **NACK reason code taxonomy** — free text in v1; standard codes deferred to enforcer design doc.
- **Federation implementation** — spec is federation-aware (slots reserved); no federation code in v1.
- **`sox/presence` subscription ACL** — any authenticated agent may subscribe in v1; observer role deferred.
- **Per-channel `thread_depth` config default** — defer to channel-config pass.
- **Schema evolution** — versioned schemas with migration semantics deferred.
- **`channels__negotiate` tool** — version negotiation via `list_channels` is sufficient for v1; dedicated tool deferred.
