# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol — top-level CLI.

Usage::

    python -m sox_protocol.cli verify [--project-dir PATH]

Commands
--------
``verify``
    Reports configuration health:
    - Backing store reachable
    - MCP server registered in ``.claude/settings.json``
    - Hook scripts installed and executable
    - Skill SKILL.md present
    - All four MCP tools surfaced

``install``
    Delegates to the Claude Code adapter installer.

``lint-discipline``
    Validates a discipline markdown file's anchor structure.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(label: str, detail: str = "") -> None:
    suffix = f"  {detail}" if detail else ""
    print(f"  [OK]  {label}{suffix}")


def _fail(label: str, detail: str = "") -> None:
    suffix = f"  {detail}" if detail else ""
    print(f"  [FAIL] {label}{suffix}")


def _warn(label: str, detail: str = "") -> None:
    suffix = f"  {detail}" if detail else ""
    print(f"  [WARN] {label}{suffix}")


# ---------------------------------------------------------------------------
# verify sub-command
# ---------------------------------------------------------------------------

_REQUIRED_TOOLS = {
    "channels__send",
    "channels__recv",
    "channels__subscribe",
    "channels__list_channels",
}

_MCP_SERVER_NAME = "sox"
_HOOK_EVENTS = ["PostToolUse", "Stop", "SubagentStop"]
_HOOK_SCRIPTS = ["post_tool_use.sh", "stop.sh"]


def _check_backing_store(project_dir: Path) -> bool:
    """Verify the backing store is reachable."""
    import os as _os

    backing_store_url = _os.environ.get("SOX_BACKING_STORE", "")

    # Try to find the DB from settings.json
    settings_path = project_dir / ".claude" / "settings.json"
    if not backing_store_url and settings_path.exists():
        try:
            settings: dict[str, Any] = json.loads(settings_path.read_text())
            mcp = settings.get("mcpServers", {}).get(_MCP_SERVER_NAME, {})
            env = mcp.get("env", {})
            backing_store_url = env.get("SOX_BACKING_STORE", "")
        except Exception:
            pass

    if not backing_store_url:
        _warn("Backing store", "SOX_BACKING_STORE not set; using default")
        return True

    if backing_store_url.startswith("sqlite:///") or backing_store_url.startswith("sqlite://"):
        # sqlite:///absolute/path  or  sqlite://relative/path
        # urllib.parse handles this correctly
        from urllib.parse import urlparse
        parsed = urlparse(backing_store_url)
        db_path_str = parsed.path  # already the path component
        if not db_path_str or db_path_str in ("/:memory:", ":memory:"):
            _ok("Backing store", "sqlite::memory: (ephemeral)")
            return True
        db_path = Path(db_path_str)
        if not db_path.is_absolute():
            db_path = project_dir / db_path
        if db_path.exists():
            _ok("Backing store", f"SQLite reachable at {db_path}")
            return True
        else:
            # DB doesn't exist yet — that's fine for a fresh install
            _ok("Backing store", f"SQLite not yet initialised at {db_path} (will be created on first use)")
            return True
    elif backing_store_url.startswith("memory://"):
        _ok("Backing store", "memory:// (ephemeral)")
        return True
    else:
        _warn("Backing store", f"Unknown scheme: {backing_store_url}")
        return True


def _check_mcp_server(project_dir: Path) -> bool:
    """Verify the SOX MCP server is registered in settings.json."""
    settings_path = project_dir / ".claude" / "settings.json"
    if not settings_path.exists():
        _fail("MCP server", ".claude/settings.json not found — run 'install' first")
        return False

    try:
        settings: dict[str, Any] = json.loads(settings_path.read_text())
    except json.JSONDecodeError as exc:
        _fail("MCP server", f"settings.json is not valid JSON: {exc}")
        return False

    mcp_servers = settings.get("mcpServers", {})
    if _MCP_SERVER_NAME not in mcp_servers:
        _fail("MCP server", f"'{_MCP_SERVER_NAME}' not in mcpServers")
        return False

    server_cfg = mcp_servers[_MCP_SERVER_NAME]
    _ok("MCP server", f"registered as '{_MCP_SERVER_NAME}' ({server_cfg.get('type', '?')} transport)")
    return True


def _check_hooks(project_dir: Path) -> bool:
    """Verify hook scripts are installed and executable."""
    hooks_dir = project_dir / "tools" / "sox-hooks"
    all_ok = True

    for script_name in _HOOK_SCRIPTS:
        script = hooks_dir / script_name
        if not script.exists():
            _fail(f"Hook {script_name}", f"not found at {script}")
            all_ok = False
            continue
        if not os.access(script, os.X_OK):
            _fail(f"Hook {script_name}", "exists but is not executable")
            all_ok = False
            continue
        _ok(f"Hook {script_name}", str(script))

    # Check hook registrations in settings.json
    settings_path = project_dir / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings: dict[str, Any] = json.loads(settings_path.read_text())
            hooks_cfg = settings.get("hooks", {})
            for event in _HOOK_EVENTS:
                if event in hooks_cfg and hooks_cfg[event]:
                    _ok(f"Hook event {event}", "registered in settings.json")
                else:
                    _fail(f"Hook event {event}", "not registered in settings.json")
                    all_ok = False
        except Exception:
            pass

    return all_ok


def _check_skill(project_dir: Path) -> bool:
    """Verify the inter-agent-channels skill SKILL.md is present."""
    skill_path = project_dir / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md"
    if not skill_path.exists():
        _fail("Skill SKILL.md", f"not found at {skill_path}")
        return False
    _ok("Skill SKILL.md", str(skill_path))
    return True


def _check_tools(project_dir: Path) -> bool:
    """Verify all four MCP tools are mentioned in the skill (as a proxy for surfacing)."""
    skill_path = project_dir / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md"
    if not skill_path.exists():
        _fail("MCP tools", "SKILL.md missing; cannot check tool surface")
        return False

    content = skill_path.read_text(encoding="utf-8")
    all_ok = True
    for tool in _REQUIRED_TOOLS:
        claude_name = f"mcp__sox__{tool}"
        # tools appear as mcp__sox__channels__send etc.
        mcp_name = f"mcp__sox__{tool}"
        if mcp_name in content or tool in content:
            _ok(f"Tool {tool}", "found in SKILL.md")
        else:
            _fail(f"Tool {tool}", "NOT found in SKILL.md")
            all_ok = False

    return all_ok


def verify(project_dir: Path | None = None) -> int:
    """Run all config health checks. Returns 0 on full pass, 1 on any failure."""
    if project_dir is None:
        project_dir = Path.cwd()
    project_dir = project_dir.resolve()

    print(f"SOX Protocol — configuration health check")
    print(f"  Project dir: {project_dir}")
    print()

    checks = [
        _check_backing_store(project_dir),
        _check_mcp_server(project_dir),
        _check_hooks(project_dir),
        _check_skill(project_dir),
        _check_tools(project_dir),
    ]

    print()
    if all(checks):
        print("All checks passed.")
        return 0
    else:
        failed = sum(1 for c in checks if not c)
        print(f"{failed} check(s) failed. Run 'python -m sox_protocol.adapters.runtimes.claude_code install' to fix.")
        return 1


# ---------------------------------------------------------------------------
# lint-discipline sub-command
# ---------------------------------------------------------------------------

_REQUIRED_HEADINGS = [
    "# Inter-agent channels",
    "## When to send",
    "## How to send",
    "## Polling cadence",
    "## The send-and-continue pattern",
    "## The speculative-then-reconcile recipe",
    "## Anti-patterns",
    "## What not to use channels for",
]

_CONCRETE_TOOL_NAMES = [
    "mcp__sox__channels__send",
    "mcp__sox__channels__recv",
    "mcp__sox__channels__subscribe",
    "mcp__sox__channels__list_channels",
    "channels__send",
    "channels__recv",
    "channels__subscribe",
    "channels__list_channels",
]


def lint_discipline(discipline_path: Path) -> int:
    """Validate a discipline markdown file. Returns 0 on pass, 1 on fail."""
    if not discipline_path.exists():
        print(f"[FAIL] File not found: {discipline_path}")
        return 1

    content = discipline_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    errors: list[str] = []

    # Check required headings present and in order
    last_pos = -1
    for heading in _REQUIRED_HEADINGS:
        found = False
        for i, line in enumerate(lines):
            if line.strip() == heading:
                if i <= last_pos:
                    errors.append(f"Heading '{heading}' appears out of order (line {i + 1})")
                else:
                    last_pos = i
                found = True
                break
        if not found:
            errors.append(f"Required heading missing: '{heading}'")

    # Check no concrete tool names outside placeholders
    for tool_name in _CONCRETE_TOOL_NAMES:
        if tool_name in content:
            errors.append(f"Concrete tool name found (must use placeholder instead): '{tool_name}'")

    if errors:
        print(f"Discipline lint FAILED: {discipline_path}")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"Discipline lint passed: {discipline_path}")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m sox_protocol.cli",
        description="SOX Protocol command-line interface.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # verify
    verify_parser = subparsers.add_parser("verify", help="Check configuration health.")
    verify_parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Path to the Claude Code project root (default: current directory).",
    )

    # install (delegates to adapter)
    install_parser = subparsers.add_parser("install", help="Install the SOX adapter.")
    install_parser.add_argument("--project-dir", type=Path, default=None)
    install_parser.add_argument("--quiet", action="store_true")

    # lint-discipline
    lint_parser = subparsers.add_parser(
        "lint-discipline", help="Validate a discipline markdown file."
    )
    lint_parser.add_argument("path", type=Path, help="Path to the discipline.md file.")

    args = parser.parse_args(argv)

    if args.command == "verify":
        sys.exit(verify(project_dir=args.project_dir))

    elif args.command == "install":
        from sox_protocol.adapters.runtimes.claude_code.install import install

        install(project_dir=args.project_dir, verbose=not args.quiet)

    elif args.command == "lint-discipline":
        sys.exit(lint_discipline(args.path))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
