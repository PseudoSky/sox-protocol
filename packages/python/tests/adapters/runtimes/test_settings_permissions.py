# SPDX-License-Identifier: Apache-2.0
"""Tests for the SOX MCP tool permissions injection in .claude/settings.json.

Covers ``_update_settings`` and ``install`` with and without the
``inject_permissions`` flag, including merge-with-existing-entries
idempotency.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sox_protocol.adapters.runtimes.claude_code.install import (
    _SOX_MCP_TOOL_NAMES,
    _update_settings,
    install,
)


def _read_settings(project_dir: Path) -> dict:
    return json.loads((project_dir / ".claude" / "settings.json").read_text())


# ---------------------------------------------------------------------------
# Default behavior — all 15 SOX tools added to permissions.allow
# ---------------------------------------------------------------------------


def test_install_default_injects_all_sox_tools(tmp_path: Path) -> None:
    install(project_dir=tmp_path, verbose=False)
    s = _read_settings(tmp_path)
    allow = s.get("permissions", {}).get("allow", [])
    for tool in _SOX_MCP_TOOL_NAMES:
        assert tool in allow, f"missing tool: {tool}"


def test_install_no_permissions_omits_block(tmp_path: Path) -> None:
    install(project_dir=tmp_path, verbose=False, inject_permissions=False)
    s = _read_settings(tmp_path)
    assert "permissions" not in s


# ---------------------------------------------------------------------------
# Merge — preserves existing user entries, adds only the missing SOX tools
# ---------------------------------------------------------------------------


def test_merge_preserves_user_entries(tmp_path: Path) -> None:
    """Pre-existing permissions.allow entries are preserved."""
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    user_settings = {
        "permissions": {
            "allow": ["Bash(*)", "Read(*)", "mcp__some-other-server__tool"],
        }
    }
    (settings_dir / "settings.json").write_text(json.dumps(user_settings))

    install(project_dir=tmp_path, verbose=False)
    s = _read_settings(tmp_path)
    allow = s["permissions"]["allow"]

    # User's entries kept
    assert "Bash(*)" in allow
    assert "Read(*)" in allow
    assert "mcp__some-other-server__tool" in allow
    # SOX entries appended
    assert "mcp__sox__channels__send" in allow
    assert "mcp__sox__group__create" in allow


def test_idempotent_does_not_duplicate(tmp_path: Path) -> None:
    """Re-running install does not duplicate SOX tool entries."""
    install(project_dir=tmp_path, verbose=False)
    install(project_dir=tmp_path, verbose=False)
    s = _read_settings(tmp_path)
    allow = s["permissions"]["allow"]
    # No tool should appear twice
    for tool in _SOX_MCP_TOOL_NAMES:
        assert allow.count(tool) == 1, f"{tool} appears {allow.count(tool)} times"


def test_partial_pre_existing_sox_tool_no_duplicate(tmp_path: Path) -> None:
    """If the user already has SOME SOX tools allowed, others get added without duplicating."""
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["mcp__sox__channels__send"]},
    }))

    install(project_dir=tmp_path, verbose=False)
    s = _read_settings(tmp_path)
    allow = s["permissions"]["allow"]
    # Original entry kept exactly once
    assert allow.count("mcp__sox__channels__send") == 1
    # The missing tools were appended
    assert "mcp__sox__channels__recv" in allow


def test_install_creates_permissions_block_if_missing(tmp_path: Path) -> None:
    """Settings without a permissions block get one created."""
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(json.dumps({"hooks": {}}))

    install(project_dir=tmp_path, verbose=False)
    s = _read_settings(tmp_path)
    assert "permissions" in s
    assert isinstance(s["permissions"]["allow"], list)


# ---------------------------------------------------------------------------
# CLI dispatch — sox-protocol install --no-permissions
# ---------------------------------------------------------------------------


def test_cli_install_no_permissions_flag_dispatches(tmp_path: Path) -> None:
    from sox_protocol.cli.install import install_command

    rc = install_command(argparse.Namespace(
        project_dir=tmp_path,
        quiet=True,
        auto_subscribe=False,
        default_channels=None,
        no_permissions=True,
    ))
    assert rc == 0
    s = _read_settings(tmp_path)
    assert "permissions" not in s


def test_cli_install_default_dispatches_with_permissions(tmp_path: Path) -> None:
    from sox_protocol.cli.install import install_command

    rc = install_command(argparse.Namespace(
        project_dir=tmp_path,
        quiet=True,
        auto_subscribe=False,
        default_channels=None,
        no_permissions=False,
    ))
    assert rc == 0
    s = _read_settings(tmp_path)
    assert len(s["permissions"]["allow"]) >= len(_SOX_MCP_TOOL_NAMES)


# ---------------------------------------------------------------------------
# Pure _update_settings — corrupted permissions.allow doesn't crash
# ---------------------------------------------------------------------------


def test_update_settings_handles_non_list_allow_gracefully(tmp_path: Path) -> None:
    """If permissions.allow is somehow not a list (user error), no crash; we leave it alone."""
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(json.dumps({
        "permissions": {"allow": "this should be a list but isn't"},
    }))

    # Should not raise
    _update_settings(tmp_path)
    s = _read_settings(tmp_path)
    # allow is left as the string the user had — we don't try to fix corrupt input
    assert s["permissions"]["allow"] == "this should be a list but isn't"
