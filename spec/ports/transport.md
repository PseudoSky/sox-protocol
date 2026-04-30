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

## 4. Conformance

A transport implementation is conformant when:

- [ ] Connection is established before tool serving begins.
- [ ] Connection loss triggers reconnection with back-off.
- [ ] The `watch` stream resumes (or re-subscribes) after reconnection.
- [ ] Outbound buffer overflow is surfaced as an error.
- [ ] Shutdown is clean; no resource leaks.
- [ ] All messages serialise and deserialise conformantly against `spec/schemas/message.schema.json`.
- [ ] The implementation passes the standard conformance suite at `spec/conformance/`.
