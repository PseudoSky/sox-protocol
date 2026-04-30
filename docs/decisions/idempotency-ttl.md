# Decision: idempotency-ttl

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q2 (idempotent send)

## Context
Idempotent send requires the backing store to retain deduplication keys long enough to absorb realistic retry windows, but not so long that the table grows unbounded. SQLite (the reference store) makes unbounded growth a real operational risk; production Postgres deployments expect operator control. This decision shapes the backing-store port contract and the conformance-suite expectations for replay-after-window behaviour.

## Decision
**Option C — Configurable TTL at the server (and optionally per channel), with a default of 24 hours.** The spec mandates that implementations support a TTL on idempotency keys, sets the default to 24h, and requires that a background sweep (or equivalent compaction) reclaim expired keys. Operators can extend (e.g. 7d for slow agents, 30d for audit-heavy environments) or shorten via configuration. Per-channel override is permitted but not required for v1.

## Rationale
A fixed TTL is too inflexible for a protocol meant to run across very different deployments (Claude Code subprocess agents finish in seconds; long-running research agents may retry days later). 24h is the right default — it covers the overwhelming majority of retry scenarios documented in distributed-systems literature for at-least-once semantics, and matches Postgres/Redis conventions for idempotency tables. "Forever" is rejected: it shifts an operational concern (table growth) into a correctness claim the protocol cannot keep on the SQLite reference store. Trade-off accepted: callers cannot rely on dedup beyond the configured window, and must be told this in the spec.

## Consequences
- Positive: Bounded growth on every backing store. SQLite reference deployment stays viable indefinitely.
- Positive: Operators with strong audit requirements can extend the window; nothing in the protocol blocks them.
- Negative: Idempotent send is a guarantee with a clock attached. Spec must state this explicitly to avoid the "forever" misreading.
- Negative: Implementations must ship a sweep/compaction mechanism — extra surface in the backing-store port.
- Spec impact: `ports/backing-store.md` adds an `idempotency_ttl_seconds` configuration field and requires implementations to expose a sweep operation (or equivalent). `spec/idempotent-send.md` documents the windowed guarantee. Conformance suite must test (a) dedup within window, (b) re-acceptance after window, (c) sweep reclaims storage.

## Open questions for follow-up
- Whether per-channel TTL override is worth shipping in v1 or defer to v0.2.
- Exact sweep cadence default (continuous, hourly, on-startup) — implementation detail, may not need to live in the spec.
