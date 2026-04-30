#!/usr/bin/env bash
# SOX Protocol — PostToolUse hook for Claude Code
#
# Claude Code invokes this script after every tool call.  Stdin carries a
# JSON object describing the tool use.  We forward it to the SOX enforcer
# and translate the Decision into Claude Code's expected output shape:
#
#   inject  → {"hookSpecificOutput": {"additionalContext": "<message>"}}
#   block   → {"decision": "block", "reason": "<message>"}
#   noop    → (exit 0, no output)
#
# On any error the script exits 0 with no output (safe-fail): the hook MUST
# NOT crash the agent.  The raw error is appended to $SOX_LOG_DIR/decisions.jsonl.
#
# Spec reference: CONTRACTS.md §3.5 (Decision semantics by adapter).

set -euo pipefail

if [ "${SOX_ORCHESTRATOR_MODE:-0}" = "1" ]; then
  exit 0
fi

SOX_LOG_DIR="${SOX_LOG_DIR:-${HOME}/.sox/logs}"

_log_error() {
    local msg="$1"
    mkdir -p "${SOX_LOG_DIR}"
    printf '{"ts":%s,"hook":"post_tool_use","error":%s}\n' \
        "$(date +%s)" \
        "$(printf '%s' "${msg}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
        >> "${SOX_LOG_DIR}/decisions.jsonl" 2>/dev/null || true
}

# Read stdin once into a variable so we can pass it to the enforcer
hook_input="$(cat)"

# Invoke the SOX enforcer CLI.  It reads the hook JSON on stdin, determines
# the event type and agent_id, runs decide(), and prints a JSON Decision on
# stdout (or nothing for noop).
decision_json="$(
    printf '%s' "${hook_input}" \
        | python3 -m sox_protocol.enforcer cli --hook post_tool_use 2>/tmp/sox_hook_err \
    || true
)"

enforcer_exit=$?

if [[ ${enforcer_exit} -ne 0 ]]; then
    err_content="$(cat /tmp/sox_hook_err 2>/dev/null || echo 'unknown error')"
    _log_error "${err_content}"
    exit 0  # safe-fail: do not crash the agent
fi

if [[ -z "${decision_json}" ]]; then
    exit 0  # noop
fi

# Parse the action field
action="$(printf '%s' "${decision_json}" | python3 -c \
    'import json,sys; d=json.load(sys.stdin); print(d.get("action","noop"))' 2>/dev/null || echo "noop")"

case "${action}" in
    inject)
        message="$(printf '%s' "${decision_json}" | python3 -c \
            'import json,sys; d=json.load(sys.stdin); print(d.get("message",""))' 2>/dev/null || echo "")"
        if [[ -n "${message}" ]]; then
            python3 -c \
                "import json,sys; print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': sys.argv[1]}}))" \
                "${message}"
        fi
        ;;
    block)
        message="$(printf '%s' "${decision_json}" | python3 -c \
            'import json,sys; d=json.load(sys.stdin); print(d.get("message",""))' 2>/dev/null || echo "")"
        python3 -c \
            "import json,sys; print(json.dumps({'decision': 'block', 'reason': sys.argv[1]}))" \
            "${message}"
        ;;
    noop|*)
        exit 0
        ;;
esac
