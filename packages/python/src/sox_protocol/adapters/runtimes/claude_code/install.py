# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol — Claude Code runtime adapter installer.

Invocation::

    python -m sox_protocol.adapters.runtimes.claude_code install [--project-dir PATH]

This module implements ``DisciplineRenderer`` + ``EnforcerBinding`` installation
for the Claude Code runtime.  Running ``install`` is idempotent: executing it
twice MUST NOT duplicate content or break the project.

What it does
------------
1. Reads ``spec/discipline/discipline.md`` (bundled into the wheel).
2. Renders ``skill/SKILL.md.template`` with the discipline body.
3. Substitutes ``{{placeholder}}`` tokens with Claude Code tool names.
4. Writes ``<project>/.claude/skills/inter-agent-channels/SKILL.md``.
5. Copies hook scripts to ``<project>/tools/sox-hooks/`` and makes them executable.
6. Updates ``<project>/.claude/settings.json``:
   - Registers ``PostToolUse``, ``Stop``, ``SubagentStop`` hooks.
   - Registers the SOX MCP server (SQLite backing store at ``.sox/messages.db``).
7. Inserts the bootstrap line into each ``<project>/.claude/agents/*.md`` file
   that does not already contain it.

Spec reference: CONTRACTS.md §7.1 (DisciplineRenderer) and §7.2 (EnforcerBinding).
"""

from __future__ import annotations

import importlib.resources
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Tool-name substitution map
# Claude Code MCP tool names follow the pattern mcp__<server>__<tool>
# ---------------------------------------------------------------------------

TOOL_SUBSTITUTIONS: dict[str, str] = {
    "{{send_tool}}": "mcp__sox__channels__send",
    "{{recv_tool}}": "mcp__sox__channels__recv",
    "{{subscribe_tool}}": "mcp__sox__channels__subscribe",
    "{{list_tool}}": "mcp__sox__channels__list_channels",
    # discipline.md also uses {{send_tool}} inside code blocks; handled by the
    # same substitution pass.
}

# The one-line bootstrap snippet inserted into agent system prompts.
# CONTRACTS.md §2 / USAGE.md §1.3 — exactly one line.
BOOTSTRAP_LINE = (
    "For coordination with other agents (clarification, broadcasts, peer questions), "
    "load the `inter-agent-channels` skill when blocked, broadcasting, or seeking "
    "peer input."
)

# Sentinel used to detect whether the bootstrap line is already present.
# We match on the unique substring rather than the exact full line so minor
# whitespace / line-ending variations don't cause duplication.
_BOOTSTRAP_SENTINEL = "load the `inter-agent-channels` skill"

# MCP server name registered in settings.json
_MCP_SERVER_NAME = "sox"

# Default backing-store path relative to the project root
_DEFAULT_DB_RELPATH = ".sox/messages.db"

# Hooks registered in settings.json
_HOOK_EVENTS = ["PostToolUse", "Stop", "SubagentStop"]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _skills_dir(project_dir: Path) -> Path:
    return project_dir / ".claude" / "skills" / "inter-agent-channels"


def _hooks_install_dir(project_dir: Path) -> Path:
    return project_dir / "tools" / "sox-hooks"


def _settings_path(project_dir: Path) -> Path:
    return project_dir / ".claude" / "settings.json"


def _mcp_json_path(project_dir: Path) -> Path:
    return project_dir / ".mcp.json"


def _agents_dir(project_dir: Path) -> Path:
    return project_dir / ".claude" / "agents"


# ---------------------------------------------------------------------------
# Bundled resource helpers
# ---------------------------------------------------------------------------


def _bundled_discipline() -> str:
    """Return the contents of the bundled ``spec/discipline/discipline.md``."""
    try:
        # Installed wheel: spec/ is under sox_protocol package data
        pkg_ref = importlib.resources.files("sox_protocol")
        discipline_path = pkg_ref / "spec" / "discipline" / "discipline.md"
        return discipline_path.read_text(encoding="utf-8")
    except (FileNotFoundError, TypeError):
        pass

    # Development layout: walk up from this file to the repo root
    here = Path(__file__).parent
    for ancestor in [here, *here.parents]:
        candidate = ancestor / "spec" / "discipline" / "discipline.md"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")

    raise FileNotFoundError(
        "Cannot locate spec/discipline/discipline.md. "
        "If running from a source checkout, ensure the repo root contains spec/. "
        "If running from a wheel, file a bug — the wheel may be missing package data."
    )


def _bundled_template() -> str:
    """Return the contents of ``skill/SKILL.md.template``."""
    template_path = Path(__file__).parent / "skill" / "SKILL.md.template"
    return template_path.read_text(encoding="utf-8")


def _hook_source_dir() -> Path:
    """Return the directory containing the bundled hook shell scripts."""
    return Path(__file__).parent / "hooks"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _substitute_placeholders(text: str) -> str:
    """Replace all ``{{placeholder}}`` tokens with Claude Code tool names."""
    for placeholder, tool_name in TOOL_SUBSTITUTIONS.items():
        text = text.replace(placeholder, tool_name)
    return text


def render_skill_md() -> str:
    """Render the full SKILL.md content ready for writing to disk.

    Returns:
        The rendered Markdown string with frontmatter and substituted body.
    """
    template = _bundled_template()
    discipline_body = _bundled_discipline()
    substituted_body = _substitute_placeholders(discipline_body)
    skill_md = template.replace("{{discipline_body}}", substituted_body)
    return skill_md


# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------


def _write_skill(project_dir: Path, *, dry_run: bool = False) -> bool:
    """Write SKILL.md. Returns True if the file was written (new or changed)."""
    skill_dir = _skills_dir(project_dir)
    skill_file = skill_dir / "SKILL.md"

    content = render_skill_md()

    if skill_file.exists() and skill_file.read_text(encoding="utf-8") == content:
        return False  # already up-to-date

    if not dry_run:
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(content, encoding="utf-8")
    return True


def _write_hooks(project_dir: Path, *, dry_run: bool = False) -> bool:
    """Copy hook scripts to <project>/tools/sox-hooks/. Returns True if any changed."""
    src_dir = _hook_source_dir()
    dst_dir = _hooks_install_dir(project_dir)

    changed = False
    for hook_file in src_dir.glob("*.sh"):
        dst_file = dst_dir / hook_file.name
        src_content = hook_file.read_bytes()

        if dst_file.exists() and dst_file.read_bytes() == src_content:
            continue  # already identical

        if not dry_run:
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hook_file, dst_file)
            # Ensure executable bits are set
            current_mode = dst_file.stat().st_mode
            dst_file.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        changed = True

    return changed


def _load_settings(settings_path: Path) -> dict[str, Any]:
    """Load settings.json, returning an empty dict if the file does not exist."""
    if not settings_path.exists():
        return {}
    raw = settings_path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)  # type: ignore[no-any-return]


def _build_hook_entry(project_dir: Path, event: str) -> dict[str, Any]:
    """Construct a single hook entry for settings.json (Claude Code ≥0.2 format)."""
    hook_script_name = _event_to_script_name(event)
    hook_path = _hooks_install_dir(project_dir) / hook_script_name
    return {
        "matcher": "",
        "hooks": [{"type": "command", "command": str(hook_path)}],
    }


def _event_to_script_name(event: str) -> str:
    """Map a hook event name to the corresponding shell script filename."""
    mapping = {
        "PostToolUse": "post_tool_use.sh",
        "Stop": "stop.sh",
        "SubagentStop": "stop.sh",
    }
    return mapping.get(event, f"{event.lower()}.sh")


def _update_mcp_json(project_dir: Path, *, dry_run: bool = False) -> bool:
    """Idempotently write/update .mcp.json with the SOX server entry."""
    mcp_json_path = _mcp_json_path(project_dir)
    existing: dict[str, Any] = {}
    if mcp_json_path.exists():
        raw = mcp_json_path.read_text(encoding="utf-8").strip()
        if raw:
            existing = json.loads(raw)
    original = json.dumps(existing, sort_keys=True)

    servers: dict[str, Any] = existing.setdefault("mcpServers", {})
    if _MCP_SERVER_NAME not in servers:
        db_path = str(project_dir / _DEFAULT_DB_RELPATH)
        servers[_MCP_SERVER_NAME] = {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "sox_protocol.core.mcp_server"],
            "env": {
                "SOX_BACKING_STORE": f"sqlite:///{db_path}",
            },
        }

    if json.dumps(existing, sort_keys=True) == original:
        return False

    if not dry_run:
        mcp_json_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return True


def _update_settings(project_dir: Path, *, dry_run: bool = False) -> bool:
    """Idempotently update .claude/settings.json. Returns True if changed."""
    settings_path = _settings_path(project_dir)
    settings = _load_settings(settings_path)
    original = json.dumps(settings, sort_keys=True)

    # --- Hooks ---
    hooks_section: dict[str, Any] = settings.setdefault("hooks", {})
    for event in _HOOK_EVENTS:
        hook_entry = _build_hook_entry(project_dir, event)
        target_cmd = hook_entry["hooks"][0]["command"]
        # Migrate: remove any old-format entries (bare {"type","command"}) for our script
        event_hooks_raw: list[dict[str, Any]] = hooks_section.setdefault(event, [])
        hooks_section[event] = [
            h for h in event_hooks_raw
            if h.get("command") != target_cmd  # drop old-format entries for our script
        ]
        event_hooks = hooks_section[event]
        # Idempotency: skip if new-format entry already present
        already_registered = any(
            any(h2.get("command") == target_cmd for h2 in h.get("hooks", []))
            for h in event_hooks
        )
        if not already_registered:
            event_hooks.append(hook_entry)

    # --- MCP server ---
    mcp_servers: dict[str, Any] = settings.setdefault("mcpServers", {})
    if _MCP_SERVER_NAME not in mcp_servers:
        db_path = str(project_dir / _DEFAULT_DB_RELPATH)
        mcp_servers[_MCP_SERVER_NAME] = {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "sox_protocol.core.mcp_server"],
            "env": {
                "SOX_BACKING_STORE": f"sqlite:///{db_path}",
            },
        }

    # --- Explicit allowlist entry ---
    # Ensures the server is callable in all permission modes, not just 'auto'.
    allowed: list[dict[str, Any]] = settings.setdefault("allowedMcpServers", [])
    if not any(e.get("serverName") == _MCP_SERVER_NAME for e in allowed):
        allowed.append({"serverName": _MCP_SERVER_NAME})

    updated = json.dumps(settings, sort_keys=True)
    if updated == original:
        return False

    if not dry_run:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return True


def _insert_bootstrap(project_dir: Path, *, dry_run: bool = False) -> list[Path]:
    """Insert bootstrap line into agent .md files that lack it.

    Returns:
        List of Path objects for files that were modified (or would be if dry_run).
    """
    agents_dir = _agents_dir(project_dir)
    if not agents_dir.exists():
        return []

    modified: list[Path] = []
    for agent_file in sorted(agents_dir.glob("*.md")):
        content = agent_file.read_text(encoding="utf-8")
        if _BOOTSTRAP_SENTINEL in content:
            continue  # already present — idempotent

        # Append bootstrap line as a new paragraph at the end of the file
        separator = "\n\n" if content and not content.endswith("\n\n") else "\n"
        new_content = content.rstrip("\n") + separator + BOOTSTRAP_LINE + "\n"

        if not dry_run:
            agent_file.write_text(new_content, encoding="utf-8")
        modified.append(agent_file)

    return modified


# ---------------------------------------------------------------------------
# Public install entry point
# ---------------------------------------------------------------------------


def install(project_dir: Path | None = None, *, verbose: bool = True) -> None:
    """Install the SOX Claude Code adapter into *project_dir*.

    Idempotent: safe to call multiple times.  Only writes files when content
    has actually changed.

    Args:
        project_dir: Root of the target Claude Code project.  Defaults to
            ``Path.cwd()``.
        verbose: When ``True``, print a summary of actions taken to stdout.
    """
    if project_dir is None:
        project_dir = Path.cwd()
    project_dir = project_dir.resolve()

    actions: list[str] = []

    # 1. Skill
    if _write_skill(project_dir):
        actions.append(f"  Wrote SKILL.md → {_skills_dir(project_dir) / 'SKILL.md'}")
    else:
        actions.append(f"  SKILL.md already up-to-date")

    # 2. Hooks
    if _write_hooks(project_dir):
        actions.append(f"  Wrote hook scripts → {_hooks_install_dir(project_dir)}/")
    else:
        actions.append(f"  Hook scripts already up-to-date")

    # 3. .mcp.json  (project MCP server discovery — read by Claude Code at startup)
    if _update_mcp_json(project_dir):
        actions.append(f"  Written {_mcp_json_path(project_dir)}")
    else:
        actions.append(f"  .mcp.json already up-to-date")

    # 4. settings.json  (hooks + allowedMcpServers)
    if _update_settings(project_dir):
        actions.append(f"  Updated {_settings_path(project_dir)}")
    else:
        actions.append(f"  settings.json already up-to-date")

    # 5. Bootstrap lines
    modified_agents = _insert_bootstrap(project_dir)
    if modified_agents:
        for af in modified_agents:
            actions.append(f"  Inserted bootstrap line → {af}")
    else:
        actions.append("  Bootstrap lines already present (or no agent files found)")

    if verbose:
        print("SOX Protocol — Claude Code adapter installed.")
        for action in actions:
            print(action)


# ---------------------------------------------------------------------------
# __main__ support: python -m sox_protocol.adapters.runtimes.claude_code install
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for ``python -m sox_protocol.adapters.runtimes.claude_code``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m sox_protocol.adapters.runtimes.claude_code",
        description="Install the SOX inter-agent-channels skill into a Claude Code project.",
    )
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Install the SOX adapter.")
    install_parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Path to the Claude Code project root (default: current directory).",
    )
    install_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output.",
    )

    args = parser.parse_args(argv)

    if args.command == "install":
        install(project_dir=args.project_dir, verbose=not args.quiet)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
