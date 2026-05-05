# SPDX-License-Identifier: Apache-2.0
"""Tests for the Claude Code runtime adapter installer.

Uses ``tmp_path`` fixtures to simulate a fresh Claude Code project.

Test coverage:
- SKILL.md written with correct frontmatter and substituted placeholders.
- Hook scripts written and made executable.
- settings.json updated with MCP server and hook registrations.
- Bootstrap line inserted into agent .md files.
- Full idempotency: running install twice produces identical artefacts.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from sox_protocol.adapters.runtimes.claude_code.install import (
    _BOOTSTRAP_SENTINEL,
    _HOOK_EVENTS,
    _MCP_SERVER_NAME,
    BOOTSTRAP_LINE,
    TOOL_SUBSTITUTIONS,
    install,
    render_skill_md,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """Return a minimal simulated Claude Code project directory."""
    # Create the .claude/agents directory with one agent file
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "worker.md").write_text(
        "---\nname: worker\n---\n\nYou are a worker agent.\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# SKILL.md tests
# ---------------------------------------------------------------------------


def test_skill_md_exists_after_install(project: Path) -> None:
    install(project_dir=project, verbose=False)
    skill = project / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md"
    assert skill.exists(), "SKILL.md should be written"


def test_skill_md_has_frontmatter(project: Path) -> None:
    install(project_dir=project, verbose=False)
    skill = (project / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md").read_text()
    assert "name: inter-agent-channels" in skill
    assert "description:" in skill


def test_skill_md_required_headings(project: Path) -> None:
    install(project_dir=project, verbose=False)
    skill = (project / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md").read_text()
    required = [
        "# Inter-agent channels",
        "## When to send",
        "## How to send",
        "## Polling cadence",
        "## The send-and-continue pattern",
        "## The speculative-then-reconcile recipe",
        "## Anti-patterns",
        "## What not to use channels for",
    ]
    for heading in required:
        assert heading in skill, f"Required heading missing: {heading!r}"


def test_skill_md_placeholders_substituted(project: Path) -> None:
    install(project_dir=project, verbose=False)
    skill = (project / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md").read_text()

    # All {{placeholder}} tokens must be gone
    for placeholder in TOOL_SUBSTITUTIONS:
        assert placeholder not in skill, f"Placeholder {placeholder!r} was not substituted"

    # All concrete tool names must be present
    for concrete in TOOL_SUBSTITUTIONS.values():
        assert concrete in skill, f"Concrete tool name {concrete!r} not found in SKILL.md"


def test_skill_md_no_raw_tool_names_in_discipline_text(project: Path) -> None:
    """The rendered SKILL.md should contain mcp__ names, not bare channels__ names."""
    install(project_dir=project, verbose=False)
    content = (project / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md").read_text()
    # The discipline uses {{send_tool}} etc.; after substitution, bare tool
    # names like "channels__send" (without mcp__sox__ prefix) should not appear
    # as standalone references outside the mcp__sox__ form.
    # (They may legitimately appear as part of mcp__sox__channels__send.)
    assert "mcp__sox__channels__send" in content
    assert "mcp__sox__channels__recv" in content


# ---------------------------------------------------------------------------
# Hook tests
# ---------------------------------------------------------------------------


def test_hooks_exist_after_install(project: Path) -> None:
    install(project_dir=project, verbose=False)
    hooks_dir = project / "tools" / "sox-hooks"
    assert (hooks_dir / "post_tool_use.sh").exists()
    assert (hooks_dir / "stop.sh").exists()


def test_hooks_are_executable(project: Path) -> None:
    install(project_dir=project, verbose=False)
    hooks_dir = project / "tools" / "sox-hooks"
    for script in ["post_tool_use.sh", "stop.sh"]:
        path = hooks_dir / script
        assert os.access(path, os.X_OK), f"{script} must be executable"
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR, f"{script} missing user execute bit"


def test_hooks_have_shebang(project: Path) -> None:
    install(project_dir=project, verbose=False)
    hooks_dir = project / "tools" / "sox-hooks"
    for script in ["post_tool_use.sh", "stop.sh"]:
        first_line = (hooks_dir / script).read_text().splitlines()[0]
        assert first_line.startswith("#!/"), f"{script} must start with a shebang"


# ---------------------------------------------------------------------------
# settings.json tests
# ---------------------------------------------------------------------------


def test_settings_json_created(project: Path) -> None:
    install(project_dir=project, verbose=False)
    settings_path = project / ".claude" / "settings.json"
    assert settings_path.exists()


def test_settings_json_valid(project: Path) -> None:
    install(project_dir=project, verbose=False)
    settings_path = project / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text())
    assert isinstance(settings, dict)


def test_settings_json_mcp_server_registered(project: Path) -> None:
    install(project_dir=project, verbose=False)
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    mcp_servers = settings.get("mcpServers", {})
    assert _MCP_SERVER_NAME in mcp_servers, "SOX MCP server not in mcpServers"
    server = mcp_servers[_MCP_SERVER_NAME]
    assert server.get("type") == "stdio"
    assert server.get("command")  # some Python executable
    assert "-m" in server.get("args", [])
    assert "sox_protocol.core.mcp_server" in server.get("args", [])


def test_settings_json_mcp_server_env(project: Path) -> None:
    """Installer sets SOX_BACKING_STORE and the SOX_AGENT_ID_SOURCE declaration.

    Per spec/ports/identity.md §6, credential plumbs through MCP launch params,
    not tool-call inputs.  ``SOX_AGENT_ID_SOURCE`` documents which env channel
    the runtime adapter is using to inject the verified agent_id.
    """
    install(project_dir=project, verbose=False)
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    env = settings["mcpServers"][_MCP_SERVER_NAME].get("env", {})
    assert "SOX_BACKING_STORE" in env
    assert env["SOX_BACKING_STORE"].startswith("sqlite:///")
    assert ".sox/messages.db" in env["SOX_BACKING_STORE"]
    assert env.get("SOX_AGENT_ID_SOURCE") == "claude_code_agent_name"


def test_settings_json_hooks_registered(project: Path) -> None:
    install(project_dir=project, verbose=False)
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    hooks = settings.get("hooks", {})
    for event in _HOOK_EVENTS:
        assert event in hooks, f"Hook event {event!r} not registered"
        assert len(hooks[event]) > 0, f"No hook entries for event {event!r}"


def test_settings_json_hooks_point_to_scripts(project: Path) -> None:
    """Hook entries follow Claude Code's nested schema:
    ``{matcher: ..., hooks: [{type: command, command: <path>.sh}, ...]}``.
    """
    install(project_dir=project, verbose=False)
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    hooks = settings.get("hooks", {})
    for event in _HOOK_EVENTS:
        for entry in hooks.get(event, []):
            inner_hooks = entry.get("hooks", [])
            assert inner_hooks, f"Hook entry for {event} must contain inner hooks list"
            for inner in inner_hooks:
                cmd = inner.get("command", "")
                assert cmd.endswith(".sh"), (
                    f"Hook command for {event} must be a .sh script: {cmd}"
                )
                assert Path(cmd).name in ("post_tool_use.sh", "stop.sh")


def test_settings_json_merged_with_existing(project: Path) -> None:
    """Install should merge into an existing settings.json, not overwrite."""
    settings_path = project / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"existingKey": "existingValue", "mcpServers": {"other": {"type": "stdio"}}}),
        encoding="utf-8",
    )
    install(project_dir=project, verbose=False)
    settings = json.loads(settings_path.read_text())
    assert settings.get("existingKey") == "existingValue", "Existing keys must be preserved"
    assert "other" in settings.get("mcpServers", {}), "Existing MCP servers must be preserved"
    assert _MCP_SERVER_NAME in settings.get("mcpServers", {}), "SOX server must be added"


# ---------------------------------------------------------------------------
# Bootstrap line tests
# ---------------------------------------------------------------------------


def test_bootstrap_line_inserted(project: Path) -> None:
    install(project_dir=project, verbose=False)
    agent_file = project / ".claude" / "agents" / "worker.md"
    content = agent_file.read_text()
    assert _BOOTSTRAP_SENTINEL in content, "Bootstrap sentinel not found in agent file"
    assert BOOTSTRAP_LINE in content, "Full bootstrap line not found in agent file"


def test_bootstrap_line_not_duplicated_on_rerun(project: Path) -> None:
    install(project_dir=project, verbose=False)
    install(project_dir=project, verbose=False)
    agent_file = project / ".claude" / "agents" / "worker.md"
    content = agent_file.read_text()
    count = content.count(BOOTSTRAP_LINE)
    assert count == 1, f"Bootstrap line duplicated: found {count} occurrences"


def test_bootstrap_skips_agents_already_containing_it(project: Path) -> None:
    """Agent files that already have the bootstrap line must not be modified."""
    agents_dir = project / ".claude" / "agents"
    already_done = agents_dir / "smart.md"
    original = f"---\nname: smart\n---\n\nSome prompt.\n\n{BOOTSTRAP_LINE}\n"
    already_done.write_text(original, encoding="utf-8")

    install(project_dir=project, verbose=False)

    result = already_done.read_text()
    assert result.count(BOOTSTRAP_LINE) == 1, "Bootstrap line was duplicated in already-done file"


def test_no_agent_files_is_fine(tmp_path: Path) -> None:
    """Install must not fail when .claude/agents/ does not exist."""
    install(project_dir=tmp_path, verbose=False)
    # Just check no exception was raised
    assert (tmp_path / ".claude" / "settings.json").exists()


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------


def _collect_artefacts(project: Path) -> dict[str, str | bytes]:
    """Collect all SOX-installed artefacts as a snapshot."""
    artefacts: dict[str, str | bytes] = {}

    skill = project / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md"
    if skill.exists():
        artefacts["SKILL.md"] = skill.read_text()

    settings = project / ".claude" / "settings.json"
    if settings.exists():
        artefacts["settings.json"] = settings.read_text()

    hooks_dir = project / "tools" / "sox-hooks"
    for script in ["post_tool_use.sh", "stop.sh"]:
        p = hooks_dir / script
        if p.exists():
            artefacts[script] = p.read_bytes()

    agents_dir = project / ".claude" / "agents"
    if agents_dir.exists():
        for agent in sorted(agents_dir.glob("*.md")):
            artefacts[f"agents/{agent.name}"] = agent.read_text()

    return artefacts


def test_install_is_fully_idempotent(project: Path) -> None:
    """Running install twice MUST produce byte-for-byte identical artefacts."""
    install(project_dir=project, verbose=False)
    snapshot_1 = _collect_artefacts(project)

    install(project_dir=project, verbose=False)
    snapshot_2 = _collect_artefacts(project)

    assert snapshot_1.keys() == snapshot_2.keys(), "Second install changed the set of artefacts"
    for key in snapshot_1:
        assert snapshot_1[key] == snapshot_2[key], (
            f"Artefact '{key}' changed on second install — install is NOT idempotent"
        )


def test_idempotent_settings_no_duplicate_hooks(project: Path) -> None:
    """Running install three times must not append duplicate hook entries.

    Traverses the nested Claude Code hook schema:
    ``hooks[event] -> [{matcher, hooks: [{type, command}]}]``.
    """
    for _ in range(3):
        install(project_dir=project, verbose=False)

    settings = json.loads((project / ".claude" / "settings.json").read_text())
    hooks = settings.get("hooks", {})
    for event in _HOOK_EVENTS:
        entries = hooks.get(event, [])
        commands = [
            inner["command"]
            for entry in entries
            for inner in entry.get("hooks", [])
            if "command" in inner
        ]
        assert len(commands) == len(set(commands)), (
            f"Duplicate hook commands for event {event!r}: {commands}"
        )


def test_idempotent_mcp_server_not_duplicated(project: Path) -> None:
    """MCP server must appear exactly once in mcpServers after multiple installs."""
    for _ in range(3):
        install(project_dir=project, verbose=False)

    settings = json.loads((project / ".claude" / "settings.json").read_text())
    sox_count = sum(1 for k in settings.get("mcpServers", {}) if k == _MCP_SERVER_NAME)
    assert sox_count == 1, f"SOX MCP server appears {sox_count} times in mcpServers"


# ---------------------------------------------------------------------------
# render_skill_md unit test (no disk I/O)
# ---------------------------------------------------------------------------


def test_render_skill_md_no_raw_placeholders() -> None:
    """render_skill_md() must produce no {{...}} placeholders."""
    rendered = render_skill_md()
    for placeholder in TOOL_SUBSTITUTIONS:
        assert placeholder not in rendered, f"Placeholder {placeholder!r} survived rendering"


def test_render_skill_md_contains_all_tools() -> None:
    """render_skill_md() must contain all four Claude Code tool names."""
    rendered = render_skill_md()
    for tool_name in TOOL_SUBSTITUTIONS.values():
        assert tool_name in rendered, f"Tool name {tool_name!r} missing from rendered SKILL.md"


def test_render_skill_md_has_frontmatter() -> None:
    rendered = render_skill_md()
    assert rendered.startswith("---"), "SKILL.md must start with YAML frontmatter"
    assert "name: inter-agent-channels" in rendered
    assert "description:" in rendered


# ---------------------------------------------------------------------------
# agent_id_source plumbing — install() honors the override and writes it
# into both .mcp.json and .claude/settings.json.
# ---------------------------------------------------------------------------


def test_install_default_agent_id_source_is_claude_code(project: Path) -> None:
    """Without override, both files use the historical claude_code_agent_name."""
    install(project_dir=project, verbose=False)

    mcp = json.loads((project / ".mcp.json").read_text())
    settings = json.loads((project / ".claude" / "settings.json").read_text())

    assert mcp["mcpServers"][_MCP_SERVER_NAME]["env"]["SOX_AGENT_ID_SOURCE"] == "claude_code_agent_name"
    assert (
        settings["mcpServers"][_MCP_SERVER_NAME]["env"]["SOX_AGENT_ID_SOURCE"]
        == "claude_code_agent_name"
    )


def test_install_with_env_var_agent_id_source(project: Path) -> None:
    """``--agent-id-source env:SOX_AGENT_NAME`` writes through to both files."""
    install(
        project_dir=project,
        verbose=False,
        agent_id_source="env:SOX_AGENT_NAME",
    )

    mcp = json.loads((project / ".mcp.json").read_text())
    settings = json.loads((project / ".claude" / "settings.json").read_text())

    assert mcp["mcpServers"][_MCP_SERVER_NAME]["env"]["SOX_AGENT_ID_SOURCE"] == "env:SOX_AGENT_NAME"
    assert (
        settings["mcpServers"][_MCP_SERVER_NAME]["env"]["SOX_AGENT_ID_SOURCE"]
        == "env:SOX_AGENT_NAME"
    )


def test_install_with_arbitrary_env_var_agent_id_source(project: Path) -> None:
    """Any env:VARNAME string is forwarded verbatim — no whitelist."""
    install(
        project_dir=project,
        verbose=False,
        agent_id_source="env:MY_HOST_AGENT_ID",
    )

    mcp = json.loads((project / ".mcp.json").read_text())
    assert (
        mcp["mcpServers"][_MCP_SERVER_NAME]["env"]["SOX_AGENT_ID_SOURCE"]
        == "env:MY_HOST_AGENT_ID"
    )


def test_install_with_agent_id_source_idempotent(project: Path) -> None:
    """Running install twice with the same agent_id_source produces no diff."""
    install(project_dir=project, verbose=False, agent_id_source="env:SOX_AGENT_NAME")
    mcp_first = (project / ".mcp.json").read_text()

    install(project_dir=project, verbose=False, agent_id_source="env:SOX_AGENT_NAME")
    mcp_second = (project / ".mcp.json").read_text()

    assert mcp_first == mcp_second
