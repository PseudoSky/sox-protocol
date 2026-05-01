<!-- SPDX-License-Identifier: Apache-2.0 -->
# Transport Port — Behaviour Contract

**Version:** 1.0  
**Status:** Normative  
**Scope:** Language-neutral. This document specifies required behaviour, not a language binding. Implementations express this contract in their own idioms.

---

## 1. Purpose

The **Transport** port describes the wire-level delivery layer between a SOX MCP server and a backing store. It is the mechanism by which the MCP server pushes sent messages to the store and receives new messages from it.

SOX separates the transport concern from the backing-store concern:

- The **BackingStore** port (`spec/ports/backing-store.md`) specifies the logical operations (`send`, `recv`, `subscribe`, `list_channels`, `watch`).
- The **Transport** port specifies how those operations are realised over a network or IPC boundary.

In the simplest in-process case (e.g. in-memory backing store in a test), the transport is trivial (direct function calls). For remote backing stores (NATS, Redis), the transport handles connection management, reconnection, and serialisation.

---

## 2. Required behaviours

### 2.1 Connection establishment

The transport MUST:

- Establish a connection to the backing store before the MCP server begins accepting tool calls.
- Fail fast with a clear error if the connection cannot be established within a configurable timeout. The MCP server MUST NOT serve tool calls while the transport is not connected.
- Report the protocol version it targets during connection so the backing store can detect version mismatches.

### 2.2 Serialisation

All messages sent over the transport MUST be serialised as JSON. The JSON representation of a message envelope MUST conform to `spec/schemas/message.schema.json`.

The full wire envelope field set (see `spec/schemas/message.schema.json` and `spec/protocol.md §Message envelope shape`):

| Field | Type | Assigned by | Notes |
|---|---|---|---|
| `channel` | string | Sender | Target channel name. Reserved prefixes: `dm/`, `group/`, `sox/`. |
| `sender` | string | Server | Server-certified agent_id. |
| `body` | object | Sender | Opaque JSON payload. |
| `correlation_id` | string\|null | Sender | Optional request-reply token. |
| `sent_at` | number | Server | Unix epoch seconds (float). |
| `message_id` | string | Server | Backing-store-assigned unique ID. |
| `seq` | integer ≥ 1 | Server | Per-channel monotone counter. Authoritative ordering key. Replay cursor (`since`). |
| `ts` | integer\|null | Server | Monotonic nanosecond timestamp. Advisory cross-channel display tiebreaker. Not globally total-ordered. |
| `reply_to` | string\|null | Sender | `message_id` of parent in thread. Null if not a reply. Used with `thread_depth` on recv and for deadlock wait-graph. |
| `delivered_to` | string[]\|null | Server | Agent IDs that have recv'd this message. Used for deadlock detection. SHOULD-implement. |
| `origin_server` | string\|null | Server | Server ID in federated deployments. Always null in v1.0 single-server. |
| `_meta` | object\|null | Server | Observability metadata. Present when `include_meta=true` (default). Contains `trace_id`, `middleware_timings`, `server_node_id`. |

Implementations MAY use a more efficient wire encoding (e.g. MessagePack) for performance, provided:

- The backing store endpoint supports that encoding.
- The conformance suite (which speaks JSON over HTTP/MCP) is not affected.

### 2.3 Connection durability

The transport MUST:

- Detect connection loss and attempt reconnection with exponential back-off (minimum: 100 ms, maximum: configurable, default: 30 s).
- Buffer outbound `send` calls locally during a transient disconnection up to a configurable limit (default: 1000 messages). Overflow MUST surface as an error to the calling tool.
- Resume the `watch` stream from the last successfully delivered message after reconnection. If resume is not possible (e.g. the backing store does not support cursor-based resumption), the transport MUST re-establish the subscription from "current" (no replay of historical messages).

### 2.4 The `watch` stream

The transport is responsible for maintaining the long-lived push stream from the backing store to the MCP server. This stream is what gives the `channels__recv` tool its non-blocking, pre-buffered property.

Requirements:

- The `watch` stream MUST begin before the MCP server serves its first tool call.
- The transport MUST multiplex `watch` streams for all subscribed agent IDs over a single connection where the backing-store backend supports it.
- A slow `watch` consumer (i.e. the MCP server's listener task) MUST NOT cause the transport to drop `send` operations from other agents.

### 2.5 Shutdown

On MCP server shutdown:

- The transport MUST drain any locally buffered outbound messages before closing the connection.
- The transport MUST close the `watch` stream cleanly.
- Resource leaks (open sockets, file descriptors) MUST NOT remain after shutdown.

---

## 3. Security

The transport MUST support TLS when connecting to a remote backing store. In v1.0, TLS is optional for local connections (loopback, Unix socket).

Authentication of the MCP server to the backing store is implementation-defined. Recommended: shared secret or mTLS certificate. See `spec/ports/identity.md` for agent identity; the transport's authentication concern is MCP-server-to-store, not agent-to-server.

---

## 4. HTTP binding — CORS requirements

When the transport is bound to HTTP (as opposed to stdio), the server MUST implement CORS handling to enable browser-based clients (including the `sox-ui` web application).

**Required CORS behaviour:**

- The server MUST respond to preflight `OPTIONS` requests with the appropriate `Access-Control-Allow-*` headers before credentials are checked.
- The server MUST support a configurable origin allow-list. The default allow-list MUST include `http://localhost:*` and `http://127.0.0.1:*` for local development.
- The server MUST NOT include `Access-Control-Allow-Origin: *` when credentials (Authorization headers, cookies) are present in the request — this is a browser security constraint.
- The allow-list is a deployment configuration parameter (not a protocol field). Operators extending the allow-list beyond localhost MUST document their trust model.

> **Warning:** Exposing the SOX HTTP endpoint to the public internet without a reverse proxy is not recommended. Auth tokens travel in browser-visible headers. Document this clearly in deployment guides.
>
> **Decision source:** `docs/decisions/webapp-deployment-model.md`

---

## 5. HTTP binding — streaming for `channels__collect`

The `channels__collect` operation may block for up to the configured timeout (maximum 300 seconds). HTTP transport bindings MUST support one of the following efficient streaming mechanisms for collect responses:

- **Server-Sent Events (SSE):** The server opens an SSE stream and pushes collect progress events, closing the stream when count is reached or timeout elapses.
- **Long-poll:** The server holds the HTTP connection open until the collect condition is satisfied, then returns the full response.

Implementations that support neither SSE nor long-poll MAY implement collect by polling internally and returning a regular HTTP response, but this degrades efficiency for long timeout windows and is NOT RECOMMENDED for production deployments.

**Stdio binding:** The stdio transport satisfies `channels__collect` via asyncio blocking (the tool call blocks until completion). No additional transport mechanism is required for the stdio binding.

> **Decision source:** `docs/decisions/fanout-collect.md`

---

## 6. Conformance

A transport implementation is conformant when:

- [ ] Connection is established before tool serving begins.
- [ ] Connection loss triggers reconnection with back-off.
- [ ] The `watch` stream resumes (or re-subscribes) after reconnection.
- [ ] Outbound buffer overflow is surfaced as an error.
- [ ] Shutdown is clean; no resource leaks.
- [ ] All messages serialise and deserialise conformantly against `spec/schemas/message.schema.json` (including all fields: `seq`, `ts`, `reply_to`, `delivered_to`, `origin_server`, `_meta`).
- [ ] `list_channels` responses include the `_sox_protocol` block (not a flat `protocol_version` string). See `spec/schemas/tools/list-channels.output.schema.json`.
- [ ] HTTP binding: CORS preflight is handled; origin allow-list is configurable; localhost is in the default allow-list.
- [ ] HTTP binding: `channels__collect` is served via SSE or long-poll (or documented degraded mode).
- [ ] Stdio binding: `channels__collect` blocks via asyncio (no extra transport needed).
- [ ] The implementation passes the standard conformance suite at `spec/conformance/`.
