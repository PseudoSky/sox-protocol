# Decision: admin-api-colocation

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q3 (admin / management API)

## Context
Admin tools (channel creation, ACL management, agent registry edits) need to be reachable by operators but unreachable by agent participants — even compromised ones. Co-location is operationally simple but shares a process boundary with the agent-facing surface; a separate admin process is harder to misconfigure but doubles deployment complexity. This decision interacts with the in-progress identity primitive decision.

## Decision
**Option C — Co-located but opt-in via an `--admin` flag (or equivalent server-config setting).** The reference server bundles admin tools in the same MCP server, but they are *not registered* unless the server is started with admin mode enabled. Production deployments are expected to run two server instances: a public agent-facing one (no admin tools registered) and an internal operator-facing one (admin tools registered, bound to a non-public socket and gated by ACL middleware). The spec describes the admin tool surface as a separable module that conformant implementations may or may not expose.

## Rationale
Pure co-location (Option A) makes the threat model depend entirely on ACL middleware being correctly configured — an unrecoverable single-line misconfiguration could expose admin tools to every agent. That is unacceptable for a protocol that hasn't yet locked its identity primitive. Pure separation (Option B) doubles the deployment story before the project has a chance to land its core pitch, and a separate process for what is essentially the same code is operational theatre. Opt-in registration is the right balance: a single deployment knob (the flag) decides whether the surface even exists, and the same codebase ships both modes. Trade-off accepted: documentation must teach operators the two-instance pattern, and conformance suite must verify that without the flag the admin tools are absent (not merely 403-gated).

## Consequences
- Positive: Default deployment is safe — agents literally cannot call tools that aren't registered.
- Positive: Single codebase, two deployment modes. Operations remain simple.
- Positive: Defence-in-depth — when identity primitive lands, ACL middleware on the admin instance is the second layer, not the only layer.
- Negative: Operators must understand and follow the two-instance pattern. Misconfiguration risk shifts from "ACL bug exposes admin to agents" to "operator runs only one instance with the flag and binds it publicly" — easier to spot in review.
- Negative: Some admin operations (channel creation triggered by an agent) may need a narrow public surface; those must be modelled as regular tools, not admin tools.
- Spec impact: `spec/admin-api.md` defines the admin tool set as an optional module. `ports/server.md` (or equivalent) documents the registration toggle. Reference implementation ships the `--admin` flag.

## Open questions for follow-up
- Whether the agent-triggered "create channel" verb is admin or public — defer until the addressable-destinations design pass.
- Audit logging for admin operations: same store, separate store, or external sink — defer to observability spec.
