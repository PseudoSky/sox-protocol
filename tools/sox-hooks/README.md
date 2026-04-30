# SOX Claude Code hooks

Two scripts wired into Claude Code's hook system:

| Script | Hook event | Purpose |
|---|---|---|
| `post_tool_use.sh` | `PostToolUse` | After every tool call, ask the SOX enforcer whether to inject an inbox reminder, block the action, or no-op. |
| `stop.sh` | `Stop` / `SubagentStop` | Before an agent stops, optionally block until its inbox is drained (per `force_drain_on_stop` policy). |

Both forward stdin (Claude's hook payload) to `python3 -m
sox_protocol.enforcer cli --hook <event>` and translate the JSON Decision
into Claude Code's expected output shape. On any error they exit 0 with
no output (safe-fail) and append the error to
`$SOX_LOG_DIR/decisions.jsonl`.

## Environment variables

| Var | Default | Effect |
|---|---|---|
| `SOX_LOG_DIR` | `~/.sox/logs` | Where the safe-fail error log is written. |
| `SOX_ORCHESTRATOR_MODE` | `0` | When set to `1`, both hooks short-circuit immediately with `exit 0`. The workflow orchestrator sets this so cadence-enforcer hooks do not re-inject inbox reminders during the orchestrator's own bash exit-criterion runs. The orchestrator is not the agent being cadence-enforced — its dispatched subagents are, in their own Claude Code sessions where `SOX_ORCHESTRATOR_MODE` is unset. |

The opt-out is intentionally a hook-side check rather than enforcer-side
policy: it is a per-session ergonomics flag, not part of the SOX contract.

## Spec reference

`docs/CONTRACTS.md §3.5` (Decision semantics by adapter) and `§4`
(`force_drain_on_stop` policy).
