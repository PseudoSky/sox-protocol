# SPDX-License-Identifier: Apache-2.0
"""Tests for the SKILL.md auto-subscribe Activation block.

Covers the ``auto_subscribe`` + ``default_channels`` plumbing through:
- ``_render_activation_section`` (pure function)
- ``render_skill_md`` (wires it into the template)
- ``install`` (passes through to ``_write_skill``)
- The CLI parsers (``sox-protocol install`` + ``sox-protocol upgrade`` +
  the legacy ``python -m sox_protocol.adapters.runtimes.claude_code install``)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sox_protocol.adapters.runtimes.claude_code.install import (
    _render_activation_section,
    install,
    render_skill_md,
)

# ---------------------------------------------------------------------------
# _render_activation_section — pure function
# ---------------------------------------------------------------------------


def test_activation_off_returns_empty() -> None:
    """auto_subscribe=False → empty string (no block at all)."""
    assert _render_activation_section(False, None) == ""
    assert _render_activation_section(False, ["any/channel"]) == ""  # default_channels ignored


def test_activation_on_no_channels_uses_inbox_only() -> None:
    """auto_subscribe=True with no extra channels → only agent/<your-id>."""
    out = _render_activation_section(True, None)
    assert "## Activation" in out
    assert '["agent/<your-agent-id>"]' in out
    # No other channels in the subscribe call
    assert "team/" not in out
    assert "broadcast/" not in out


def test_activation_on_with_channels_includes_them() -> None:
    """default_channels are listed alongside the inbox in the subscribe call."""
    out = _render_activation_section(True, ["team/eng", "broadcast/announcements"])
    assert '"agent/<your-agent-id>"' in out
    assert '"team/eng"' in out
    assert '"broadcast/announcements"' in out
    # Order preserved (inbox first, then default_channels in order)
    inbox_pos = out.index('"agent/<your-agent-id>"')
    eng_pos = out.index('"team/eng"')
    bcast_pos = out.index('"broadcast/announcements"')
    assert inbox_pos < eng_pos < bcast_pos


def test_activation_includes_drain_and_heartbeat_steps() -> None:
    """The activation block tells the LLM to drain and heartbeat too."""
    out = _render_activation_section(True, None)
    assert "channels__recv" in out
    assert "channels__heartbeat" in out


# ---------------------------------------------------------------------------
# render_skill_md — full template wiring
# ---------------------------------------------------------------------------


def test_render_skill_md_default_no_activation() -> None:
    """Default render: no activation section in output."""
    md = render_skill_md()
    assert "## Activation" not in md
    # Frontmatter still present
    assert "name: inter-agent-channels" in md


def test_render_skill_md_auto_subscribe_includes_activation() -> None:
    md = render_skill_md(auto_subscribe=True)
    assert "## Activation (auto-subscribe)" in md
    assert '["agent/<your-agent-id>"]' in md


def test_render_skill_md_auto_subscribe_with_channels() -> None:
    md = render_skill_md(auto_subscribe=True, default_channels=["ticket/ENGI-42"])
    assert '"ticket/ENGI-42"' in md


# ---------------------------------------------------------------------------
# install() — wires through to disk
# ---------------------------------------------------------------------------


def test_install_default_no_activation_in_skill_file(tmp_path: Path) -> None:
    install(project_dir=tmp_path, verbose=False)
    skill = (tmp_path / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md").read_text()
    assert "## Activation" not in skill


def test_install_auto_subscribe_writes_activation_section(tmp_path: Path) -> None:
    install(project_dir=tmp_path, verbose=False, auto_subscribe=True)
    skill = (tmp_path / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md").read_text()
    assert "## Activation (auto-subscribe)" in skill


def test_install_auto_subscribe_with_channels_writes_them(tmp_path: Path) -> None:
    install(
        project_dir=tmp_path,
        verbose=False,
        auto_subscribe=True,
        default_channels=["team/qa"],
    )
    skill = (tmp_path / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md").read_text()
    assert '"team/qa"' in skill


def test_install_idempotent_with_auto_subscribe(tmp_path: Path) -> None:
    """Running install twice with the same auto-subscribe args produces no diff."""
    install(project_dir=tmp_path, verbose=False, auto_subscribe=True, default_channels=["x/y"])
    skill_path = tmp_path / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md"
    first = skill_path.read_text()

    install(project_dir=tmp_path, verbose=False, auto_subscribe=True, default_channels=["x/y"])
    second = skill_path.read_text()
    assert first == second


def test_install_changing_auto_subscribe_state_rewrites_skill(tmp_path: Path) -> None:
    """Toggling --auto-subscribe between runs correctly rewrites the file."""
    skill_path = tmp_path / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md"

    install(project_dir=tmp_path, verbose=False)
    assert "## Activation" not in skill_path.read_text()

    install(project_dir=tmp_path, verbose=False, auto_subscribe=True)
    assert "## Activation" in skill_path.read_text()

    install(project_dir=tmp_path, verbose=False, auto_subscribe=False)
    assert "## Activation" not in skill_path.read_text()


# ---------------------------------------------------------------------------
# CLI wiring — sox-protocol install ...
# ---------------------------------------------------------------------------


def test_cli_install_auto_subscribe_flag_parses(tmp_path: Path) -> None:
    """`sox-protocol install --auto-subscribe --channel a --channel b` reaches install()."""
    from sox_protocol.cli.install import install_command

    rc = install_command(argparse.Namespace(
        project_dir=tmp_path,
        quiet=True,
        auto_subscribe=True,
        default_channels=["a/x", "b/y"],
    ))
    assert rc == 0
    skill = (tmp_path / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md").read_text()
    assert "## Activation" in skill
    assert '"a/x"' in skill
    assert '"b/y"' in skill


def test_cli_install_no_flags_omits_activation(tmp_path: Path) -> None:
    """`sox-protocol install` with no auto-subscribe flag keeps SKILL.md plain."""
    from sox_protocol.cli.install import install_command

    rc = install_command(argparse.Namespace(
        project_dir=tmp_path,
        quiet=True,
        auto_subscribe=False,
        default_channels=None,
    ))
    assert rc == 0
    skill = (tmp_path / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md").read_text()
    assert "## Activation" not in skill
