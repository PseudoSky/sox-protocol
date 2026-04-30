# ADR 0002 — Agent identity primitive

## Status: Accepted (2026-04-29)

## Context

Today an agent's `agent_id` is a self-asserted environment variable read at MCP-client startup. Any process that can spawn a subprocess and set `SOX_AGENT_ID=alice` can speak as `alice`. This is an impersonation vulnerability that nullifies every higher-level security property the protocol claims to offer: DM confidentiality reduces to "delivered to whoever named themselves the recipient," group membership is unenforceable, audit logs are unattributable, and replay/admin ACLs anchored on `agent_id` are decorative. Until the server can independently verify "the bytes on this connection were sent by the holder of identity X," no other security work pays off.

The primary runtime is the Claude Code subprocess model: agents are launched via the Agent tool with environment supplied through `.mcp.json`. Subprocess startup is hot-path — the credential must be obtainable cheaply (a file read or env var, no interactive flow, no network round-trip before the first `channels__send`). The protocol spec is also expected to remain language-neutral: a Python, Rust, or browser-based agent runtime must be able to implement the same guarantee without inheriting the reference implementation's choices. Finally, the project ships under Apache 2.0 with the patent grant in scope; per the patent-landscape memo we avoid primitives where narrow claims have been asserted around agent-authentication flows.

This decision blocks ADRs that depend on verified-sender semantics: signed messages, recipient-side verification of DMs, group-membership enforcement, and any future federation handshake.

## Decision

Adopt **asymmetric keypair per agent** (Ed25519) as the reference-implementation identity primitive. Each agent holds a private key on disk; the server stores only the public key bound to the `agent_id`. Every request carries a signature over a canonical request envelope (agent_id, nonce, timestamp, method, body-hash); the server verifies before admitting the call. This is the only candidate that simultaneously (a) gives the server cryptographic rejection of impersonation without trusting a token issuer, (b) enables recipient-side verification of message provenance — required for the DM and signed-broadcast features already on the roadmap, and (c) costs one file read at subprocess boot.

## Alternatives considered

### 1. Shared secret per agent

| Pros | Cons |
|---|---|
| Trivial to implement | Server must store the secret (or a verifier equivalent); leak = full impersonation |
| Cheap subprocess bootstrap (env var) | No recipient-side verification — only the server can check |
| No PKI, no key formats | Rotation requires server-side coordination per agent |
|  | Cannot extend to federation without a second mechanism |

Rejected: forecloses signed-message and federation roadmap items. Solves only the server-auth slice of the problem and would be replaced within one minor version.

### 2. Asymmetric keypair per agent (chosen)

| Pros | Cons |
|---|---|
| Server stores public key only — leak of server DB does not enable impersonation | Key-management overhead: generation, distribution, storage |
| Enables recipient-side verification of messages (signed DMs, signed broadcasts) | Agents must protect private keys on disk |
| Ed25519 is unencumbered (public-domain reference, no known narrow patent claims in this space) | Rotation requires re-publishing public key |
| Language-neutral: every target runtime has an Ed25519 library | Initial bootstrap (first public-key registration) still needs a trust root |
| Subprocess cost: one file read + one signature per request (microseconds) |  |

Accepted.

### 3. Server-issued JWT

| Pros | Cons |
|---|---|
| Short-lived, revocable | Server becomes a trusted issuer — single point of compromise |
| Flexible claims model | Token-acquisition flow before first request: violates cheap-bootstrap constraint or requires a long-lived bootstrap credential anyway (recreating problem #1 or #2) |
| Familiar to web devs | Recipient-side verification requires distributing JWKs and trusting the issuer — heavier than a per-agent public key |
|  | Several JWT-adjacent agent-auth flows have narrow patent claims flagged in the landscape memo |
|  | Rotation flow non-trivial; revocation lists or short TTLs both add complexity |

Rejected: introduces an issuer dependency, doesn't avoid needing a long-lived credential underneath, and the patent surface is non-zero.

## Consequences

### Positive
- Server can reject impersonation cryptographically; `agent_id` becomes a verified claim, not an assertion.
- Unblocks signed-message ADRs: recipient can verify provenance without trusting the broker.
- No issuer dependency; works in air-gapped and federated deployments.
- Ed25519 is small (32-byte keys, 64-byte signatures), fast, and free of known patent encumbrance.
- Spec stays language-neutral: any runtime with an Ed25519 implementation can comply.

### Negative
- Agents must manage private-key files; loss of the key requires re-registration.
- Initial public-key registration needs a trust root (out-of-band admin step, or trust-on-first-use with operator confirmation) — see open questions.
- Slightly larger request envelope (signature + nonce + timestamp).

### Operational
- **Bootstrapping:** at first run, the agent generates a keypair, writes the private key to a per-agent path (e.g. `~/.sox/agents/<agent_id>/key.ed25519`, mode 0600), and registers the public key with the server via an admin-authenticated registration call. `.mcp.json` env points to the key path.
- **Rotation:** agent generates a new keypair, registers the new public key alongside the old, switches signing to the new key, then revokes the old public key after a grace window. Server accepts either during the overlap.
- **Recovery from key loss:** treated as identity loss. The operator must re-register through the same trust root used at bootstrap; no automatic recovery. Past messages signed by the lost key remain verifiable against the historically-recorded public key.
- **Server storage:** `(agent_id, public_key, registered_at, revoked_at?)`. Append-only; revocation does not delete history (needed for replay-log signature verification).

### Spec impact
The protocol spec at `spec/ports/identity.md` describes the **guarantee** — "the server (and any recipient with access to the agent's public key) can verify that a given request or message originated from the holder of `agent_id`" — and the abstract envelope shape (signed_request envelope: agent_id, nonce, timestamp, method, body-hash, signature). The spec does **not** mandate Ed25519; it states the cryptographic strength requirement. Ed25519 is recorded here as the reference-implementation choice only. Alternative implementations may select another scheme of equivalent strength provided they preserve the verified-sender guarantee.

## Open questions for follow-up

- **Rotation grace-period default:** how long to accept both old and new public keys during rotation. Deferred to the implementation-phase ADR; expected to land at 24h–7d.
- **Trust root for initial registration:** TOFU with operator confirmation vs. a dedicated admin bootstrap credential. Will be resolved alongside the admin-API ADR.
- **Key storage hardening:** OS keychain integration vs. plain file with 0600 mode. File mode is the v1 floor; keychain integration is a post-v1 enhancement.
- **Replay-window size:** the nonce + timestamp envelope needs a server-side replay cache TTL. Defer to the request-envelope ADR.
- **Federation bridging:** how a remote server learns a foreign agent's public key. Out of scope for v1; tracked in `docs/decisions/federation-scope.md`.
- **Key-format on disk:** raw 32-byte seed vs. PEM vs. JWK. Reference impl will pick one; spec stays silent.
