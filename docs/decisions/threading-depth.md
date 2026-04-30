# Decision: threading-depth

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q1 (threading)

## Context
When an agent receives a message in a thread, the protocol must decide how much ancestor context to inline. The primary consumers are LLM agents whose context windows are the dominant cost; a 3-message thread is cheap to inline, a 100-message channel is not. This decision shapes the `recv` envelope schema, replay semantics, and the SDK helper surface.

## Decision
**Option C — `thread_depth` parameter on recv/replay, with sane defaults.** Messages always carry `reply_to` (immediate parent message ID) on the wire; that is the load-bearing primitive. Recv and replay verbs accept an optional `thread_depth` parameter: `0` (default) returns only `reply_to` IDs, `n` returns `n` ancestor envelopes inline, `-1` returns the full chain. The server resolves the inline expansion against the backing store; the agent decides per-call whether to pay the token cost.

## Rationale
The two extremes both lose: always-inline burns context on long threads (the dominant failure mode for LLM agents per `multi-agent-orchestration/dispatch-prompt-budget-contract.md`), and ID-only forces every agent to implement paging logic before it can do basic threaded reasoning. A caller-controlled depth keeps the wire format minimal (always just `reply_to`), keeps the cheap path cheap (default 0), and makes recovery scenarios (full chain) one parameter away. The trade-off accepted: server pays a join/walk cost when `thread_depth > 0`; bounded by `n` and by per-channel max-depth config.

## Consequences
- Positive: Agents pick their context cost per-call. Short threads can be requested in full; high-volume channels stay lean by default.
- Positive: Wire envelope stays minimal — `reply_to` is the only threading field. Inline ancestors are a response-shaping concern, not envelope schema.
- Positive: Conformance suite tests three depth modes against a fixed fixture; clean coverage matrix.
- Negative: Backing store must support efficient ancestor-walk queries (recursive CTE in SQL, parent-pointer chase in KV). Adds one port requirement.
- Negative: Server-side max-depth cap needed to prevent abuse (`thread_depth=-1` on a 10k-message thread).
- Spec impact: `spec/threading.md` defines `reply_to` semantics and the `thread_depth` parameter on `channels__recv` and replay. `ports/backing-store.md` adds an "ancestor walk by message id, bounded by depth" capability requirement. SDK ships `recv_thread(message_id, depth=-1)` convenience.

## Open questions for follow-up
- Per-channel default `thread_depth` (channel config)? Useful so high-volume channels can pin default to 0 even if SDK default differs. Defer to channel-config pass.
- Server-side max-depth cap value. Decide during spec extraction; suggest 50.
- Whether `thread_depth` interacts with `since` parameter (replay). Likely orthogonal but verify in conformance design.
