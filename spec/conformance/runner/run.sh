#!/bin/sh
# SOX Protocol Conformance Runner
# spec/conformance/runner/run.sh
#
# Runs all scenarios in spec/conformance/scenarios/ (lexicographic order)
# against a running SOX MCP HTTP server.
#
# AGENT ROUTING MODEL
# ===================
# Each scenario may involve multiple agent identities. The runner maintains
# one MCP session per (server_url, agent_id) pair. Sessions are established
# via MCP initialize and reused for all calls by that agent within the scenario.
# When the server is launched by run_python_impl.py (or docker compose), a
# single server process handles all agents because the agent_id is passed as
# an argument to each tool call via SOX_AGENT_ID awareness in the backing
# store. However, the Python reference implementation binds agent_id at server
# startup time.
#
# MULTI-AGENT STRATEGY
# ====================
# The runner passes agent-specific server URLs in SOX_AGENT_URLS (JSON map of
# agent_id -> URL). When not set, it falls back to SOX_SERVER_URL for all agents
# (single-server mode; the server must support per-session agent-id from the
# X-SOX-Agent-ID header or similar mechanism).
#
# For the Python reference implementation, run_python_impl.py starts one server
# per agent_id discovered in the scenario files and passes SOX_AGENT_URLS.
#
# Dependencies (must be on PATH):
#   sh (POSIX), curl, jq
#
# Environment variables:
#   SOX_SERVER_URL     Default MCP HTTP endpoint (used when SOX_AGENT_URLS not set)
#   SOX_AGENT_URLS     JSON object mapping agent_id -> MCP URL (optional)
#   SCENARIOS_DIR      Directory of scenario JSON files
#   SCHEMAS_DIR        Directory of spec JSON Schema files (unused; structural
#                      validation is done inline)
#   SOX_VERBOSE        Set to 1 for full MCP request/response dumps
#
# Exit code: 0 if all scenarios pass; non-zero otherwise.

set -eu

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFORMANCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

SOX_SERVER_URL="${SOX_SERVER_URL:-http://localhost:8000/mcp}"
SOX_AGENT_URLS="${SOX_AGENT_URLS:-}"
SCENARIOS_DIR="${SCENARIOS_DIR:-${CONFORMANCE_DIR}/scenarios}"
SOX_VERBOSE="${SOX_VERBOSE:-0}"

# ---------------------------------------------------------------------------
# ANSI colours (disabled if not a terminal)
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
    BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; BOLD=''; RESET=''
fi

log()  { printf "%b\n" "$*"; }
info() { printf "%b\n" "${BLUE}[INFO]${RESET} $*"; }
ok()   { printf "%b\n" "${GREEN}[PASS]${RESET} $*"; }
warn() { printf "%b\n" "${YELLOW}[WARN]${RESET} $*"; }
fail() { printf "%b\n" "${RED}[FAIL]${RESET} $*"; }

# MCP request ID counter
_MCP_ID=1

# Session store: /tmp/sox-sessions/<agent_id> contains the session ID
_SESSION_DIR="/tmp/sox-sessions-$$"
mkdir -p "${_SESSION_DIR}"
trap 'rm -rf "${_SESSION_DIR}"' EXIT INT TERM

# ---------------------------------------------------------------------------
# agent_url AGENT_ID -> prints the MCP URL for that agent
# ---------------------------------------------------------------------------
agent_url() {
    _aid="$1"
    if [ -n "${SOX_AGENT_URLS}" ]; then
        _url=$(printf '%s' "${SOX_AGENT_URLS}" | jq -r ".\"${_aid}\" // empty" 2>/dev/null)
        if [ -n "${_url}" ]; then
            printf '%s' "${_url}"
            return
        fi
    fi
    printf '%s' "${SOX_SERVER_URL}"
}

# ---------------------------------------------------------------------------
# mcp_session AGENT_ID -> prints the session ID, establishing one if needed
# ---------------------------------------------------------------------------
mcp_session() {
    _aid="$1"
    _sfile="${_SESSION_DIR}/${_aid}"
    if [ -f "${_sfile}" ]; then
        cat "${_sfile}"
        return
    fi
    _url=$(agent_url "${_aid}")
    _resp=$(curl -sf \
        -X POST "${_url}" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -D "${_SESSION_DIR}/${_aid}.headers" \
        --data-raw "{\"jsonrpc\":\"2.0\",\"id\":${_MCP_ID},\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"sox-conformance\",\"version\":\"1.0\"}}}" \
        --max-time 10 2>&1) || {
        fail "    mcp_session: initialize failed for agent=${_aid} url=${_url}"
        echo ""
        return 1
    }
    _MCP_ID=$((_MCP_ID + 1))
    _sid=$(grep -i 'mcp-session-id' "${_SESSION_DIR}/${_aid}.headers" 2>/dev/null \
        | awk '{print $2}' | tr -d '\r\n' || echo "")
    if [ -z "${_sid}" ]; then
        # Some implementations may not use session IDs (session-less mode)
        _sid="no-session"
    fi
    printf '%s' "${_sid}" > "${_sfile}"
    printf '%s' "${_sid}"
}

# ---------------------------------------------------------------------------
# mcp_call AGENT_ID TOOL ARGS_JSON -> prints result JSON to stdout
# ---------------------------------------------------------------------------
mcp_call() {
    _agent="$1"
    _tool="$2"
    _args="$3"

    _url=$(agent_url "${_agent}")
    _sid=$(mcp_session "${_agent}") || { echo "null"; return 1; }

    _req=$(jq -n \
        --arg id "${_MCP_ID}" \
        --arg tool "${_tool}" \
        --argjson args "${_args}" \
        '{"jsonrpc":"2.0","id":($id|tonumber),"method":"tools/call","params":{"name":$tool,"arguments":$args}}')
    _MCP_ID=$((_MCP_ID + 1))

    if [ "${SOX_VERBOSE}" = "1" ]; then
        log "  >> [${_agent}@${_url}] ${_tool} ${_args}"
    fi

    # Build curl command with optional session header
    if [ "${_sid}" = "no-session" ]; then
        _raw=$(curl -sf \
            -X POST "${_url}" \
            -H "Content-Type: application/json" \
            -H "Accept: application/json, text/event-stream" \
            --data-raw "${_req}" \
            --max-time 30 2>&1) || {
            fail "    curl failed for tool=${_tool} agent=${_agent}"
            echo "null"; return 1
        }
    else
        _raw=$(curl -sf \
            -X POST "${_url}" \
            -H "Content-Type: application/json" \
            -H "Accept: application/json, text/event-stream" \
            -H "mcp-session-id: ${_sid}" \
            --data-raw "${_req}" \
            --max-time 30 2>&1) || {
            fail "    curl failed for tool=${_tool} agent=${_agent}"
            echo "null"; return 1
        }
    fi

    if [ "${SOX_VERBOSE}" = "1" ]; then
        log "  << ${_raw}"
    fi

    # Handle SSE stream: extract the first data: line
    if printf '%s' "${_raw}" | grep -q "^data:"; then
        _raw=$(printf '%s' "${_raw}" | grep "^data:" | head -1 | sed 's/^data: //')
    fi

    # Validate parseable JSON
    if ! printf '%s' "${_raw}" | jq . >/dev/null 2>&1; then
        fail "    Non-JSON response for tool=${_tool} agent=${_agent}: ${_raw}"
        echo "null"; return 1
    fi

    # Extract content text from MCP tools/call response
    _content_text=$(printf '%s' "${_raw}" | jq -r \
        '.result.content[0].text // empty' 2>/dev/null || echo "")

    if [ -n "${_content_text}" ]; then
        # content[0].text is a JSON string — parse it
        if printf '%s' "${_content_text}" | jq . >/dev/null 2>&1; then
            printf '%s' "${_content_text}"
        else
            # Double-escaped — already a plain string
            printf '%s' "${_content_text}"
        fi
    else
        # Fallback: return the whole result
        printf '%s' "${_raw}" | jq '.result // .error // .'
    fi
}

# ---------------------------------------------------------------------------
# wait_for_server AGENT_ID — polls until that agent's server is reachable
# ---------------------------------------------------------------------------
wait_for_server() {
    _aid="${1:-__default__}"
    _url=$(agent_url "${_aid}")
    info "  Waiting for MCP server at ${_url} ..."
    _attempts=0
    while [ ${_attempts} -lt 30 ]; do
        if curl -sf -X POST "${_url}" \
            -H "Content-Type: application/json" \
            -H "Accept: application/json, text/event-stream" \
            --data-raw '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0.0.1"}}}' \
            --max-time 5 >/dev/null 2>&1; then
            return 0
        fi
        _attempts=$((_attempts + 1))
        sleep 1
    done
    fail "  Server at ${_url} did not become ready after 30 s"
    return 1
}

# ---------------------------------------------------------------------------
# validate_step_expect RESULT_JSON EXPECT_JSON
# ---------------------------------------------------------------------------
validate_step_expect() {
    _result="$1"
    _expect="$2"
    _ok=0
    _keys=$(printf '%s' "${_expect}" | jq -r 'keys[]' 2>/dev/null || echo "")
    for _key in ${_keys}; do
        _pred=$(printf '%s' "${_expect}" | jq -r ".\"${_key}\"")
        _pred_type=$(printf '%s' "${_pred}" | jq -r '.type // "any"' 2>/dev/null || echo "any")
        _actual_val=$(printf '%s' "${_result}" | jq ".\"${_key}\"" 2>/dev/null || echo "null")
        _key_present=$(printf '%s' "${_result}" | jq "has(\"${_key}\")" 2>/dev/null || echo "false")
        if [ "${_key_present}" = "false" ]; then
            fail "    Missing required field '${_key}'"
            _ok=1; continue
        fi
        case "${_pred_type}" in
            "number")
                if ! printf '%s' "${_actual_val}" | jq -e '. | type == "number"' >/dev/null 2>&1; then
                    fail "    Field '${_key}' expected number, got: ${_actual_val}"
                    _ok=1
                fi ;;
            "string")
                if ! printf '%s' "${_actual_val}" | jq -e '. | type == "string"' >/dev/null 2>&1; then
                    fail "    Field '${_key}' expected string, got: ${_actual_val}"
                    _ok=1
                fi
                _min_len=$(printf '%s' "${_pred}" | jq -r '.minLength // 0')
                if [ "${_min_len}" -gt 0 ]; then
                    _actual_len=$(printf '%s' "${_actual_val}" | jq -r '. | length' 2>/dev/null || echo 0)
                    if [ "${_actual_len}" -lt "${_min_len}" ]; then
                        fail "    Field '${_key}' length ${_actual_len} < minLength ${_min_len}"
                        _ok=1
                    fi
                fi ;;
            "array")
                if ! printf '%s' "${_actual_val}" | jq -e '. | type == "array"' >/dev/null 2>&1; then
                    fail "    Field '${_key}' expected array, got: ${_actual_val}"
                    _ok=1
                fi
                _min_items=$(printf '%s' "${_pred}" | jq -r '.minItems // 0')
                if [ "${_min_items}" -gt 0 ]; then
                    _actual_count=$(printf '%s' "${_actual_val}" | jq 'length' 2>/dev/null || echo 0)
                    if [ "${_actual_count}" -lt "${_min_items}" ]; then
                        fail "    Field '${_key}' has ${_actual_count} items, need >= ${_min_items}"
                        _ok=1
                    fi
                fi ;;
        esac
    done
    return ${_ok}
}

# ---------------------------------------------------------------------------
# run_step_assertions RESULT_JSON ASSERTIONS_JSON
# ---------------------------------------------------------------------------
run_step_assertions() {
    _result="$1"; _assertions="$2"; _ok=0
    _count=$(printf '%s' "${_assertions}" | jq 'length')
    _i=0
    while [ ${_i} -lt "${_count}" ]; do
        _a=$(printf '%s' "${_assertions}" | jq ".[$_i]")
        _atype=$(printf '%s' "${_a}" | jq -r '.type')
        _aidx=$(printf '%s' "${_a}" | jq -r '.message_index // 0')
        _afield=$(printf '%s' "${_a}" | jq -r '.field // ""')
        _avalue=$(printf '%s' "${_a}" | jq -r '.value // ""')
        case "${_atype}" in
            "message_field_equals")
                _msg=$(printf '%s' "${_result}" | jq ".messages[${_aidx}]" 2>/dev/null || echo "null")
                _actual=$(printf '%s' "${_msg}" | jq -r ".\"${_afield}\"" 2>/dev/null || echo "")
                if [ "${_actual}" != "${_avalue}" ]; then
                    fail "    Step assertion: messages[${_aidx}].${_afield}='${_actual}' != '${_avalue}'"
                    _ok=1
                fi ;;
            "message_body_field_equals")
                _msg=$(printf '%s' "${_result}" | jq ".messages[${_aidx}]" 2>/dev/null || echo "null")
                _actual=$(printf '%s' "${_msg}" | jq -r ".body.\"${_afield}\"" 2>/dev/null || echo "")
                if [ "${_actual}" != "${_avalue}" ]; then
                    fail "    Step assertion: messages[${_aidx}].body.${_afield}='${_actual}' != '${_avalue}'"
                    _ok=1
                fi ;;
        esac
        _i=$((_i + 1))
    done
    return ${_ok}
}

# ---------------------------------------------------------------------------
# run_scenario_assertions SCENARIO_ASSERTIONS STEP_RESULTS_JSON
# ---------------------------------------------------------------------------
run_scenario_assertions() {
    _assertions="$1"; _results="$2"; _ok=0
    _count=$(printf '%s' "${_assertions}" | jq 'length')
    _i=0
    while [ ${_i} -lt "${_count}" ]; do
        _a=$(printf '%s' "${_assertions}" | jq ".[$_i]")
        _atype=$(printf '%s' "${_a}" | jq -r '.type')
        _adesc=$(printf '%s' "${_a}" | jq -r '.description // .type')
        case "${_atype}" in
            "no_loss")
                _step=$(printf '%s' "${_a}" | jq -r '.recv_step')
                _min=$(printf '%s' "${_a}" | jq -r '.min // .sent_count // 1')
                _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                if [ "${_result}" = "null" ]; then
                    fail "    no_loss: recv_step '${_step}' result not found"
                    _ok=1
                else
                    _cnt=$(printf '%s' "${_result}" | jq '.messages | length' 2>/dev/null || echo 0)
                    if [ "${_cnt}" -lt "${_min}" ]; then
                        fail "    no_loss [${_adesc}]: got ${_cnt} messages, need >= ${_min}"
                        _ok=1
                    else
                        log "    ok: no_loss [${_adesc}] — ${_cnt} >= ${_min}"
                    fi
                fi ;;
            "no_duplication")
                _step=$(printf '%s' "${_a}" | jq -r '.recv_step // "recv-all"')
                _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                if [ "${_result}" != "null" ]; then
                    _total=$(printf '%s' "${_result}" | jq '.messages | length')
                    _unique=$(printf '%s' "${_result}" | jq '.messages | map(.message_id) | unique | length')
                    if [ "${_total}" != "${_unique}" ]; then
                        fail "    no_duplication [${_adesc}]: ${_total} msgs but ${_unique} unique ids"
                        _ok=1
                    else
                        log "    ok: no_duplication [${_adesc}] — ${_unique} unique ids"
                    fi
                fi ;;
            "no_redelivery")
                _step=$(printf '%s' "${_a}" | jq -r '.recv_step')
                _expected=$(printf '%s' "${_a}" | jq -r '.expected_count // 0')
                _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                if [ "${_result}" != "null" ]; then
                    _cnt=$(printf '%s' "${_result}" | jq '.messages | length' 2>/dev/null || echo -1)
                    if [ "${_cnt}" -ne "${_expected}" ]; then
                        fail "    no_redelivery [${_adesc}]: expected ${_expected}, got ${_cnt}"
                        _ok=1
                    else
                        log "    ok: no_redelivery [${_adesc}] — second recv returned ${_cnt}"
                    fi
                fi ;;
            "independent_delivery")
                _step=$(printf '%s' "${_a}" | jq -r '.recv_step')
                _min=$(printf '%s' "${_a}" | jq -r '.min // 1')
                _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                if [ "${_result}" != "null" ]; then
                    _cnt=$(printf '%s' "${_result}" | jq '.messages | length' 2>/dev/null || echo 0)
                    if [ "${_cnt}" -lt "${_min}" ]; then
                        fail "    independent_delivery [${_adesc}]: got ${_cnt}, need >= ${_min}"
                        _ok=1
                    else
                        log "    ok: independent_delivery [${_adesc}] — ${_cnt} >= ${_min}"
                    fi
                fi ;;
            "ordering")
                _step=$(printf '%s' "${_a}" | jq -r '.recv_step')
                _channel=$(printf '%s' "${_a}" | jq -r '.channel')
                _by=$(printf '%s' "${_a}" | jq -r '.by // "sent_at"')
                _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                if [ "${_result}" != "null" ]; then
                    _check=$(printf '%s' "${_result}" | jq \
                        --arg ch "${_channel}" --arg by "${_by}" \
                        '[.messages[] | select(.channel == $ch) | .[$by]] |
                         . as $a | reduce range(1;length) as $i (true; . and ($a[$i] >= $a[$i-1]))')
                    if [ "${_check}" != "true" ]; then
                        fail "    ordering [${_adesc}]: not ascending on ${_channel}.${_by}"
                        _ok=1
                    else
                        log "    ok: ordering [${_adesc}]"
                    fi
                fi ;;
            "body_seq_ascending")
                _step=$(printf '%s' "${_a}" | jq -r '.recv_step')
                _channel=$(printf '%s' "${_a}" | jq -r '.channel')
                _bf=$(printf '%s' "${_a}" | jq -r '.body_field')
                _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                if [ "${_result}" != "null" ]; then
                    _check=$(printf '%s' "${_result}" | jq \
                        --arg ch "${_channel}" --arg bf "${_bf}" \
                        '[.messages[] | select(.channel == $ch) | .body[$bf]] |
                         . as $a | reduce range(1;length) as $i (true; . and ($a[$i] >= $a[$i-1]))')
                    if [ "${_check}" != "true" ]; then
                        fail "    body_seq_ascending [${_adesc}]: body.${_bf} not ascending"
                        _ok=1
                    else
                        log "    ok: body_seq_ascending [${_adesc}]"
                    fi
                fi ;;
            "received_count")
                _step=$(printf '%s' "${_a}" | jq -r '.recv_step')
                _min=$(printf '%s' "${_a}" | jq -r '.min // 0')
                _max=$(printf '%s' "${_a}" | jq -r '.max // 99999')
                _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                if [ "${_result}" != "null" ]; then
                    _cnt=$(printf '%s' "${_result}" | jq '.messages | length' 2>/dev/null || echo 0)
                    if [ "${_cnt}" -lt "${_min}" ] || [ "${_cnt}" -gt "${_max}" ]; then
                        fail "    received_count [${_adesc}]: got ${_cnt}, expected [${_min},${_max}]"
                        _ok=1
                    else
                        log "    ok: received_count [${_adesc}] — ${_cnt} in [${_min},${_max}]"
                    fi
                fi ;;
            "no_channel_leak")
                _step=$(printf '%s' "${_a}" | jq -r '.recv_step')
                _forbidden=$(printf '%s' "${_a}" | jq -r '.forbidden_channel')
                _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                if [ "${_result}" != "null" ]; then
                    _found=$(printf '%s' "${_result}" | jq \
                        --arg ch "${_forbidden}" \
                        '[.messages[] | select(.channel == $ch)] | length')
                    if [ "${_found}" -gt 0 ]; then
                        fail "    no_channel_leak [${_adesc}]: ${_found} msgs from '${_forbidden}'"
                        _ok=1
                    else
                        log "    ok: no_channel_leak [${_adesc}]"
                    fi
                fi ;;
            "all_channels_match_pattern")
                _step=$(printf '%s' "${_a}" | jq -r '.recv_step')
                _pattern=$(printf '%s' "${_a}" | jq -r '.pattern')
                _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                if [ "${_result}" != "null" ]; then
                    _channels=$(printf '%s' "${_result}" | jq -r '[.messages[].channel] | unique[]')
                    _bad=0
                    for _ch in ${_channels}; do
                        case "${_ch}" in
                            ${_pattern}) ;;
                            *) fail "    all_channels_match_pattern: '${_ch}' not matching '${_pattern}'"; _bad=1 ;;
                        esac
                    done
                    [ ${_bad} -eq 0 ] && log "    ok: all_channels_match_pattern [${_adesc}]" || _ok=1
                fi ;;
            "all_receivers_got_message")
                _recv_steps=$(printf '%s' "${_a}" | jq -r '.recv_steps[]')
                for _step in ${_recv_steps}; do
                    _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                    if [ "${_result}" = "null" ]; then
                        fail "    all_receivers_got_message: step '${_step}' missing"
                        _ok=1; continue
                    fi
                    _cnt=$(printf '%s' "${_result}" | jq '.messages | length' 2>/dev/null || echo 0)
                    if [ "${_cnt}" -lt 1 ]; then
                        fail "    all_receivers_got_message: step '${_step}' got 0 msgs"
                        _ok=1
                    else
                        log "    ok: all_receivers_got_message — '${_step}' got ${_cnt}"
                    fi
                done ;;
            "all_writers_represented")
                _step=$(printf '%s' "${_a}" | jq -r '.recv_step')
                _bf=$(printf '%s' "${_a}" | jq -r '.body_field')
                _writers=$(printf '%s' "${_a}" | jq -r '.writers[]')
                _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                if [ "${_result}" != "null" ]; then
                    for _writer in ${_writers}; do
                        _found=$(printf '%s' "${_result}" | jq \
                            --arg bf "${_bf}" --arg w "${_writer}" \
                            '[.messages[] | select(.body[$bf] == $w)] | length')
                        if [ "${_found}" -lt 1 ]; then
                            fail "    all_writers_represented: no msgs from writer '${_writer}'"
                            _ok=1
                        else
                            log "    ok: all_writers_represented — '${_writer}' has ${_found} msg(s)"
                        fi
                    done
                fi ;;
            "message_id_present")
                _step=$(printf '%s' "${_a}" | jq -r '.recv_step')
                _ref=$(printf '%s' "${_a}" | jq -r '.capture_ref // ""')
                _result=$(printf '%s' "${_results}" | jq -r ".\"${_step}\"" 2>/dev/null || echo "null")
                if [ "${_result}" != "null" ] && [ -n "${_ref}" ]; then
                    _ref_step=$(printf '%s' "${_ref}" | cut -d. -f1)
                    _ref_field=$(printf '%s' "${_ref}" | cut -d. -f2)
                    _expected_id=$(printf '%s' "${_results}" | \
                        jq -r ".\"${_ref_step}\".\"${_ref_field}\"" 2>/dev/null || echo "")
                    if [ -z "${_expected_id}" ] || [ "${_expected_id}" = "null" ]; then
                        warn "    message_id_present: cannot resolve '${_ref}' — skipping"
                    else
                        _found=$(printf '%s' "${_result}" | jq \
                            --arg mid "${_expected_id}" \
                            '[.messages[] | select(.message_id == $mid)] | length')
                        if [ "${_found}" -lt 1 ]; then
                            fail "    message_id_present [${_adesc}]: id '${_expected_id}' not found"
                            _ok=1
                        else
                            log "    ok: message_id_present — '${_expected_id}' found"
                        fi
                    fi
                fi ;;
            "schema_valid")
                _step=$(printf '%s' "${_a}" | jq -r '.step')
                _schema_rel=$(printf '%s' "${_a}" | jq -r '.schema')
                log "    info: schema_valid '${_step}' vs '${_schema_rel}' (structural validation done during step)" ;;
        esac
        _i=$((_i + 1))
    done
    return ${_ok}
}

# ---------------------------------------------------------------------------
# run_scenario SCENARIO_FILE
# ---------------------------------------------------------------------------
run_scenario() {
    _file="$1"
    _scenario=$(cat "${_file}")
    _name=$(printf '%s' "${_scenario}" | jq -r '.name')

    log ""
    log "${BOLD}━━━ Scenario: ${_name} ━━━${RESET}"

    # Clear sessions for this scenario (fresh agent states)
    rm -f "${_SESSION_DIR}"/*.headers "${_SESSION_DIR}"/agent-*

    _results="{}"
    _ok=0

    # ----------------------------------------------------------------
    # Setup steps
    # ----------------------------------------------------------------
    _setup=$(printf '%s' "${_scenario}" | jq '.setup // []')
    _setup_count=$(printf '%s' "${_setup}" | jq 'length')
    _si=0
    while [ ${_si} -lt "${_setup_count}" ]; do
        _s=$(printf '%s' "${_setup}" | jq ".[$_si]")
        _agent=$(printf '%s' "${_s}" | jq -r '.agent')
        _tool=$(printf '%s' "${_s}" | jq -r '.tool')
        _args=$(printf '%s' "${_s}" | jq '.args // {}')
        info "  setup[${_si}]: [${_agent}] ${_tool}"
        _res=$(mcp_call "${_agent}" "${_tool}" "${_args}") || { _ok=1; }
        [ "${SOX_VERBOSE}" = "1" ] && log "    result: ${_res}"
        _si=$((_si + 1))
    done

    # ----------------------------------------------------------------
    # Main steps
    # ----------------------------------------------------------------
    _steps=$(printf '%s' "${_scenario}" | jq '.steps')
    _step_count=$(printf '%s' "${_steps}" | jq 'length')
    _si=0
    while [ ${_si} -lt "${_step_count}" ]; do
        _s=$(printf '%s' "${_steps}" | jq ".[$_si]")
        _stype=$(printf '%s' "${_s}" | jq -r '.type // "mcp_call"')
        _sid=$(printf '%s' "${_s}" | jq -r '.id // ""')

        if [ "${_stype}" = "sleep" ]; then
            _ms=$(printf '%s' "${_s}" | jq -r '.milliseconds // 200')
            _sec=$(awk "BEGIN{printf \"%.3f\", ${_ms}/1000}")
            info "  step[${_sid}]: sleep ${_ms}ms"
            sleep "${_sec}"
            _si=$((_si + 1))
            continue
        fi

        _agent=$(printf '%s' "${_s}" | jq -r '.agent')
        _tool=$(printf '%s' "${_s}" | jq -r '.tool')
        _args=$(printf '%s' "${_s}" | jq '.args // {}')
        _expect=$(printf '%s' "${_s}" | jq '.expect // {}')
        _step_assertions=$(printf '%s' "${_s}" | jq '.assertions // []')
        _capture_list=$(printf '%s' "${_s}" | jq -r '.capture // [] | .[]' 2>/dev/null || true)

        info "  step[${_sid}]: [${_agent}] ${_tool}"

        _res=$(mcp_call "${_agent}" "${_tool}" "${_args}") || {
            fail "  step[${_sid}] ERROR: mcp_call failed"
            _ok=1; _si=$((_si + 1)); continue
        }

        [ "${SOX_VERBOSE}" = "1" ] && log "    result: ${_res}"

        if ! validate_step_expect "${_res}" "${_expect}"; then
            fail "  step[${_sid}] FAILED: expect validation"
            _ok=1
        fi

        _assertion_count=$(printf '%s' "${_step_assertions}" | jq 'length')
        if [ "${_assertion_count}" -gt 0 ]; then
            if ! run_step_assertions "${_res}" "${_step_assertions}"; then
                _ok=1
            fi
        fi

        if [ -n "${_sid}" ]; then
            _results=$(printf '%s' "${_results}" | jq \
                --arg id "${_sid}" --argjson res "${_res}" \
                '. + {($id): $res}')
        fi

        for _field in ${_capture_list}; do
            _val=$(printf '%s' "${_res}" | jq -r ".\"${_field}\"" 2>/dev/null || echo "")
            if [ -n "${_sid}" ] && [ -n "${_val}" ] && [ "${_val}" != "null" ]; then
                _results=$(printf '%s' "${_results}" | jq \
                    --arg id "${_sid}" --arg field "${_field}" --arg val "${_val}" \
                    '.[$id][$field] = $val')
            fi
        done

        _si=$((_si + 1))
    done

    # ----------------------------------------------------------------
    # Scenario-level assertions
    # ----------------------------------------------------------------
    _scenario_assertions=$(printf '%s' "${_scenario}" | jq '.assertions // []')
    _acount=$(printf '%s' "${_scenario_assertions}" | jq 'length')
    if [ "${_acount}" -gt 0 ]; then
        info "  Running ${_acount} scenario assertion(s)..."
        if ! run_scenario_assertions "${_scenario_assertions}" "${_results}"; then
            _ok=1
        fi
    fi

    if [ ${_ok} -eq 0 ]; then
        ok "${GREEN}${BOLD}PASS${RESET} ${_name}"
    else
        fail "${RED}${BOLD}FAIL${RESET} ${_name}"
    fi
    return ${_ok}
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log ""
    log "${BOLD}SOX Protocol Conformance Suite${RESET}"
    log "Default server: ${SOX_SERVER_URL}"
    [ -n "${SOX_AGENT_URLS}" ] && log "Agent URL map: ${SOX_AGENT_URLS}"
    log "Scenarios: ${SCENARIOS_DIR}"
    log ""

    for _cmd in curl jq; do
        command -v "${_cmd}" >/dev/null 2>&1 || {
            fail "Required tool '${_cmd}' not found"; exit 1
        }
    done

    # Wait for default server (at minimum)
    wait_for_server "__default__" || exit 1

    _scenarios=$(find "${SCENARIOS_DIR}" -name "*.json" | sort)
    if [ -z "${_scenarios}" ]; then
        fail "No scenario files in ${SCENARIOS_DIR}"; exit 1
    fi

    _total=0; _passed=0; _failed=0; _failed_names=""

    for _f in ${_scenarios}; do
        _total=$((_total + 1))
        if run_scenario "${_f}"; then
            _passed=$((_passed + 1))
        else
            _failed=$((_failed + 1))
            _n=$(jq -r '.name' "${_f}")
            _failed_names="${_failed_names}  ${_n}"
        fi
    done

    log ""
    log "${BOLD}━━━ Results ━━━${RESET}"
    log "  Total:  ${_total}"
    log "  ${GREEN}Passed: ${_passed}${RESET}"
    if [ ${_failed} -gt 0 ]; then
        log "  ${RED}Failed: ${_failed}${RESET}"
        log "  Failed:${_failed_names}"
        log ""
        fail "${BOLD}Conformance suite FAILED (${_failed}/${_total})${RESET}"
        exit 1
    fi
    log ""
    ok "${BOLD}Conformance suite PASSED (${_passed}/${_total})${RESET}"
    exit 0
}

main "$@"
