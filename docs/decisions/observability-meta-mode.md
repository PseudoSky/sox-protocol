# Decision: observability-meta-mode

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q1 (observability)

## Context

Every SOX response can carry a `_sox_meta` envelope (timing, routing, server version, token accounting). Always-present yields predictable client code and uniform telemetry; opt-in saves tokens for agents that don't care. This decision shapes the response envelope schema and the conformance-suite expectations for every tool.

## Decision

**Option C — Configurable at the server level, default ON, with a per-request override flag (`include_meta: false`) to suppress it.** Operators choose the default for their deployment via server config; individual callers can opt out per request to save tokens on hot paths. The shape of `_sox_meta` is fixed by the spec; whether it appears is a deployment/per-call concern.

## Rationale

The vision doc treats observability as a first-class differentiator ("observability has teeth"), so the default must surface it — opt-in would mean most users never see what makes SOX rigorous. But token cost is a real LLM-ergonomics concern flagged in the question, and a single global toggle is too coarse: a benchmark harness wants meta on every reply, while an agent in a tight back-and-forth thread wants it off. Server-default plus per-request override gives both audiences the right ergonomic without forking the protocol. Trade-off accepted: two configuration surfaces (deployment + request) instead of one, and conformance tests must cover both states.

## Consequences

- Positive: Default-on observability matches the product posture. Token-sensitive callers retain an escape hatch.
- Positive: Operators can flip the deployment default for "quiet mode" environments without client changes.
- Negative: Spec must define both the schema and the toggle precedence (request flag overrides server default).
- Negative: Conformance suite must test meta-on, meta-off, and override behaviour — three paths per tool.
- Spec impact: `spec/envelope.md` defines `_sox_meta` schema and the `include_meta` request flag. `spec/server-config.md` (or equivalent) defines the deployment default. `ports/transport.md` unchanged. Token-floor benchmark must measure both states.

## Pinned during spec extraction (2026-04-30)

The `_meta` field set was pinned as follows during spec extraction:

```json
{
  "trace_id": "string",
  "middleware_timings": ["string"],
  "server_node_id": "string"
}
```

`middleware_timings` is `string[]` using `"name:duration"` format (e.g. `"auth:2ms"`). This was chosen over a structured `{name, duration_ms}` object form for v1 simplicity. The canonical schema is in `spec/schemas/message.schema.json#/properties/_meta`.

## Open questions for follow-up

- Whether `middleware_timings` items should be structured objects `{name: string, duration_ms: number}` in v2 (richer for programmatic analysis). The string format is the v1 pin.
- Whether `include_meta: true` on a server defaulted to off should be allowed for unauthenticated callers, or gated behind ACL once identity primitive lands.
