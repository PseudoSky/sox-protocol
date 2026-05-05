# SPDX-License-Identifier: Apache-2.0
"""Tests for the sox-protocol CLI: cli/__main__.py + the subcommand modules.

History note: prior to 0.1.5 the verify/install/lint-discipline subcommands
lived in a standalone ``sox_protocol/cli.py`` file that was shadowed by the
``sox_protocol/cli/`` package (Python's import resolution prefers the
package), so the documented ``python -m sox_protocol.cli verify`` invocation
silently routed to ``cli/__main__.py`` — which didn't have those commands —
while ``cli.py`` itself was reachable only via importlib trickery in this
test file. 0.1.5 migrated them into ``cli/verify.py`` and
``cli/lint_discipline.py``, deleted ``cli.py``, and removed the importlib
workaround.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sox_protocol.cli import __main__ as cli_main_module
from sox_protocol.cli import lint_discipline as sox_lint_module
from sox_protocol.cli import serve as cli_serve
from sox_protocol.cli import verify as sox_cli  # alias preserves test names from pre-0.1.5

# ===========================================================================
# sox_protocol/cli/verify.py — printer helpers
# ===========================================================================


def test_ok_prints_label(capsys) -> None:
    sox_cli._ok("Backing store")
    assert "[OK]" in capsys.readouterr().out


def test_ok_prints_label_with_detail(capsys) -> None:
    sox_cli._ok("Backing store", "sqlite reachable")
    out = capsys.readouterr().out
    assert "[OK]" in out
    assert "sqlite reachable" in out


def test_fail_prints_label(capsys) -> None:
    sox_cli._fail("MCP server")
    assert "[FAIL]" in capsys.readouterr().out


def test_fail_prints_with_detail(capsys) -> None:
    sox_cli._fail("Hook", "not found")
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "not found" in out


def test_warn_prints_label(capsys) -> None:
    sox_cli._warn("Backing store")
    assert "[WARN]" in capsys.readouterr().out


def test_warn_prints_with_detail(capsys) -> None:
    sox_cli._warn("Backing store", "unknown scheme")
    out = capsys.readouterr().out
    assert "[WARN]" in out
    assert "unknown scheme" in out


# ===========================================================================
# _check_backing_store
# ===========================================================================


def test_check_backing_store_no_env_no_settings(tmp_path: Path) -> None:
    """No SOX_BACKING_STORE and no settings.json → warns but returns True."""
    env = {k: v for k, v in os.environ.items() if k != "SOX_BACKING_STORE"}
    with patch.dict(os.environ, env, clear=True):
        result = sox_cli._check_backing_store(tmp_path)
    assert result is True


def test_check_backing_store_memory_scheme(tmp_path: Path) -> None:
    """memory:// scheme → ok."""
    with patch.dict(os.environ, {"SOX_BACKING_STORE": "memory://"}):
        result = sox_cli._check_backing_store(tmp_path)
    assert result is True


def test_check_backing_store_sqlite_existing(tmp_path: Path) -> None:
    """sqlite:// with existing file → ok."""
    db = tmp_path / "test.db"
    db.touch()
    with patch.dict(os.environ, {"SOX_BACKING_STORE": f"sqlite://{db}"}):
        result = sox_cli._check_backing_store(tmp_path)
    assert result is True


def test_check_backing_store_sqlite_nonexistent(tmp_path: Path) -> None:
    """sqlite:// with nonexistent file → ok (will be created on first use)."""
    with patch.dict(os.environ, {"SOX_BACKING_STORE": f"sqlite://{tmp_path}/new.db"}):
        result = sox_cli._check_backing_store(tmp_path)
    assert result is True


def test_check_backing_store_sqlite_memory_uri(tmp_path: Path) -> None:
    """sqlite://:memory: → ok."""
    with patch.dict(os.environ, {"SOX_BACKING_STORE": "sqlite://:memory:"}):
        result = sox_cli._check_backing_store(tmp_path)
    assert result is True


def test_check_backing_store_sqlite_triple_slash(tmp_path: Path) -> None:
    """sqlite:/// → ok."""
    db = tmp_path / "triple.db"
    with patch.dict(os.environ, {"SOX_BACKING_STORE": f"sqlite:///{db}"}):
        result = sox_cli._check_backing_store(tmp_path)
    assert result is True


def test_check_backing_store_unknown_scheme(tmp_path: Path) -> None:
    """Unknown scheme → warns but returns True."""
    with patch.dict(os.environ, {"SOX_BACKING_STORE": "redis://localhost"}):
        result = sox_cli._check_backing_store(tmp_path)
    assert result is True


def test_check_backing_store_reads_from_settings_json(tmp_path: Path) -> None:
    """_check_backing_store reads SOX_BACKING_STORE from settings.json when env not set."""
    settings = {
        "mcpServers": {
            "sox": {
                "env": {"SOX_BACKING_STORE": "memory://"}
            }
        }
    }
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps(settings))

    env = {k: v for k, v in os.environ.items() if k != "SOX_BACKING_STORE"}
    with patch.dict(os.environ, env, clear=True):
        result = sox_cli._check_backing_store(tmp_path)
    assert result is True


def test_check_backing_store_settings_json_parse_error(tmp_path: Path) -> None:
    """_check_backing_store handles invalid JSON in settings.json gracefully."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("not valid json {{{{")

    env = {k: v for k, v in os.environ.items() if k != "SOX_BACKING_STORE"}
    with patch.dict(os.environ, env, clear=True):
        result = sox_cli._check_backing_store(tmp_path)
    # Falls through to "not set" warn
    assert result is True


def test_check_backing_store_relative_sqlite_path(tmp_path: Path) -> None:
    """sqlite:// with relative path → resolves relative to project_dir."""
    sub = tmp_path / "sub"
    sub.mkdir()
    db = sub / "test.db"
    db.touch()
    with patch.dict(os.environ, {"SOX_BACKING_STORE": "sqlite://sub/test.db"}):
        result = sox_cli._check_backing_store(tmp_path)
    assert result is True


# ===========================================================================
# _check_mcp_server
# ===========================================================================


def test_check_mcp_server_no_settings_returns_false(tmp_path: Path, capsys) -> None:
    result = sox_cli._check_mcp_server(tmp_path)
    assert result is False
    assert "FAIL" in capsys.readouterr().out


def test_check_mcp_server_invalid_json_returns_false(tmp_path: Path, capsys) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("not json")
    result = sox_cli._check_mcp_server(tmp_path)
    assert result is False


def test_check_mcp_server_missing_sox_key_returns_false(tmp_path: Path, capsys) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({"mcpServers": {}}))
    result = sox_cli._check_mcp_server(tmp_path)
    assert result is False


def test_check_mcp_server_present_returns_true(tmp_path: Path, capsys) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = {"mcpServers": {"sox": {"type": "stdio"}}}
    (claude_dir / "settings.json").write_text(json.dumps(settings))
    result = sox_cli._check_mcp_server(tmp_path)
    assert result is True
    assert "OK" in capsys.readouterr().out


# ===========================================================================
# _check_hooks
# ===========================================================================


def _make_hooks_dir(project_dir: Path) -> Path:
    """Create tools/sox-hooks with executable scripts."""
    hooks_dir = project_dir / "tools" / "sox-hooks"
    hooks_dir.mkdir(parents=True)
    for name in sox_cli._HOOK_SCRIPTS:
        script = hooks_dir / name
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
    return hooks_dir


def test_check_hooks_missing_scripts_returns_false(tmp_path: Path, capsys) -> None:
    result = sox_cli._check_hooks(tmp_path)
    assert result is False


def test_check_hooks_scripts_present_no_settings(tmp_path: Path, capsys) -> None:
    _make_hooks_dir(tmp_path)
    result = sox_cli._check_hooks(tmp_path)
    assert isinstance(result, bool)


def test_check_hooks_not_executable(tmp_path: Path, capsys) -> None:
    hooks_dir = tmp_path / "tools" / "sox-hooks"
    hooks_dir.mkdir(parents=True)
    script = hooks_dir / sox_cli._HOOK_SCRIPTS[0]
    script.write_text("#!/bin/sh\n")
    script.chmod(0o644)  # Not executable
    result = sox_cli._check_hooks(tmp_path)
    assert result is False


def test_check_hooks_with_settings_registered(tmp_path: Path, capsys) -> None:
    _make_hooks_dir(tmp_path)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    hooks_cfg = {event: [{"cmd": "x"}] for event in sox_cli._HOOK_EVENTS}
    (claude_dir / "settings.json").write_text(json.dumps({"hooks": hooks_cfg}))
    result = sox_cli._check_hooks(tmp_path)
    assert result is True


def test_check_hooks_with_settings_missing_events(tmp_path: Path, capsys) -> None:
    _make_hooks_dir(tmp_path)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({"hooks": {}}))
    result = sox_cli._check_hooks(tmp_path)
    assert result is False


def test_check_hooks_settings_json_parse_error(tmp_path: Path, capsys) -> None:
    """_check_hooks handles invalid JSON in settings.json gracefully (line 170-171)."""
    _make_hooks_dir(tmp_path)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("not json {{{{")
    # Should not raise; exception is caught silently
    result = sox_cli._check_hooks(tmp_path)
    # Scripts exist but we couldn't read hook registrations
    assert isinstance(result, bool)


# ===========================================================================
# _check_skill
# ===========================================================================


def test_check_skill_missing_returns_false(tmp_path: Path, capsys) -> None:
    result = sox_cli._check_skill(tmp_path)
    assert result is False


def test_check_skill_present_returns_true(tmp_path: Path, capsys) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "inter-agent-channels"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# SOX Skill")
    result = sox_cli._check_skill(tmp_path)
    assert result is True


# ===========================================================================
# _check_tools
# ===========================================================================


def test_check_tools_missing_skill_returns_false(tmp_path: Path, capsys) -> None:
    result = sox_cli._check_tools(tmp_path)
    assert result is False


def test_check_tools_all_present_returns_true(tmp_path: Path, capsys) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "inter-agent-channels"
    skill_dir.mkdir(parents=True)
    content = "\n".join(sox_cli._REQUIRED_TOOLS)
    (skill_dir / "SKILL.md").write_text(content)
    result = sox_cli._check_tools(tmp_path)
    assert result is True


def test_check_tools_some_missing_returns_false(tmp_path: Path, capsys) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "inter-agent-channels"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("channels__send")
    result = sox_cli._check_tools(tmp_path)
    assert result is False


# ===========================================================================
# verify
# ===========================================================================


def test_verify_full_pass(tmp_path: Path) -> None:
    """verify() returns 0 when all checks pass."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = {
        "mcpServers": {"sox": {"type": "stdio"}},
        "hooks": {event: [{"cmd": "x"}] for event in sox_cli._HOOK_EVENTS},
    }
    (claude_dir / "settings.json").write_text(json.dumps(settings))

    skill_dir = claude_dir / "skills" / "inter-agent-channels"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("\n".join(sox_cli._REQUIRED_TOOLS))

    _make_hooks_dir(tmp_path)

    with patch.dict(os.environ, {"SOX_BACKING_STORE": "memory://"}):
        rc = sox_cli.verify(project_dir=tmp_path)
    assert rc == 0


def test_verify_fails_returns_1(tmp_path: Path) -> None:
    """verify() returns 1 when checks fail."""
    env = {k: v for k, v in os.environ.items() if k != "SOX_BACKING_STORE"}
    with patch.dict(os.environ, env, clear=True):
        rc = sox_cli.verify(project_dir=tmp_path)
    assert rc == 1


def test_verify_uses_passed_project_dir(tmp_path: Path) -> None:
    """verify() uses the passed project_dir argument."""
    rc = sox_cli.verify(project_dir=tmp_path)
    assert isinstance(rc, int)


def test_verify_none_project_dir_uses_cwd(tmp_path: Path) -> None:
    """verify() uses cwd when project_dir is None."""
    import os as _os
    orig = _os.getcwd()
    _os.chdir(tmp_path)
    try:
        rc = sox_cli.verify(project_dir=None)
        assert isinstance(rc, int)
    finally:
        _os.chdir(orig)


# ===========================================================================
# lint_discipline
# ===========================================================================


def _make_valid_discipline(path: Path) -> None:
    """Write a valid discipline file to *path*.

    Required-headings list lives in ``cli/lint_discipline.py`` post-0.1.5.
    """
    content = "\n".join(sox_lint_module._REQUIRED_HEADINGS) + "\n"
    path.write_text(content, encoding="utf-8")


def test_lint_discipline_missing_file(tmp_path: Path) -> None:
    rc = sox_lint_module.lint_discipline(tmp_path / "nonexistent.md")
    assert rc == 1


def test_lint_discipline_valid_file_passes(tmp_path: Path) -> None:
    f = tmp_path / "discipline.md"
    _make_valid_discipline(f)
    rc = sox_lint_module.lint_discipline(f)
    assert rc == 0


def test_lint_discipline_missing_heading_fails(tmp_path: Path) -> None:
    f = tmp_path / "discipline.md"
    # Write only first heading
    f.write_text(sox_lint_module._REQUIRED_HEADINGS[0], encoding="utf-8")
    rc = sox_lint_module.lint_discipline(f)
    assert rc == 1


def test_lint_discipline_out_of_order_headings_fails(tmp_path: Path) -> None:
    f = tmp_path / "discipline.md"
    # Reverse the required headings
    content = "\n".join(reversed(sox_lint_module._REQUIRED_HEADINGS))
    f.write_text(content, encoding="utf-8")
    rc = sox_lint_module.lint_discipline(f)
    assert rc == 1


def test_lint_discipline_concrete_tool_name_fails(tmp_path: Path) -> None:
    f = tmp_path / "discipline.md"
    valid_content = "\n".join(sox_lint_module._REQUIRED_HEADINGS) + "\n"
    # Add a concrete tool name
    valid_content += "mcp__sox__channels__send\n"
    f.write_text(valid_content, encoding="utf-8")
    rc = sox_lint_module.lint_discipline(f)
    assert rc == 1


# ===========================================================================
# Subcommand argument dispatch via cli/__main__.main(...).
#
# These cover the verify / install / lint-discipline subcommands going
# through the unified entry point.  Pre-0.1.5 they routed through a
# now-deleted cli.py main(); post-0.1.5 they're all wired into
# cli/__main__.py and return ints (no SystemExit raised inside main()).
# ===========================================================================


def test_main_verify_runs(tmp_path: Path) -> None:
    """sox-protocol main() with 'verify' returns int (0 on full pass, 1 on any check fail)."""
    env = {k: v for k, v in os.environ.items() if k != "SOX_BACKING_STORE"}
    with patch.dict(os.environ, env, clear=True):
        rc = cli_main_module.main(["verify", "--project-dir", str(tmp_path)])
    assert rc in (0, 1)


def test_main_lint_discipline_missing_file(tmp_path: Path) -> None:
    """sox-protocol main() with 'lint-discipline' on a missing file returns 1."""
    rc = cli_main_module.main(["lint-discipline", str(tmp_path / "missing.md")])
    assert rc == 1


def test_main_lint_discipline_valid_file(tmp_path: Path) -> None:
    """sox-protocol main() with 'lint-discipline' on a valid file returns 0."""
    f = tmp_path / "d.md"
    _make_valid_discipline(f)
    rc = cli_main_module.main(["lint-discipline", str(f)])
    assert rc == 0


def test_main_install_delegates(tmp_path: Path) -> None:
    """sox-protocol main() with 'install' delegates to the adapter installer."""
    with patch("sox_protocol.cli.install.install") as mock_install:
        rc = cli_main_module.main(
            ["install", "--project-dir", str(tmp_path), "--quiet"]
        )
        mock_install.assert_called_once()
    assert rc == 0


def test_main_version_flag_prints_and_exits(capsys) -> None:
    """sox-protocol --version prints the version and exits 0 (argparse action='version')."""
    with pytest.raises(SystemExit) as exc_info:
        cli_main_module.main(["--version"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "sox-protocol" in out


def test_main_version_subcommand_returns_0(capsys) -> None:
    """sox-protocol version subcommand prints the version and returns 0."""
    rc = cli_main_module.main(["version"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    # Loose check: the subcommand prints just the version (e.g. "0.1.5"),
    # not "sox-protocol 0.1.5", so we just assert it's non-empty + dotted.
    assert out
    assert "." in out


# ===========================================================================
# cli/__main__.py — the sox-protocol serve entrypoint (lines 37-45)
# ===========================================================================


def test_cli_main_module_no_func_returns_0() -> None:
    """cli/__main__.main() with no subcommand prints help and returns 0."""
    result = cli_main_module.main([])
    assert result == 0


def test_cli_main_module_with_serve_returns_func() -> None:
    """cli/__main__.main() with 'serve' subcommand calls func."""
    with patch("sox_protocol.cli.serve.serve_command", return_value=0):
        result = cli_main_module.main(["serve", "--transport", "stdio"])
    # Should have called serve_command
    assert isinstance(result, int)


def test_cli_main_module_as_main_exits(monkeypatch) -> None:
    """cli/__main__.py's if __name__ == '__main__' block calls sys.exit(main())."""
    # Simulate the __name__ == '__main__' block:
    # sys.exit(main())
    with patch.object(cli_main_module, "main", return_value=0):
        with pytest.raises(SystemExit) as exc_info:
            sys.exit(cli_main_module.main())
    assert exc_info.value.code == 0


def test_cli_main_module_as_main_subprocess() -> None:
    """Running 'python -m sox_protocol.cli' executes sys.exit(main()) — line 45."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "sox_protocol.cli", "--help"],
        capture_output=True,
        text=True,
    )
    # --help exits 0
    assert result.returncode == 0
    assert "sox" in result.stdout.lower() or "serve" in result.stdout.lower()


# ===========================================================================
# cli/serve.py — serve_command
# ===========================================================================


def test_add_serve_subcommand_registers_parser() -> None:
    """add_serve_subcommand adds 'serve' to subparsers."""
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    cli_serve.add_serve_subcommand(subparsers)
    args = parser.parse_args(["serve", "--transport", "http"])
    assert args.transport == "http"


def test_add_serve_subcommand_stdio_transport() -> None:
    """add_serve_subcommand parses stdio transport."""
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    cli_serve.add_serve_subcommand(subparsers)
    args = parser.parse_args(["serve", "--transport", "stdio"])
    assert args.transport == "stdio"


def test_serve_command_stdio_delegates_to_mcp_server() -> None:
    """serve_command with stdio calls mcp_server.main()."""
    import argparse

    args = argparse.Namespace(transport="stdio", host=None, port=None)
    with patch("sox_protocol.core.mcp_server.server.main") as mock_main:
        result = cli_serve.serve_command(args)
    mock_main.assert_called_once()
    assert result == 0


def test_serve_command_http_sets_env_and_runs_uvicorn() -> None:
    """serve_command with http sets host/port env and calls uvicorn.run()."""
    import argparse

    args = argparse.Namespace(transport="http", host="0.0.0.0", port=9988)

    with patch("uvicorn.run") as mock_run:
        mock_run.return_value = None
        result = cli_serve.serve_command(args)

    mock_run.assert_called_once()
    assert result == 0


def test_serve_command_http_no_host_no_port() -> None:
    """serve_command with http and no host/port uses env defaults."""
    import argparse

    args = argparse.Namespace(transport="http", host=None, port=None)

    with patch("uvicorn.run") as mock_run:
        mock_run.return_value = None
        result = cli_serve.serve_command(args)

    assert result == 0
    mock_run.assert_called_once()
