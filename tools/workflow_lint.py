#!/usr/bin/env python3
"""workflow_lint.py — internal-consistency validator for .workflow/ engagements.

Scans .workflow/plans/<slug>/ directories and reports violations.
Exit 0 on clean, non-zero on any violation (or warning if --strict).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_FRONTMATTER_KEYS: list[str] = [
    "phase_id",
    "title",
    "agent",
    "profile",
    "estimated_effort",
    "prereqs",
    "unblocks",
    "parallelizable_with",
    "writes",
    "reads",
    "context_size",
]

VALID_PROFILES: set[str] = {
    "meta",
    "spec",
    "code-python",
    "code-typescript",
    "code-with-spec",
    "planning",
    "test-harness",
    "docs",
    "review",
    "release",
}

KNOWN_AGENTS: set[str] = {
    "python-pro",
    "api-designer",
    "test-automator",
    "content-marketer",
    "code-reviewer",
    "architect-reviewer",
    "sox-cto-system:planner",
    "workflow-architect",
    "qa-expert",
    "devops-engineer",
    "fullstack-developer",
    "frontend-developer",
    "backend-developer",
    "data-scientist",
    "rust-engineer",
    "golang-pro",
    "typescript-pro",
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LintIssue:
    severity: str  # "error" | "warning" | "info"
    engagement: str
    phase_id: str | None
    check: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "engagement": self.engagement,
            "phase_id": self.phase_id,
            "check": self.check,
            "message": self.message,
        }


@dataclass
class LintResult:
    issues: list[LintIssue] = field(default_factory=list)
    checks_run: int = 0
    elapsed_ms: float = 0.0

    def error(
        self, engagement: str, phase_id: str | None, check: str, message: str
    ) -> None:
        self.issues.append(
            LintIssue("error", engagement, phase_id, check, message)
        )

    def warning(
        self, engagement: str, phase_id: str | None, check: str, message: str
    ) -> None:
        self.issues.append(
            LintIssue("warning", engagement, phase_id, check, message)
        )

    def info(
        self, engagement: str, phase_id: str | None, check: str, message: str
    ) -> None:
        self.issues.append(
            LintIssue("info", engagement, phase_id, check, message)
        )

    @property
    def errors(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def infos(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "info"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "checks_run": self.checks_run,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [i.as_dict() for i in self.issues],
        }


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> dict[str, Any] | None:
    """Extract YAML-like frontmatter between --- delimiters.

    Returns parsed dict or None if no frontmatter found.
    Uses a minimal hand-rolled parser to avoid yaml dependency.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return None
    fm_lines = lines[1:end]
    return _parse_yaml_simple(fm_lines)


def _parse_yaml_simple(lines: list[str]) -> dict[str, Any]:
    """Parse a simple flat YAML block (scalars and inline lists only)."""
    result: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        # Match key: value
        m = re.match(r"^(\w[\w_-]*):\s*(.*)", line)
        if not m:
            i += 1
            continue
        key = m.group(1)
        raw = m.group(2).strip()
        if raw.startswith("["):
            # inline list
            result[key] = _parse_inline_list(raw)
        elif raw == "" or raw == "|" or raw == ">":
            # block scalar or empty — collect continuation lines
            block_lines = []
            i += 1
            while i < len(lines) and (
                lines[i].startswith("  ") or lines[i].startswith("\t")
            ):
                block_lines.append(lines[i].strip())
                i += 1
            result[key] = "\n".join(block_lines) if block_lines else ""
            continue
        else:
            result[key] = _unquote(raw)
        i += 1
    return result


def _parse_inline_list(raw: str) -> list[str]:
    """Parse an inline YAML list like [a, b, "c d"]."""
    raw = raw.strip()
    if raw == "[]":
        return []
    inner = raw[1:-1] if raw.startswith("[") and raw.endswith("]") else raw
    items = []
    for part in re.split(r",\s*", inner):
        part = part.strip()
        if part:
            items.append(_unquote(part))
    return items


def _unquote(s: str) -> str:
    """Strip surrounding quotes from a YAML scalar."""
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (
        s.startswith("'") and s.endswith("'")
    ):
        return s[1:-1]
    return s


# ---------------------------------------------------------------------------
# STATE.md parser
# ---------------------------------------------------------------------------


def parse_state_md(state_path: Path) -> dict[str, Any]:
    """Extract status table rows and 'Currently next action' from STATE.md."""
    text = state_path.read_text()

    # Parse frontmatter
    fm = parse_frontmatter(text) or {}

    # Parse status table rows: | phase_id | title | status | ... |
    phase_rows: list[dict[str, str]] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if "|" not in stripped:
            continue
        cells = [c.strip() for c in stripped.split("|") if c.strip()]
        if not cells:
            continue
        # Header row detection
        if cells[0].lower() in ("phase", "phase_id"):
            in_table = True
            continue
        # Separator row
        if all(c.replace("-", "").replace(":", "") == "" for c in cells):
            continue
        if in_table and len(cells) >= 3:
            # Extract backtick-wrapped status if present
            raw_status = cells[2]
            status_m = re.search(r"`([^`]+)`", raw_status)
            status = status_m.group(1) if status_m else raw_status
            phase_rows.append({"phase_id": cells[0], "title": cells[1], "status": status})

    # Parse "Currently next action"
    next_action: str | None = None
    for line in text.splitlines():
        m = re.search(r"`([^`]+)`\s+is\s+`(READY|IN_PROGRESS|REVIEW|DONE|BLOCKED)`", line)
        if m:
            next_action = m.group(1)
            break
        # Alternate: plain phase_id reference in "Currently next action" section
        m2 = re.search(r"^\s*`([0-9]{2}-[a-z0-9-]+)`", line)
        if m2:
            next_action = m2.group(1)
            break

    return {"frontmatter": fm, "phase_rows": phase_rows, "next_action": next_action}


# ---------------------------------------------------------------------------
# DAG cycle detection
# ---------------------------------------------------------------------------


def has_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """Return a cycle path if one exists, else None. DFS-based."""
    visited: set[str] = set()
    rec_stack: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in graph:
                continue  # dangling ref handled elsewhere
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                path.append(neighbor)
                return True
        rec_stack.discard(node)
        path.pop()
        return False

    for node in list(graph.keys()):
        if node not in visited:
            if dfs(node):
                return path[:]
    return None


# ---------------------------------------------------------------------------
# Per-engagement lint
# ---------------------------------------------------------------------------


def lint_engagement(
    engagement_dir: Path, result: LintResult, repo_root: Path
) -> None:
    slug = engagement_dir.name
    phases_dir = engagement_dir / "phases"
    state_path = engagement_dir / "STATE.md"

    # Analyzer-only engagements have no phases/ directory by design — they
    # produce read-only artifacts (status.md, analysis.md) and never
    # decompose into phases. Skip phase/STATE-dependent checks (i), (j),
    # (l) for these engagements.
    if not phases_dir.exists():
        result.info(
            slug, None, "analyzer_only_engagement",
            "analyzer-only engagement, no phase decomposition"
        )
        result.checks_run += 1
        return

    # Collect phase files
    phase_files: dict[str, Path] = {}
    for p in sorted(phases_dir.glob("*.md")):
        # Skip feedback files
        if ".feedback-" in p.name:
            continue
        phase_files[p.stem] = p

    # Parse all phase frontmatters
    phase_fms: dict[str, dict[str, Any]] = {}
    for phase_id, phase_path in phase_files.items():
        text = phase_path.read_text()
        fm = parse_frontmatter(text)
        if fm is None:
            result.error(
                slug, phase_id, "frontmatter_missing",
                f"No frontmatter found in {phase_path.name}"
            )
            result.checks_run += 1
            continue
        phase_fms[phase_id] = fm
        result.checks_run += 1

        # (a) Required keys
        for key in REQUIRED_FRONTMATTER_KEYS:
            if key not in fm:
                result.error(
                    slug, phase_id, "frontmatter_schema",
                    f"Missing required frontmatter key '{key}' in {phase_path.name}"
                )
        result.checks_run += 1

        # (b) phase_id matches filename
        if "phase_id" in fm and fm["phase_id"] != phase_id:
            result.error(
                slug, phase_id, "phase_id_filename_mismatch",
                f"phase_id '{fm['phase_id']}' does not match filename '{phase_id}.md'"
            )
        result.checks_run += 1

        # (f) profile is valid
        if "profile" in fm:
            if fm["profile"] not in VALID_PROFILES:
                result.error(
                    slug, phase_id, "invalid_profile",
                    f"profile '{fm['profile']}' is not one of: {sorted(VALID_PROFILES)}"
                )
        result.checks_run += 1

        # (g) agent is non-empty string
        if "agent" in fm:
            agent_val = fm["agent"]
            if not isinstance(agent_val, str) or not agent_val.strip():
                result.error(
                    slug, phase_id, "invalid_agent",
                    f"agent must be a non-empty string, got: {agent_val!r}"
                )
            elif agent_val not in KNOWN_AGENTS:
                # Per phase prompt (g): "warn-only if matches a known list".
                # The KNOWN_AGENTS list is informational — emit INFO so
                # --strict does not promote to error for unrecognized agents.
                result.info(
                    slug, phase_id, "unknown_agent",
                    f"agent '{agent_val}' not in known agent registry (info-only)"
                )
        result.checks_run += 1

        # (h) writes[] and reads[] are non-empty arrays of strings
        for field_name in ("writes", "reads"):
            if field_name in fm:
                val = fm[field_name]
                if not isinstance(val, list):
                    result.error(
                        slug, phase_id, f"invalid_{field_name}",
                        f"'{field_name}' must be an array, got: {type(val).__name__}"
                    )
                else:
                    for item in val:
                        if not isinstance(item, str):
                            result.error(
                                slug, phase_id, f"invalid_{field_name}_item",
                                f"'{field_name}' items must be strings, got: {item!r}"
                            )
            result.checks_run += 1

        # Warn if writes is empty for non-review profiles
        if "writes" in fm and "profile" in fm:
            writes_val = fm["writes"]
            if isinstance(writes_val, list) and len(writes_val) == 0:
                if fm["profile"] not in ("review", "meta"):
                    result.warning(
                        slug, phase_id, "empty_writes",
                        f"writes[] is empty for profile '{fm['profile']}' — consider declaring write envelope"
                    )
        result.checks_run += 1

    # (c) prereqs[] entries are valid phase_ids within engagement
    # (d) unblocks[] entries are valid phase_ids within engagement
    for phase_id, fm in phase_fms.items():
        for field_name in ("prereqs", "unblocks"):
            if field_name not in fm:
                continue
            refs = fm[field_name]
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if not isinstance(ref, str):
                    continue
                if ref not in phase_files:
                    result.error(
                        slug, phase_id, f"dangling_{field_name}",
                        f"{field_name}[] references '{ref}' which does not exist in phases/"
                    )
            result.checks_run += 1

    # (e) DAG acyclic — build prereqs graph
    graph: dict[str, list[str]] = {}
    for phase_id, fm in phase_fms.items():
        prereqs = fm.get("prereqs", [])
        graph[phase_id] = [r for r in prereqs if isinstance(r, str)]

    cycle = has_cycle(graph)
    if cycle:
        result.error(
            slug, None, "cyclic_dependency",
            f"Dependency cycle detected: {' -> '.join(cycle)}"
        )
    result.checks_run += 1

    # (i) STATE.md phase rows match phases/ directory listing
    if state_path.exists():
        state_data = parse_state_md(state_path)
        table_phase_ids = {row["phase_id"] for row in state_data["phase_rows"]}
        fs_phase_ids = set(phase_files.keys())

        orphans = table_phase_ids - fs_phase_ids
        missing = fs_phase_ids - table_phase_ids
        for orphan in sorted(orphans):
            result.error(
                slug, orphan, "state_orphan",
                f"STATE.md status table has '{orphan}' but no matching file in phases/"
            )
        for miss in sorted(missing):
            result.error(
                slug, miss, "state_missing",
                f"phases/{miss}.md exists but has no row in STATE.md status table"
            )
        result.checks_run += 1

        # (j) "Currently next action" references a READY/IN_PROGRESS/REVIEW phase
        next_action = state_data["next_action"]
        if next_action:
            ready_phases = {
                row["phase_id"]
                for row in state_data["phase_rows"]
                if row["status"] in ("READY", "IN_PROGRESS", "REVIEW")
            }
            if next_action not in ready_phases:
                # Check if it's simply DONE/BLOCKED (stale state file)
                all_statuses = {
                    row["phase_id"]: row["status"]
                    for row in state_data["phase_rows"]
                }
                actual_status = all_statuses.get(next_action, "UNKNOWN")
                result.error(
                    slug, next_action, "next_action_not_ready",
                    f"'Currently next action' references '{next_action}' "
                    f"but its status is '{actual_status}', not READY/IN_PROGRESS/REVIEW"
                )
            result.checks_run += 1
    else:
        result.error(slug, None, "state_missing_file", "STATE.md not found in engagement directory")
        result.checks_run += 1

    # (k) Inputs section paths exist (warn-only)
    for phase_id, phase_path in phase_files.items():
        text = phase_path.read_text()
        # Find lines in the Inputs section
        in_inputs = False
        for line in text.splitlines():
            if re.match(r"^##\s+Inputs", line):
                in_inputs = True
                continue
            if in_inputs and re.match(r"^##\s+", line):
                in_inputs = False
                continue
            if in_inputs:
                # Match backtick-quoted paths or markdown links
                for path_match in re.finditer(r"`(/[^`]+)`", line):
                    cited_path = Path(path_match.group(1))
                    if not cited_path.exists():
                        # Future artifacts are expected; emit INFO so --strict
                        # does not promote these to errors. (Check (k) is
                        # documented as warn-only / informational.)
                        result.info(
                            slug, phase_id, "input_path_missing",
                            f"Inputs cites path '{cited_path}' which does not exist (info — may be future artifact)"
                        )
                    result.checks_run += 1

    # (l) planning-profile phases have downstream consumer in exit criteria
    for phase_id, fm in phase_fms.items():
        if fm.get("profile") != "planning":
            continue
        unblocks = fm.get("unblocks", [])
        if not isinstance(unblocks, list) or not unblocks:
            result.warning(
                slug, phase_id, "planning_no_consumer",
                f"planning-profile phase '{phase_id}' has no unblocks[] — expected downstream consumer"
            )
        result.checks_run += 1


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def lint(
    workflow_dir: Path,
    engagement_filter: str | None = None,
) -> LintResult:
    """Run all lint checks against the workflow directory."""
    start = time.monotonic()
    result = LintResult()

    plans_dir = workflow_dir / "plans"
    if not plans_dir.exists():
        result.error("", None, "plans_dir_missing", f"plans/ directory not found under {workflow_dir}")
        result.elapsed_ms = (time.monotonic() - start) * 1000
        return result

    for engagement_dir in sorted(plans_dir.iterdir()):
        if not engagement_dir.is_dir():
            continue
        if engagement_dir.name == "README.md":
            continue
        if engagement_filter and engagement_dir.name != engagement_filter:
            continue
        lint_engagement(engagement_dir, result, workflow_dir.parent)

    result.elapsed_ms = (time.monotonic() - start) * 1000
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate .workflow/ engagement consistency"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".workflow/",
        help="Path to .workflow/ directory (default: .workflow/)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit machine-readable JSON report",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors",
    )
    parser.add_argument(
        "--engagement",
        metavar="SLUG",
        help="Scope lint to a single engagement slug",
    )
    args = parser.parse_args()

    workflow_dir = Path(args.path).resolve()
    result = lint(workflow_dir, engagement_filter=args.engagement)

    if args.json_output:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        # Human-readable output
        if result.issues:
            for issue in result.issues:
                loc = f"{issue.engagement}"
                if issue.phase_id:
                    loc += f"/{issue.phase_id}"
                if issue.severity == "error":
                    prefix = "ERROR"
                elif issue.severity == "warning":
                    prefix = "WARN "
                else:
                    prefix = "INFO "
                print(f"[{prefix}] {loc}: [{issue.check}] {issue.message}")
        else:
            print(f"OK — {result.checks_run} checks passed in {result.elapsed_ms:.0f}ms")

        error_count = len(result.errors)
        warn_count = len(result.warnings)
        effective_errors = error_count + (warn_count if args.strict else 0)

        if result.issues:
            print(
                f"\n{result.checks_run} checks, {error_count} error(s), "
                f"{warn_count} warning(s) in {result.elapsed_ms:.0f}ms"
            )
            if args.strict and warn_count:
                print("(--strict: warnings treated as errors)")

    error_count = len(result.errors)
    warn_count = len(result.warnings)
    effective_errors = error_count + (warn_count if args.strict else 0)
    return 0 if effective_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
