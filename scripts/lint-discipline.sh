#!/usr/bin/env bash
# scripts/lint-discipline.sh
#
# Validates spec/discipline/discipline.md against the SOX discipline document
# structural requirements defined in CONTRACTS.md §2.
#
# Checks:
#   1. Required H1 heading is present.
#   2. All eight required H2 headings are present, in the exact order specified.
#   3. No concrete tool names appear outside {{placeholder}} forms
#      (catches accidental hard-coding of runtime-specific names like
#       mcp__sox__channels__send or channels__send).
#
# Exit codes:
#   0 — all checks pass
#   1 — one or more checks failed (errors printed to stderr)
#
# Usage:
#   scripts/lint-discipline.sh [path-to-discipline.md]
#
# If no path is given, defaults to spec/discipline/discipline.md relative to
# the repository root (detected as the directory containing this script's parent).

set -euo pipefail

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ $# -ge 1 ]]; then
  DISCIPLINE_FILE="$1"
else
  DISCIPLINE_FILE="${REPO_ROOT}/spec/discipline/discipline.md"
fi

if [[ ! -f "${DISCIPLINE_FILE}" ]]; then
  echo "ERROR: discipline file not found: ${DISCIPLINE_FILE}" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Required headings (CONTRACTS.md §2.1)
# Order is significant: checked in sequence.
# ---------------------------------------------------------------------------

REQUIRED_H1="# Inter-agent channels"

REQUIRED_H2=(
  "## When to send"
  "## How to send"
  "## Polling cadence"
  "## The send-and-continue pattern"
  "## The speculative-then-reconcile recipe"
  "## Anti-patterns"
  "## What not to use channels for"
)

# ---------------------------------------------------------------------------
# Tool name patterns that MUST NOT appear as bare text outside placeholders.
# Each entry is an extended-regex pattern passed to grep -E.
# We check for typical concrete MCP tool name forms:
#   - mcp__<namespace>__channels__<verb>  (Claude Code namespaced form)
#   - channels__send / channels__recv / channels__subscribe / channels__list_channels
#     when NOT inside a {{...}} token.
#
# Strategy: first strip all {{...}} tokens from the file content, then grep
# for any remaining bare tool name references.
# ---------------------------------------------------------------------------

CONCRETE_TOOL_PATTERNS=(
  'mcp__[a-zA-Z0-9_]+__channels__(send|recv|subscribe|list_channels)'
  'channels__(send|recv|subscribe|list_channels)'
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

ERRORS=0

fail() {
  echo "FAIL: $*" >&2
  ERRORS=$(( ERRORS + 1 ))
}

pass() {
  echo "PASS: $*"
}

# ---------------------------------------------------------------------------
# Check 1: Required H1
# ---------------------------------------------------------------------------

if grep -qF "${REQUIRED_H1}" "${DISCIPLINE_FILE}"; then
  pass "H1 '${REQUIRED_H1}' present"
else
  fail "H1 '${REQUIRED_H1}' not found"
fi

# ---------------------------------------------------------------------------
# Check 2: Required H2 headings present and in order
# ---------------------------------------------------------------------------

# Extract all headings (lines starting with # ) preserving order
HEADING_LIST="$(grep -E '^#{1,6} ' "${DISCIPLINE_FILE}" || true)"

# We scan sequentially: for each required H2, find it after the position of
# the previous one. We use awk for positional scanning.

prev_line=0
all_h2_ok=true

for h2 in "${REQUIRED_H2[@]}"; do
  # Find the line number of this H2 heading (exact match at start of line)
  found_line="$(awk -v h="${h2}" 'index($0, h) == 1 { print NR; exit }' "${DISCIPLINE_FILE}" || true)"

  if [[ -z "${found_line}" ]]; then
    fail "Required H2 not found: '${h2}'"
    all_h2_ok=false
  elif [[ "${found_line}" -le "${prev_line}" ]]; then
    fail "Required H2 out of order: '${h2}' (found on line ${found_line}, must appear after line ${prev_line})"
    all_h2_ok=false
  else
    pass "H2 '${h2}' present on line ${found_line}"
    prev_line="${found_line}"
  fi
done

# ---------------------------------------------------------------------------
# Check 3: No bare concrete tool names outside {{placeholder}} forms
#
# Strategy:
#   - Remove all content that is inside {{ ... }} from the file text.
#   - Then search the remaining text for known concrete tool name patterns.
#   - A match on the cleaned text means the tool name appears bare.
# ---------------------------------------------------------------------------

# Strip {{...}} tokens (may span any content inside braces; treat as single line)
STRIPPED_CONTENT="$(sed 's/{{[^}]*}}//g' "${DISCIPLINE_FILE}")"

for pattern in "${CONCRETE_TOOL_PATTERNS[@]}"; do
  # Use grep -n for line numbers in output; -E for extended regex
  matches="$(echo "${STRIPPED_CONTENT}" | grep -nE "${pattern}" || true)"
  if [[ -n "${matches}" ]]; then
    fail "Concrete tool name matching /${pattern}/ found outside {{placeholder}} form:"
    echo "${matches}" | while IFS= read -r line; do
      echo "  ${line}" >&2
    done
    ERRORS=$(( ERRORS + 1 ))
  else
    pass "No bare tool names matching /${pattern}/"
  fi
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
if [[ "${ERRORS}" -eq 0 ]]; then
  echo "discipline lint PASSED (0 errors)"
  exit 0
else
  echo "discipline lint FAILED (${ERRORS} error(s))" >&2
  exit 1
fi
