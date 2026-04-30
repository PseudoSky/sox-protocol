<!-- SPDX-License-Identifier: Apache-2.0 -->
# Identity Port — Behaviour Contract

**Version:** 1.0  
**Status:** Normative  
**Scope:** Language-neutral. This document specifies the guarantee that sender identity must be verified before any mutating operation, not how the credential is stored or validated. Credential mechanism is implementation-defined.

---

## 1. Purpose

The **Identity** port specifies the behavioural guarantee that every SOX message has a verifiably correct `sender` field — one that was bound by the server at connection time from a presented credential, not claimed by the client in the tool call payload.

Without identity verification, any agent could impersonate any other agent by setting `sender` to an arbitrary value. With identity verification, the `sender` field on every stored message is a server-certified claim.

---

## 2. Core guarantee

> **The `sender` field on a stored message MUST reflect the identity the server bound to the connection that issued the `send` call — not the identity the client claimed.**

The server assigns `sender` from its credential registry at the point of `send`; the client tool call does NOT include a `sender` parameter. This guarantee is unconditional regardless of which credential mechanism the implementation uses.

---

## 3. Credential primitive

The specific credential mechanism is implementation-defined. SOX v1.0 specifies only the guarantee, not the mechanism. Acceptable mechanisms include (non-exhaustive):

- **Shared secret** — agent registered with `(agent_id, secret)` pair; MCP server validates secret at connection; `agent_id` is then trusted for the session.
- **Asymmetric keypair** — agent presents a signed challenge at connection; server holds the public key; `agent_id` is bound to the key.
- **Server-issued token** — an orchestration layer issues a token to each agent before it connects; the server validates the token and maps it to an `agent_id`.

The reference implementation uses the shared-secret mechanism (see `per-agent-credential-registry` TODO in the implementation plan). Other implementations MAY substitute a different mechanism provided the core guarantee (§2) is upheld.

---

## 4. Scope of enforcement

Identity verification MUST apply to the following operations:

| Operation | Enforcement requirement |
|---|---|
| `send` | Sender identity MUST be verified; the `sender` field MUST be overwritten by the server with the bound identity, not taken from the client. |
| `subscribe` | The subscribing agent's identity MUST be verified; subscriptions are recorded under the verified `agent_id`. |
| `recv` | The draining agent's identity MUST be verified; messages MUST only be returned for the verified `agent_id`. |
| `list_channels` | Discovery is informational; identity verification is RECOMMENDED but not required. |

---

## 5. Identity failure behaviour

When an identity check fails (unknown credential, revoked credential, mismatched `agent_id`):

- The server MUST reject the operation and return an error conforming to `spec/envelopes/sox-error.schema.json`.
- The server MUST NOT persist any partial state from the failed operation.
- The server SHOULD log the failure (timestamp, claimed `agent_id`, operation) for audit purposes.
- The server MUST NOT leak information about the existence of other agents' credentials in the error response.

---

## 6. Connection-time binding

Identity is bound once at connection establishment, not per tool call. The binding persists for the lifetime of the connection. If a connection is lost and re-established, the agent must present its credential again.

This means:

- The `agent_id` field does NOT appear in any tool call input schema; the server injects it.
- Runtime adapters MUST configure the agent's credential in the MCP server launch parameters (environment variable, config file, or TLS certificate), not in tool call arguments.

---

## 7. Identity structure and federation

In v1.0 single-server deployments, agent identities are bare strings (e.g., `agent-alpha`). The protocol reserves a structured form for federated v2 deployments:

```text
<server-id>/<agent-id>
```

where `<server-id>` is an opaque string identifying the originating SOX server node, and `<agent-id>` is the agent's local identifier within that server.

**v1.0 behaviour:**

- The `<server-id>/` prefix is implicit (empty); agent IDs are bare strings.
- The `origin_server` envelope field carries `null` in v1.0.
- The backing-store credential registry records `(agent_id, public_key, registered_at, revoked_at?)` without a server-id component.

**v2 federation behaviour (reserved slot):**

- Agent IDs in cross-server messages MUST use the `<server-id>/<agent-id>` form.
- The `origin_server` envelope field carries the `server-id` of the originating server.
- A remote server learns a foreign agent's public key via federation key-exchange (deferred to v2 design).

**Reference implementation:** Ed25519 asymmetric keypair per agent (see ADR 0002). The spec describes the guarantee — "the server can verify that a given request originated from the holder of `agent_id`" — and does not mandate Ed25519. Alternative schemes of equivalent cryptographic strength are permitted provided the verified-sender guarantee (§2) is preserved.

---

## 8. v1.0 limitations

The following features are recognised as protocol-level TODOs and are deferred past v1.0:

- **Signed messages** — server signing each persisted message with a per-agent key so receivers can verify provenance independently. (Ed25519 keys from ADR 0002 enable this; the signed-envelope spec is deferred.)
- **Channel ACLs** — restricting which verified agent IDs can send to or subscribe to which channels.
- **Credential rotation** — rotating an agent's keypair without losing identity or message history.
- **Federation key exchange** — how a remote server learns a foreign agent's public key.

These are documented in the `classified.json` protocol TODO list under `post-v1` milestone.

---

## 9. Conformance

An identity-implementing SOX server is conformant when:

- [ ] No `send` call stores a message with a `sender` that differs from the server-bound identity for that connection.
- [ ] `recv` never returns messages belonging to a different agent's delivery set.
- [ ] `subscribe` never records a subscription under an unverified `agent_id`.
- [ ] Identity failures return a `sox-error` envelope and leave no partial state.
- [ ] Audit log entries are written for every identity failure.
- [ ] No information about other agents is leaked in error responses.
