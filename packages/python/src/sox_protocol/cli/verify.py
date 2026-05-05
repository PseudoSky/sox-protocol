# SPDX-License-Identifier: Apache-2.0
"""``sox-protocol verify`` CLI subcommand.

Reports the health of a Claude Code project's SOX install:

- Backing store reachable (`SOX_BACKING_STORE` resolved + path readable)
- MCP server registered in ``.claude/settings.json``
- Hook scripts installed and executable
- Skill ``SKILL.md`` present
- All four MCP tools surfaced (proxied via SKILL.md content)

Returns ``0`` on full pass, ``1`` if any check failed.

Migrated from ``sox_protocol/cli.py`` in 0.1.5 — that legacy file was
shadowed by the ``sox_protocol/cli/`` package and unreachable via the
documented ``python -m sox_protocol.cli verify`` invocation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Status printers
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
# Constants
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


# ---------------------------------------------------------------------------
# Per-check helpers
# ---------------------------------------------------------------------------


def _check_backing_store(project_dir: Path) -> bool:
    """Verify the backing store is reachable."""
    backing_store_url = os.environ.get("SOX_BACKING_STORE", "")

    # Fall back to .claude/settings.json's mcpServers.sox.env block.
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

    if backing_store_url.startswith(("sqlite:///", "sqlite://")):
        from urllib.parse import urlparse

        parsed = urlparse(backing_store_url)
        db_path_str = parsed.path
        if not db_path_str or db_path_str in ("/:memory:", ":memory:"):
            _ok("Backing store", "sqlite::memory: (ephemeral)")
            return True
        db_path = Path(db_path_str)
        if not db_path.is_absolute():  # pragma: no cover
            db_path = project_dir / db_path
        if db_path.exists():
            _ok("Backing store", f"SQLite reachable at {db_path}")
        else:
            # Pre-init is fine — the store is created lazily on first use.
            _ok(
                "Backing store",
                f"SQLite not yet initialised at {db_path} (will be created on first use)",
            )
        return True
    if backing_store_url.startswith("memory://"):
        _ok("Backing store", "memory:// (ephemeral)")
        return True
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
    _ok(
        "MCP server",
        f"registered as '{_MCP_SERVER_NAME}' ({server_cfg.get('type', '?')} transport)",
    )
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
    skill_path = (
        project_dir / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md"
    )
    if not skill_path.exists():
        _fail("Skill SKILL.md", f"not found at {skill_path}")
        return False
    _ok("Skill SKILL.md", str(skill_path))
    return True


def _check_tools(project_dir: Path) -> bool:
    """Verify all four MCP tools are mentioned in the skill (proxy for surfacing)."""
    skill_path = (
        project_dir / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md"
    )
    if not skill_path.exists():
        _fail("MCP tools", "SKILL.md missing; cannot check tool surface")
        return False

    content = skill_path.read_text(encoding="utf-8")
    all_ok = True
    for tool in _REQUIRED_TOOLS:
        mcp_name = f"mcp__sox__{tool}"
        if mcp_name in content or tool in content:
            _ok(f"Tool {tool}", "found in SKILL.md")
        else:
            _fail(f"Tool {tool}", "NOT found in SKILL.md")
            all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def verify(project_dir: Path | None = None) -> int:
    """Run all config health checks.  Returns 0 on full pass, 1 on any failure."""
    if project_dir is None:
        project_dir = Path.cwd()
    project_dir = project_dir.resolve()

    print("SOX Protocol — configuration health check")
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

    failed = sum(1 for c in checks if not c)
    print(
        f"{failed} check(s) failed. Run 'sox-protocol install' to fix.",
        file=sys.stderr,
    )
    return 1


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def add_verify_subcommand(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Register the ``verify`` subcommand."""
    parser = subparsers.add_parser(
        "verify",
        help="Check configuration health of a SOX-installed project.",
        description=(
            "Reports backing-store reachability, MCP-server registration, "
            "hook installation, skill presence, and tool-surface completeness. "
            "Exit code is 0 on full pass, 1 if any check failed."
        ),
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Path to the Claude Code project root (default: current directory).",
    )
    parser.set_defaults(func=verify_command)


def verify_command(args: argparse.Namespace) -> int:
    """Execute the ``verify`` subcommand."""
    return verify(project_dir=args.project_dir)
