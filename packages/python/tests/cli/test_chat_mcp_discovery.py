# SPDX-License-Identifier: Apache-2.0
"""Tests for the .mcp.json auto-discovery in `sox-protocol chat`.

The Claude Code installer writes ``.mcp.json`` at the project root with
``mcpServers.sox.env`` containing ``SOX_BACKING_STORE`` (project-local
SQLite path), ``SOX_AGENT_ID_SOURCE``, etc. Without auto-discovery, a
``sox-protocol chat`` session in the same project would spawn its own
MCP server with NO env (defaulting to ``memory://``), silently using a
different backing store than the project's Claude Code agents.

These tests cover ``_discover_mcp_env`` — the pure helper — for cwd,
walk-up, no-file, malformed-file, and missing-block cases.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sox_protocol.cli.chat import _discover_mcp_env


def _write_mcp_json(dir: Path, env: dict[str, str] | None) -> None:
    """Helper: write a .mcp.json with optional sox env block."""
    cfg: dict[str, object]
    if env is None:
        cfg = {"mcpServers": {}}
    else:
        cfg = {"mcpServers": {"sox": {"env": env}}}
    (dir / ".mcp.json").write_text(json.dumps(cfg))


def test_discovers_env_from_cwd(tmp_path: Path) -> None:
    """A .mcp.json directly in the start dir is found and parsed."""
    _write_mcp_json(
        tmp_path,
        {"SOX_BACKING_STORE": "sqlite:///foo/bar.db", "SOX_AGENT_ID_SOURCE": "claude_code_agent_name"},
    )
    env = _discover_mcp_env(tmp_path)
    assert env == {
        "SOX_BACKING_STORE": "sqlite:///foo/bar.db",
        "SOX_AGENT_ID_SOURCE": "claude_code_agent_name",
    }


def test_walks_up_to_find_mcp_json(tmp_path: Path) -> None:
    """Discovery walks parents — running ``sox-protocol chat`` from a subdir works."""
    project = tmp_path / "project"
    subdir = project / "src" / "deeply" / "nested"
    subdir.mkdir(parents=True)
    _write_mcp_json(project, {"SOX_BACKING_STORE": "sqlite:///up/there.db"})
    env = _discover_mcp_env(subdir)
    assert env == {"SOX_BACKING_STORE": "sqlite:///up/there.db"}


def test_no_mcp_json_returns_empty(tmp_path: Path) -> None:
    """Missing .mcp.json means no env discovered — returns ``{}``, not error."""
    env = _discover_mcp_env(tmp_path)
    assert env == {}


def test_malformed_mcp_json_returns_empty(tmp_path: Path) -> None:
    """Invalid JSON is logged and skipped — returns ``{}``."""
    (tmp_path / ".mcp.json").write_text("{this is not json")
    env = _discover_mcp_env(tmp_path)
    assert env == {}


def test_missing_sox_block_returns_empty(tmp_path: Path) -> None:
    """A .mcp.json without mcpServers.sox.env returns ``{}``."""
    _write_mcp_json(tmp_path, None)  # writes mcpServers: {} only
    env = _discover_mcp_env(tmp_path)
    assert env == {}


def test_empty_sox_env_block_returns_empty(tmp_path: Path) -> None:
    """An explicitly-empty env block returns ``{}`` (matches "no env discovered")."""
    _write_mcp_json(tmp_path, {})  # env: {}
    env = _discover_mcp_env(tmp_path)
    assert env == {}


def test_sox_env_values_coerced_to_str(tmp_path: Path) -> None:
    """Non-string values in the JSON are coerced to str (subprocess env requires str)."""
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"sox": {"env": {"SOX_PORT": 8765, "SOX_DEBUG": True}}}})
    )
    env = _discover_mcp_env(tmp_path)
    assert env == {"SOX_PORT": "8765", "SOX_DEBUG": "True"}


def test_first_ancestor_wins(tmp_path: Path) -> None:
    """If two ancestors both have .mcp.json, the nearest one wins."""
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    _write_mcp_json(outer, {"SOX_BACKING_STORE": "sqlite:///OUTER.db"})
    _write_mcp_json(inner, {"SOX_BACKING_STORE": "sqlite:///INNER.db"})
    env = _discover_mcp_env(inner)
    assert env == {"SOX_BACKING_STORE": "sqlite:///INNER.db"}


def test_discovers_sox_under_alternate_key_via_command_signature(tmp_path: Path) -> None:
    """A SOX server registered under a non-default key is still found.

    Reproduces the claude-agents collision workaround: the project already
    has a ``sox`` MCP server entry that's a different tool, so the SOX
    install registers under ``sox-protocol``.  The TUI must still find it.
    """
    cfg = {
        "mcpServers": {
            "sox": {
                "type": "stdio",
                "command": "/some/other/tool",
                "env": {"OTHER_TOOL_FLAG": "1"},
            },
            "sox-protocol": {
                "type": "stdio",
                "command": "sox-mcp-server",
                "env": {"SOX_BACKING_STORE": "sqlite:///alt.db"},
            },
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(cfg))
    env = _discover_mcp_env(tmp_path)
    assert env == {"SOX_BACKING_STORE": "sqlite:///alt.db"}


def test_discovers_sox_via_args_signature(tmp_path: Path) -> None:
    """SOX server identified by ``args`` containing the module path."""
    cfg = {
        "mcpServers": {
            "my-custom-name": {
                "type": "stdio",
                "command": "/usr/bin/python3",
                "args": ["-m", "sox_protocol.core.mcp_server"],
                "env": {"SOX_BACKING_STORE": "sqlite:///arg.db"},
            }
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(cfg))
    env = _discover_mcp_env(tmp_path)
    assert env == {"SOX_BACKING_STORE": "sqlite:///arg.db"}


def test_discovers_sox_via_env_signature(tmp_path: Path) -> None:
    """SOX server identified solely by env containing SOX_BACKING_STORE."""
    cfg = {
        "mcpServers": {
            "anything": {
                "type": "stdio",
                "command": "/something/else",
                "env": {"SOX_BACKING_STORE": "sqlite:///env-sig.db"},
            }
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(cfg))
    env = _discover_mcp_env(tmp_path)
    assert env == {"SOX_BACKING_STORE": "sqlite:///env-sig.db"}


def test_default_sox_key_takes_precedence_when_both_present(tmp_path: Path) -> None:
    """If both ``sox`` and an alternate-key SOX server are present, the
    default key wins (matches the canonical install)."""
    cfg = {
        "mcpServers": {
            "sox": {
                "command": "sox-mcp-server",
                "env": {"SOX_BACKING_STORE": "sqlite:///default.db"},
            },
            "sox-protocol": {
                "command": "sox-mcp-server",
                "env": {"SOX_BACKING_STORE": "sqlite:///alt.db"},
            },
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(cfg))
    env = _discover_mcp_env(tmp_path)
    assert env == {"SOX_BACKING_STORE": "sqlite:///default.db"}


def test_user_agent_id_overrides_discovered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """SOX_AGENT_ID from --agent-id always wins over the discovered file value.

    Verified by importing chat_command and observing the assembled server_env;
    we mock ``run`` to capture the kwargs.
    """
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> None:
        captured.update(kwargs)

    _write_mcp_json(
        tmp_path,
        {"SOX_BACKING_STORE": "sqlite:///x.db", "SOX_AGENT_ID": "discovered-agent"},
    )
    monkeypatch.setattr("sox_protocol.cli.chat.run", fake_run)
    monkeypatch.chdir(tmp_path)

    import argparse

    from sox_protocol.cli.chat import chat_command

    rc = chat_command(
        argparse.Namespace(
            agent_id="cli-agent",
            channel="#general",
            no_spawn=False,
            server_cmd=None,
        )
    )
    assert rc == 0
    server_env = captured["server_env"]
    assert isinstance(server_env, dict)
    assert server_env["SOX_AGENT_ID"] == "cli-agent"
    assert server_env["SOX_BACKING_STORE"] == "sqlite:///x.db"
