# Decision: tui-connection-model

**Status:** Resolved — 2026-04-30
**Source question:** bucket-classification result.md Q1 (tui-connection-model)

## Context
The `sox chat` TUI is the 30-second demo that sells SOX's entire pitch. It needs a connection model to the SOX server: spawn the MCP server as a stdio subprocess (Option A), bypass MCP and import the backing-store adapter directly (Option B), or wait for the HTTP transport and connect to a running endpoint (Option C). The choice determines whether the demo exercises the same code path as real agents and whether it's blocked on the `http-transport` engagement.

## Decision
**Option A — Stdio subprocess.** The TUI launches `sox` (the MCP server) as a child process and speaks the stdio MCP protocol over its pipes, exactly the way a Claude Code or other MCP-client agent would. The TUI is treated as just another MCP client, with the only differences being a richer rendering layer and human-driven input. No special "TUI mode" is added to the server; no direct backing-store import is permitted from the TUI package.

## Rationale
The TUI's value as a demo is that it shows the *real* protocol behaving correctly under live conditions; bypassing MCP (Option B) would make the demo a lie — visitors would see a UI that the reference agents cannot reproduce because they go through a different layer. Option C is correct in the long run but blocks the v1-critical demo on the `http-transport` engagement, which currently has only a READY planning phase. Stdio subprocess catches MCP-layer bugs (envelope shape, transport adapter, watch/streaming) that would otherwise only surface in agent integration tests, and aligns with the vision-doc principle "MCP is one transport binding among several" — the TUI exercises that binding end-to-end. Trade-off accepted: slightly slower than direct store access on cold start (subprocess fork + handshake) and a small amount of plumbing for stdio framing; both are negligible at demo scale.

## Consequences
- Positive: TUI and reference agents share one code path; bugs found by humans clicking in the TUI are bugs real agents would also hit.
- Positive: Unblocks `chat-tui-demo` immediately — no dependency on `http-transport`.
- Positive: When HTTP transport ships, the TUI gains it for free by switching transport adapter; the connection model abstraction stays.
- Negative: Subprocess lifecycle (spawn, health, clean shutdown on TUI exit) is the TUI's responsibility; need a small process-manager utility.
- Negative: No shared in-process state with the server — every operation goes through MCP, so the TUI cannot "peek" at server internals for diagnostics. (This is correct; it's the discipline we want.)
- Spec impact: None directly. Reinforces the position that MCP is a transport binding, not a privileged path. Confirms that `ports/transport.md` stdio binding must support multiple concurrent clients (TUI + spawned demo agents share the same server).

## Open questions for follow-up
- Should `sox chat` spawn its own dedicated server, or attach to an already-running one? Lean: spawn its own by default (zero-config demo); add `--attach <pid|socket>` later for power users.
- When HTTP transport lands, add `sox chat --http <url>` as a second connection mode. Defer the flag design to `http-transport`'s planning phase.
- Subprocess crash behavior — does the TUI offer to restart, or exit with the server's stderr? Decide during TUI implementation; not a protocol concern.
