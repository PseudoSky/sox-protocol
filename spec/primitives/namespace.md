<!-- SPDX-License-Identifier: Apache-2.0 -->
# Namespace — Primitive Spec

**Protocol version:** 1.0
**Status:** Normative

---

## 1. Concept

A **namespace** is a logical isolation boundary that tags every channel and every message in the backing store. Namespaces separate tenants within a single SOX server deployment without requiring separate server processes.

Every channel name and message is scoped to exactly one namespace. Cross-namespace data access is structurally impossible at the backing-store port level — the store API requires a `namespace` parameter on every read/write operation and MUST NOT return records from a different namespace.

> **Decision source:** `docs/decisions/namespace-isolation-layer.md` — Option C (split: store-level enforcement, middleware-level resolution)

---

## 2. Default namespace

The default namespace is the string `"default"`. Single-tenant deployments operate entirely within `"default"` and effectively never observe the namespace system.

---

## 3. Namespace identifier rules

A valid namespace identifier:

- Is a non-empty ASCII string.
- Contains only characters in `[a-z0-9_-]` (lowercase letters, digits, underscore, hyphen).
- Has a maximum length of 64 characters.
- Is case-sensitive (`"Default"` and `"default"` are different namespaces).

---

## 4. Isolation modes

The backing store declares its isolation mode at construction time. The mode is a deployment-time configuration, not a runtime field on messages or envelopes.

| Mode | Description |
|---|---|
| `shared` | Single database. All queries include a `namespace` WHERE clause enforced inside the store implementation. Cross-namespace return is prevented by query construction. |
| `isolated` | Namespace maps to a separate SQLite file or Postgres schema. The store routes per-namespace at the connection/schema level. Cross-namespace return is prevented structurally. |

Both modes present an identical port interface to the SOX server. The SOX server MUST NOT need to know which mode is in use.

---

## 5. Namespace resolver middleware

A mandatory `namespace_resolver` middleware sits in the default chain **before** authentication. Its sole responsibility is to attach the correct namespace identifier to the request context so that all downstream middleware and the backing store operate within the correct namespace.

Default resolution rule: the authenticated principal's home namespace (derived from the credential registry). This means namespace resolution requires a preliminary identity hint before full auth runs; the resolver reads the claimed `agent_id` from the connection handshake and maps it to a namespace. Full cryptographic verification is still performed by the subsequent `auth` middleware.

The `namespace_resolver` is a **required** element of the default middleware chain. Removing it breaks namespace routing. Deployments that remove it MUST replace it with a functionally equivalent component and MUST document this deviation.

---

## 6. Namespace and federation

Namespace and `server_id` (federation) are **orthogonal** slots:

```
(server_id, namespace, channel, seq)
```

- `server_id` distinguishes hosts in a federated v2 deployment.
- `namespace` distinguishes tenants within a single host.

In v1.0 single-server deployments, `server_id` is empty or `null`. `namespace` is always present (defaulting to `"default"`).

---

## 7. Wire envelope

The `namespace` field does NOT appear on the wire envelope visible to agents. It is a server-internal routing tag. Agents do not specify namespaces in tool call parameters — the server derives the active namespace from the authenticated principal via the namespace resolver.

> **Post-v1:** An explicit `namespace` field in the wire envelope is reserved for federated deployments where cross-namespace routing may be required. In v1.0, it is implicit.

---

## 8. Namespace lifecycle

In v1.0, namespaces are **create-only**. There is no namespace deletion verb. Deleting a namespace with in-flight messages and active subscribers requires an eviction protocol that is deferred to post-v1.

Namespace creation is a privileged admin operation (see `spec/ports/middleware.md` and the admin-api-colocation decision).

> **Post-v1:** Namespace deletion with a documented eviction protocol, one-shot retag migration tool for single-tenant to multi-tenant splits, and per-namespace retention configuration are all deferred items.

---

## 9. Interaction with other primitives

| Primitive | Interaction |
|---|---|
| Channels ([channels.md](channels.md)) | Every channel exists within exactly one namespace; channel names are unique per namespace |
| Replay | Replay is namespace-scoped by construction; the `replay_policy: subscriber` default implicitly scopes to the principal's namespace |
| Backing store ([spec/ports/backing-store.md](../ports/backing-store.md)) | All backing-store operations are parameterised by `namespace`; see port contract |
| Identity ([spec/ports/identity.md](../ports/identity.md)) | The credential registry maps principals to namespaces |
| Middleware ([spec/ports/middleware.md](../ports/middleware.md)) | `namespace_resolver` is a required chain element; runs before auth |
