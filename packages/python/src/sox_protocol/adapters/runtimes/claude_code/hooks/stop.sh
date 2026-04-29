#!/usr/bin/env bash
# SOX Protocol — Stop / SubagentStop hook for Claude Code
#
# Claude Code invokes this script when an agent is about to stop.  Stdin
# carries a JSON object describing the stop event.  Per CONTRACTS.md §3.5:
#
#   block  → {"decision": "block", "reason": "<message>"}   (inbox not drained)
#   noop   → (exit 0, no output)
#
# The SOX enforcer checks ``force_drain_on_stop`` (policy) and whether the
# agent's inbox is non-empty.  If both conditions are true, it returns a
# ``block`` decision that prevents the agent from stopping until it drains.
#
# On any error the script exits 0 with no output (safe-fail).
#
# Spec reference: CONTRACTS.md §3.5 and §4 (force_drain_on_stop policy).

set -euo pipefail

SOX_LOG_DIR="${SOX_LOG_DIR:-${HOME}/.sox/logs}"

_log_error() {
    local msg="$1"
    mkdir -p "${SOX_LOG_DIR}"
    printf '{"ts":%s,"hook":"stop","error":%s}\n' \
        "$(date +%s)" \
        "$(printf '%s' "${msg}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
        >> "${SOX_LOG_DIR}/decisions.jsonl" 2>/dev/null || true
}

hook_input="$(cat)"

decision_json="$(
    printf '%s' "${hook_input}" \
        | python3 -m sox_protocol.enforcer cli --hook stop 2>/tmp/sox_hook_err \
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

action="$(printf '%s' "${decision_json}" | python3 -c \
    'import json,sys; d=json.load(sys.stdin); print(d.get("action","noop"))' 2>/dev/null || echo "noop")"

case "${action}" in
    block)
        message="$(printf '%s' "${decision_json}" | python3 -c \
            'import json,sys; d=json.load(sys.stdin); print(d.get("message",""))' 2>/dev/null || echo "")"
        python3 -c \
            "import json,sys; print(json.dumps({'decision': 'block', 'reason': sys.argv[1]}))" \
            "${message}"
        ;;
    inject)
        # inject on stop is unusual but handle it gracefully
        message="$(printf '%s' "${decision_json}" | python3 -c \
            'import json,sys; d=json.load(sys.stdin); print(d.get("message",""))' 2>/dev/null || echo "")"
        if [[ -n "${message}" ]]; then
            python3 -c \
                "import json,sys; print(json.dumps({'hookSpecificOutput': {'additionalContext': sys.argv[1]}}))" \
                "${message}"
        fi
        ;;
    noop|*)
        exit 0
        ;;
esac
