# SPDX-License-Identifier: Apache-2.0
"""``sox-protocol config`` CLI subcommand.

Print the resolved SOX configuration for the current directory as JSON.
Surfaces:

  - sox-protocol version
  - resolved agent_id (and the source it came from)
  - resolved SOX_BACKING_STORE URI
  - parsed SQLite db path (when applicable) — and whether the file exists
  - SOX_HEARTBEAT_TTL_DEFAULT / SOX_AGENT_ID_SOURCE / SOX_FORCE_DRAIN_ON_STOP
    env values (whether from process env or .mcp.json env)
  - .mcp.json discovery path (when found)
  - .claude/settings.json registration state for the SOX server + hooks
  - permissions.allow entries that match SOX MCP tool names
  - skill SKILL.md presence + size

Pure read-only — never writes anywhere.  Useful for `sox-protocol config | jq …`
and for posting a config snapshot when filing bugs.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sox_protocol import __version__
from sox_protocol.cli._session import (
    discover_mcp_env,
    resolve_agent_id,
    resolve_backing_store_uri,
)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _resolve_db_path(uri: str) -> dict[str, Any]:
    """Pull the SQLite path out of a ``sqlite:///...`` URI when present."""
    if not uri.startswith("sqlite://"):
        return {"scheme": uri.split(":", 1)[0] if ":" in uri else None, "path": None}
    parsed = urlparse(uri)
    raw_path = parsed.path or uri[len("sqlite://"):]
    if raw_path == "/:memory:" or raw_path == ":memory:":
        return {"scheme": "sqlite", "path": ":memory:", "exists": False}
    abs_path = raw_path
    return {
        "scheme": "sqlite",
        "path": abs_path,
        "exists": Path(abs_path).is_file() if abs_path else False,
    }


def _discover_mcp_json_path(start: Path) -> Path | None:
    for ancestor in [start, *start.parents]:
        candidate = ancestor / ".mcp.json"
        if candidate.is_file():
            return candidate
    return None


def _sox_permission_entries(allow: list[Any]) -> list[str]:
    return [str(e) for e in allow if isinstance(e, str) and e.startswith("mcp__sox__")]


def _build_config(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    mcp_env = discover_mcp_env(project_dir)
    mcp_json_path = _discover_mcp_json_path(project_dir)
    backing_store_uri = resolve_backing_store_uri(project_dir)
    agent_id = resolve_agent_id(None, project_dir=project_dir)

    settings_path = project_dir / ".claude" / "settings.json"
    settings = _read_json(settings_path)
    mcp_servers = (settings or {}).get("mcpServers", {})
    sox_server = mcp_servers.get("sox") if isinstance(mcp_servers, dict) else None
    hooks = (settings or {}).get("hooks", {})
    perms_block = (settings or {}).get("permissions", {})
    allow_list = perms_block.get("allow", []) if isinstance(perms_block, dict) else []

    skill_path = project_dir / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md"

    # Effective env values — process env wins, then .mcp.json.
    def _eff(key: str) -> str | None:
        v = os.environ.get(key)
        if v is not None and v != "":
            return v
        return mcp_env.get(key) or None

    return {
        "sox_protocol_version": __version__,
        "project_dir": str(project_dir),
        "agent_id": agent_id,
        "backing_store": {
            "uri": backing_store_uri,
            **_resolve_db_path(backing_store_uri),
        },
        "env": {
            "SOX_AGENT_ID_SOURCE": _eff("SOX_AGENT_ID_SOURCE"),
            "SOX_AGENT_ID": _eff("SOX_AGENT_ID"),
            "CLAUDE_AGENT_NAME": _eff("CLAUDE_AGENT_NAME"),
            "SOX_AGENT_NAME": _eff("SOX_AGENT_NAME"),
            "SOX_HEARTBEAT_TTL_DEFAULT": _eff("SOX_HEARTBEAT_TTL_DEFAULT"),
            "SOX_FORCE_DRAIN_ON_STOP": _eff("SOX_FORCE_DRAIN_ON_STOP"),
        },
        "discovery": {
            "mcp_json_path": str(mcp_json_path) if mcp_json_path else None,
            "settings_json_path": str(settings_path) if settings_path.exists() else None,
            "skill_md_path": str(skill_path) if skill_path.exists() else None,
        },
        "claude_code": {
            "mcp_server_registered": sox_server is not None,
            "mcp_server_entry": sox_server,
            "hook_events": sorted(hooks.keys()) if isinstance(hooks, dict) else [],
            "permissions_allow_sox_tools": (
                _sox_permission_entries(allow_list) if isinstance(allow_list, list) else []
            ),
        },
        "skill": {
            "present": skill_path.is_file(),
            "size_bytes": skill_path.stat().st_size if skill_path.is_file() else None,
        },
    }


def _config_command(args: argparse.Namespace) -> int:
    project_dir = (args.project_dir or Path.cwd()).resolve()
    config = _build_config(project_dir)
    print(json.dumps(config, indent=2 if not args.compact else None, default=str, ensure_ascii=False))
    return 0


def add_config_subcommand(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Register the ``config`` subcommand."""
    parser = subparsers.add_parser(
        "config",
        help="Print the resolved SOX configuration as JSON.",
        description=(
            "Resolve and print the effective SOX configuration for the current "
            "directory: agent_id, backing-store URI, .mcp.json discovery, "
            "Claude Code registration, skill presence, and relevant env vars. "
            "Read-only — useful for diagnostics and bug reports."
        ),
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Path to the project root (default: current directory).",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit single-line JSON.",
    )
    parser.set_defaults(func=_config_command)
