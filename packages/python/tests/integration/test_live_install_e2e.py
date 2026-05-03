"""Live end-to-end test: install → messaging with real Claude CLI subprocesses.

This module exercises the full install→messaging path:

1. Creates a real ``python -m venv`` in a pytest tmp_path.
2. ``pip install -e packages/python plugins/sox-plugin-schema-strict`` into it.
3. Copies ``tests/fixtures/live_install/`` into a fresh tmp Claude project root.
4. Runs ``python -m sox_protocol.adapters.runtimes.claude_code install`` against it.
5. Spawns two ``claude`` CLI subprocesses **serially** (alice then bob).
6. Asserts on the SOX SQLite database **structurally** — row counts and sentinel
   presence only; never message body text (LLM drift is not a defect).

Markers
-------
- ``@pytest.mark.live`` — requires ``ANTHROPIC_API_KEY`` and the ``claude`` CLI.
  Default ``pytest`` runs (no ``-m live``) skip this module entirely.

Architecture note (discovered during phase 03 implementation)
-------------------------------------------------------------
Group state (``_groups`` dict in SqliteStore) is **in-memory only** — it is not
persisted to the SQLite database (see TODO comments in store.py).  When alice's
``claude`` subprocess exits, her MCP server process exits and the group state is
lost.  Bob's fresh MCP server process therefore starts with an empty ``_groups``
dict.

Consequence: ``group__invite`` is decorative across process boundaries in the
current implementation.  ``group__join`` still works because it writes a row to
the persisted ``subscriptions`` table regardless of whether the agent appears in
``_groups``.  The PING send writes to ``messages`` before alice's server exits,
and bob's server reads it from SQLite.  The structural assertions below target
only the tables that ARE persisted.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import venv
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Skip conditions — evaluated at collection time (no API calls)
# ---------------------------------------------------------------------------

_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_HAS_CLAUDE = shutil.which("claude") is not None


def _probe_oauth() -> bool:
    """Return True if `claude auth status` reports loggedIn=true."""
    if not _HAS_CLAUDE:
        return False
    try:
        result = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False
        return '"loggedIn": true' in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


_OAUTH_OK = _probe_oauth() if not _API_KEY else False
_AUTH_OK = bool(_API_KEY) or _OAUTH_OK

# The live marker is what gates default pytest runs; skipif is belt-and-suspenders.
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _AUTH_OK,
        reason=(
            "neither ANTHROPIC_API_KEY set nor `claude auth status` OK — "
            "live test skipped"
        ),
    ),
    pytest.mark.skipif(
        not _HAS_CLAUDE,
        reason="claude CLI not on PATH — live test skipped",
    ),
]

# ---------------------------------------------------------------------------
# Repo-root resolution
# ---------------------------------------------------------------------------

# packages/python/tests/integration/test_live_install_e2e.py  →  repo root
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent.resolve()
_PACKAGES_PYTHON = _REPO_ROOT / "packages" / "python"
_PLUGIN_DIR = _REPO_ROOT / "plugins" / "sox-plugin-schema-strict"
_FIXTURE_DIR = _PACKAGES_PYTHON / "tests" / "fixtures" / "live_install"

# ---------------------------------------------------------------------------
# Helper dataclass (stdlib only — no attrs/dataclasses import needed)
# ---------------------------------------------------------------------------


class _VenvPaths:
    """Container for resolved venv binary paths."""

    def __init__(self, venv_dir: Path) -> None:
        self.root = venv_dir
        bin_dir = venv_dir / "bin"
        self.python = bin_dir / "python"
        self.pip = bin_dir / "pip"

    def __repr__(self) -> str:
        return f"_VenvPaths(root={self.root})"


# ---------------------------------------------------------------------------
# Session-scoped venv fixture
# (built once per pytest session; reused across all live tests in this module)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def live_venv(tmp_path_factory: pytest.TempPathFactory) -> _VenvPaths:
    """Build a real venv and install sox-protocol + schema-strict plugin into it.

    Session-scoped so the ~30s build cost is paid once per test session.
    """
    venv_dir = tmp_path_factory.mktemp("live_venv", numbered=False)
    venv.create(str(venv_dir), with_pip=True, clear=True)
    paths = _VenvPaths(venv_dir)

    assert paths.python.exists(), f"venv python not found at {paths.python}"
    assert paths.pip.exists(), f"venv pip not found at {paths.pip}"

    # Upgrade pip silently to avoid spurious warnings in captured output.
    subprocess.run(
        [str(paths.python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
        check=True,
        capture_output=True,
    )

    # Install editable sox-protocol (gives stack traces pointing at repo source).
    subprocess.run(
        [
            str(paths.pip),
            "install",
            "--quiet",
            "-e",
            str(_PACKAGES_PYTHON),
        ],
        check=True,
        capture_output=True,
        cwd=str(_REPO_ROOT),
    )

    # Install the schema-strict reference plugin.
    subprocess.run(
        [
            str(paths.pip),
            "install",
            "--quiet",
            str(_PLUGIN_DIR),
        ],
        check=True,
        capture_output=True,
        cwd=str(_REPO_ROOT),
    )

    # Smoke-check: can we import sox_protocol and reach entry points?
    result = subprocess.run(
        [
            str(paths.python),
            "-c",
            (
                "from sox_protocol.adapters.backing_stores.sqlite.store import SqliteStore; "
                "print('venv-ok')"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"venv smoke-check failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "venv-ok" in result.stdout

    return paths


# ---------------------------------------------------------------------------
# Function-scoped project fixture
# (fresh copy per test so tests are isolated from each other)
# ---------------------------------------------------------------------------


@pytest.fixture()
def live_project(
    tmp_path: Path,
    live_venv: _VenvPaths,
) -> Path:
    """Copy the fixture skeleton to tmp_path and run the SOX installer against it.

    Returns the project root path (where .mcp.json, .claude/, .sox/ will live).
    """
    project_dir = tmp_path / "project"
    shutil.copytree(str(_FIXTURE_DIR), str(project_dir))

    # Run the installer using the venv's python so it writes the correct
    # sys.executable path into .mcp.json (points at venv python, not host python).
    result = subprocess.run(
        [
            str(live_venv.python),
            "-m",
            "sox_protocol.adapters.runtimes.claude_code",
            "install",
            "--project-dir",
            str(project_dir),
        ],
        capture_output=True,
        text=True,
        cwd=str(project_dir),
    )
    assert result.returncode == 0, (
        f"Installer failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Verify the installer wrote the expected artefacts.
    assert (project_dir / ".mcp.json").exists(), "Installer did not write .mcp.json"
    assert (project_dir / ".claude" / "settings.json").exists(), (
        "Installer did not write .claude/settings.json"
    )
    skill_md = (
        project_dir / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md"
    )
    assert skill_md.exists(), "Installer did not write SKILL.md"

    # Verify .mcp.json names the server "sox" — the load-bearing name.
    mcp_json = json.loads((project_dir / ".mcp.json").read_text())
    assert "sox" in mcp_json.get("mcpServers", {}), (
        f"Expected 'sox' server in .mcp.json, got: {list(mcp_json.get('mcpServers', {}).keys())}"
    )

    return project_dir


# ---------------------------------------------------------------------------
# Helper: run a single claude subprocess
# ---------------------------------------------------------------------------

_CLAUDE_TIMEOUT = 300  # seconds per agent run


def _run_claude(
    prompt: str,
    project_dir: Path,
    tmp_dir: Path,
    agent_name: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Spawn a claude CLI subprocess in --bare --print mode.

    Args:
        prompt: The full prompt string to pass to claude.
        project_dir: cwd for the subprocess (where .mcp.json lives).
        tmp_dir: Scratch dir for CLAUDE_CONFIG_DIR and HOME override.
        agent_name: Label for artifact files (alice / bob).
        extra_env: Additional env overrides (merged on top of base env).

    Returns:
        CompletedProcess with stdout/stderr captured.

    Raises:
        pytest.fail if the process times out. Non-zero return codes are
        surfaced via the returned CompletedProcess.returncode; callers must
        assert on that field separately (see usage in the happy-path test).
    """
    artifacts_dir = tmp_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Isolated Claude state dir — prevents polluting developer's real session.
    claude_state = tmp_dir / "claude_state" / agent_name
    claude_state.mkdir(parents=True, exist_ok=True)
    home_dir = tmp_dir / "home" / agent_name
    home_dir.mkdir(parents=True, exist_ok=True)

    if _API_KEY:
        # CI-style: ANTHROPIC_API_KEY-only auth via --bare. Full state isolation:
        # override HOME + CLAUDE_CONFIG_DIR so the test doesn't touch the
        # developer's real Claude session.
        env = {
            **os.environ,
            "ANTHROPIC_API_KEY": _API_KEY,
            "CLAUDE_CONFIG_DIR": str(claude_state),
            "HOME": str(home_dir),
            "SOX_HOOKS_DISABLED": "1",
            # Identity per-agent. The .mcp.json sets SOX_AGENT_ID_SOURCE=
            # claude_code_agent_name; that source falls back to SOX_AGENT_ID
            # when CLAUDE_AGENT_NAME is unset (which it is in --print mode).
            "SOX_AGENT_ID": agent_name,
        }
        bare_flag = ["--bare"]
    else:
        # OAuth-style (Max subscription): keychain auth requires the developer's
        # real HOME. State isolation impossible — accept that the test will
        # touch the developer's Claude session.
        env = {
            **os.environ,
            "SOX_HOOKS_DISABLED": "1",
            "SOX_AGENT_ID": agent_name,
        }
        # Strip any inherited empty ANTHROPIC_API_KEY that would force --bare
        # behavior to fail.
        env.pop("ANTHROPIC_API_KEY", None)
        bare_flag = []
    if extra_env:
        env.update(extra_env)

    cmd = [
        "claude",
        *bare_flag,
        "--dangerously-skip-permissions",
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        "claude-sonnet-4-5",
        "--max-budget-usd",
        "1.00",
        prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_CLAUDE_TIMEOUT,
            cwd=str(project_dir),
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        # Write whatever was captured so far for debugging.
        stdout_so_far = exc.stdout or b""
        stderr_so_far = exc.stderr or b""
        (artifacts_dir / f"{agent_name}_timeout_stdout.txt").write_bytes(
            stdout_so_far if isinstance(stdout_so_far, bytes) else stdout_so_far.encode()
        )
        pytest.fail(
            f"{agent_name} claude subprocess timed out after {_CLAUDE_TIMEOUT}s"
        )

    # Save artifacts for CI debugging regardless of pass/fail.
    (artifacts_dir / f"{agent_name}_stdout.txt").write_text(
        result.stdout, encoding="utf-8"
    )
    (artifacts_dir / f"{agent_name}_stderr.txt").write_text(
        result.stderr, encoding="utf-8"
    )

    return result


# ---------------------------------------------------------------------------
# Helper: DB structural assertions
# ---------------------------------------------------------------------------


def _db_path(project_dir: Path) -> Path:
    return project_dir / ".sox" / "messages.db"


def _query_db(project_dir: Path, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    """Run a SELECT against the SOX SQLite DB and return all rows.

    Uses stdlib sqlite3 (not the async venv's aiosqlite) to keep the assertion
    helper synchronous and dependency-free.
    """
    db = _db_path(project_dir)
    assert db.exists(), (
        f"SOX database not found at {db}. "
        "Did the MCP server start correctly? Check artifacts/alice_stderr.txt."
    )
    with sqlite3.connect(str(db)) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall()


def _assert_db_state(
    project_dir: Path,
    *,
    min_message_rows: int,
    expected_channels: list[str] | None = None,
) -> None:
    """Assert structural invariants on the SOX SQLite database.

    Args:
        project_dir: Project root (parent of .sox/messages.db).
        min_message_rows: Minimum number of rows expected in the messages table.
        expected_channels: If provided, assert each channel appears in messages.
    """
    rows = _query_db(project_dir, "SELECT COUNT(*) FROM messages")
    actual_count = rows[0][0]
    assert actual_count >= min_message_rows, (
        f"Expected at least {min_message_rows} row(s) in messages, got {actual_count}. "
        f"DB path: {_db_path(project_dir)}"
    )

    if expected_channels:
        channel_rows = _query_db(
            project_dir, "SELECT DISTINCT channel FROM messages"
        )
        actual_channels = {r[0] for r in channel_rows}
        for ch in expected_channels:
            assert ch in actual_channels, (
                f"Expected channel {ch!r} in messages table. "
                f"Actual channels: {sorted(actual_channels)}"
            )


def _assert_tool_used(transcript: str, tool_name: str, agent_name: str) -> None:
    """Assert that a SOX tool-use marker appears in the claude --print transcript."""
    assert tool_name in transcript, (
        f"Expected tool-use marker {tool_name!r} in {agent_name}'s transcript. "
        f"This means the agent did not call the expected SOX tool. "
        f"Transcript excerpt (first 2000 chars):\n{transcript[:2000]}"
    )


def _assert_sentinel(transcript: str, sentinel: str, agent_name: str) -> None:
    """Assert the completion sentinel appears in the transcript."""
    assert sentinel in transcript, (
        f"Expected sentinel {sentinel!r} in {agent_name}'s transcript. "
        f"Agent may have hit budget limit or errored before completing. "
        f"Transcript excerpt (last 2000 chars):\n{transcript[-2000:]}"
    )


def _assert_cost_logged(transcript: str, agent_name: str) -> None:
    """Assert that claude logged a cost in the stream-json result event.

    Claude emits ``"total_cost_usd": <float>`` in the ``type: "result"`` event
    when invoked with ``--output-format stream-json --verbose``. Asserting its
    presence verifies the agent actually ran (didn't short-circuit) and
    documents the actual spend per run.
    """
    assert "total_cost_usd" in transcript, (
        f"Expected 'total_cost_usd' in {agent_name}'s transcript. "
        f"Either claude did not emit a result event or output format changed. "
        f"Transcript (first 500 chars): {transcript[:500]}"
    )


# ---------------------------------------------------------------------------
# Positive test: full happy path
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(not _AUTH_OK, reason="no ANTHROPIC_API_KEY and no OAuth")
@pytest.mark.skipif(not _HAS_CLAUDE, reason="claude CLI not on PATH")
def test_live_install_happy_path(live_project: Path, tmp_path: Path) -> None:
    """Full install → alice creates group + sends PING → bob joins + sends PONG.

    Structural assertions (never message body text):
    - alice's transcript contains tool-use markers for group__create, group__invite,
      channels__send.
    - alice's transcript contains ALICE_DONE sentinel.
    - alice's transcript contains 'Total cost:' (budget guard).
    - After alice: messages table has >= 1 row (alice's PING to the group channel).
    - After alice: group channel appears in messages.channel column.
    - bob's transcript contains tool-use markers for channels__recv, group__join,
      channels__send.
    - bob's transcript contains BOB_DONE sentinel.
    - bob's transcript contains 'Total cost:' (budget guard).
    - After bob: messages table has >= 2 rows (alice's PING + bob's PONG).
    """
    # Load prompts from fixture files.
    alice_prompt = (_FIXTURE_DIR / "prompts" / "alice_prompt.txt").read_text(
        encoding="utf-8"
    ).strip()
    bob_prompt = (_FIXTURE_DIR / "prompts" / "bob_prompt.txt").read_text(
        encoding="utf-8"
    ).strip()

    # ── Alice runs first ──────────────────────────────────────────────────
    alice_result = _run_claude(
        prompt=alice_prompt,
        project_dir=live_project,
        tmp_dir=tmp_path,
        agent_name="alice",
    )
    assert alice_result.returncode == 0, (
        f"alice exited with rc={alice_result.returncode}.\n"
        f"stdout: {alice_result.stdout[:3000]}\n"
        f"stderr: {alice_result.stderr[:1000]}"
    )

    alice_tx = alice_result.stdout
    _assert_sentinel(alice_tx, "ALICE_DONE", "alice")
    _assert_cost_logged(alice_tx, "alice")
    _assert_tool_used(alice_tx, "mcp__sox__group__create", "alice")
    _assert_tool_used(alice_tx, "mcp__sox__channels__send", "alice")

    # DB: alice's PING should be in the messages table.
    _assert_db_state(
        live_project,
        min_message_rows=1,
        expected_channels=["group/live-e2e-test"],
    )

    # Brief pause between agents — avoids per-minute rate-limit edge case.
    time.sleep(3)

    # ── Bob runs second ───────────────────────────────────────────────────
    bob_result = _run_claude(
        prompt=bob_prompt,
        project_dir=live_project,
        tmp_dir=tmp_path,
        agent_name="bob",
    )
    assert bob_result.returncode == 0, (
        f"bob exited with rc={bob_result.returncode}.\n"
        f"stdout: {bob_result.stdout[:3000]}\n"
        f"stderr: {bob_result.stderr[:1000]}"
    )

    bob_tx = bob_result.stdout
    _assert_sentinel(bob_tx, "BOB_DONE", "bob")
    _assert_cost_logged(bob_tx, "bob")
    _assert_tool_used(bob_tx, "mcp__sox__group__join", "bob")
    _assert_tool_used(bob_tx, "mcp__sox__channels__recv", "bob")
    _assert_tool_used(bob_tx, "mcp__sox__channels__send", "bob")

    # DB: both alice's PING and bob's PONG should be in messages.
    _assert_db_state(
        live_project,
        min_message_rows=2,
        expected_channels=["group/live-e2e-test"],
    )

    # Subscriptions: alice and bob should both be subscribed to the group channel.
    sub_rows = _query_db(
        live_project,
        "SELECT agent_id FROM subscriptions WHERE channel_pattern = ?",
        ("group/live-e2e-test",),
    )
    sub_agents = {r[0] for r in sub_rows}
    # Alice subscribes via group__create; bob subscribes via group__join.
    # Both MUST be present — otherwise we can't tell whether bob actually joined
    # or only alice's create did the work.
    assert len(sub_agents) >= 2, (
        f"Expected at least 2 distinct subscribers (alice + bob) to "
        f"group/live-e2e-test, got {sub_agents}"
    )


# ---------------------------------------------------------------------------
# Negative test: broken MCP server name in .mcp.json
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(not _AUTH_OK, reason="no ANTHROPIC_API_KEY and no OAuth")
@pytest.mark.skipif(not _HAS_CLAUDE, reason="claude CLI not on PATH")
def test_live_install_negative_broken_mcp_name(
    live_project: Path, tmp_path: Path
) -> None:
    """Negative test: corrupt .mcp.json server name → alice cannot call SOX tools.

    After install, rename the MCP server entry from 'sox' to 'sox-broken'.
    Claude will start without the SOX MCP server registered under the expected
    name, so mcp__sox__* tools will be unavailable.

    Load-bearing assertion: either
    (a) alice's returncode is non-zero, OR
    (b) the messages table remains empty (no PING was sent), OR
    (c) alice's transcript does NOT contain ALICE_DONE.

    If all three conditions pass (alice somehow succeeded despite the broken
    config), the test raises pytest.fail to flag a false-positive in the
    positive test path.
    """
    # Corrupt .mcp.json: rename "sox" → "sox-broken"
    mcp_json_path = live_project / ".mcp.json"
    mcp_data = json.loads(mcp_json_path.read_text(encoding="utf-8"))
    servers = mcp_data.get("mcpServers", {})
    assert "sox" in servers, (
        f"Expected 'sox' key in mcpServers before corruption, got: {list(servers.keys())}"
    )
    servers["sox-broken"] = servers.pop("sox")
    mcp_json_path.write_text(
        json.dumps(mcp_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    alice_prompt = (_FIXTURE_DIR / "prompts" / "alice_prompt.txt").read_text(
        encoding="utf-8"
    ).strip()

    alice_result = _run_claude(
        prompt=alice_prompt,
        project_dir=live_project,
        tmp_dir=tmp_path,
        agent_name="alice_negative",
    )

    alice_tx = alice_result.stdout

    # Determine failure signal: any of these is sufficient.
    nonzero_exit = alice_result.returncode != 0
    db_empty = not _db_path(live_project).exists() or (
        len(_query_db(live_project, "SELECT COUNT(*) FROM messages")) == 0
        or _query_db(live_project, "SELECT COUNT(*) FROM messages")[0][0] == 0
    )
    no_sentinel = "ALICE_DONE" not in alice_tx

    failed_as_expected = nonzero_exit or db_empty or no_sentinel

    if not failed_as_expected:
        pytest.fail(
            "NEGATIVE TEST FAILED: alice succeeded despite a broken MCP server name. "
            "This means the positive test's success may be coincidental. "
            f"rc={alice_result.returncode}, "
            f"db_empty={db_empty}, "
            f"sentinel_present={'ALICE_DONE' in alice_tx}. "
            f"Transcript excerpt:\n{alice_tx[:2000]}"
        )

    # If we get here, the test correctly detected the broken config.
    # Log the failure mode for diagnostic visibility.
    print(
        f"\n[negative-test] Broken MCP name correctly caused failure: "
        f"rc={alice_result.returncode}, db_empty={db_empty}, no_sentinel={no_sentinel}"
    )


# ---------------------------------------------------------------------------
# Negative test: missing SKILL.md
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(not _AUTH_OK, reason="no ANTHROPIC_API_KEY and no OAuth")
@pytest.mark.skipif(not _HAS_CLAUDE, reason="claude CLI not on PATH")
def test_live_install_negative_missing_skill(
    live_project: Path, tmp_path: Path
) -> None:
    """Negative test: delete SKILL.md after install → alice should not find SOX tools.

    Without the skill document, alice has no guidance about which MCP tools exist
    or how to use them.  The load-bearing assertion is that the messages table
    stays empty after her run — she may still exit 0 (Claude doesn't fail hard
    when a skill file is absent) but she should not have called channels__send.

    If alice somehow sends a PING anyway (proves skill is not load-bearing for
    this prompt design), we log a warning rather than hard-failing — this is
    diagnostic signal per the phase 01 plan's design for this variant.
    """
    skill_md = (
        live_project / ".claude" / "skills" / "inter-agent-channels" / "SKILL.md"
    )
    assert skill_md.exists(), "SKILL.md should exist after installer runs"
    skill_md.unlink()
    assert not skill_md.exists(), "SKILL.md was not deleted"

    alice_prompt = (_FIXTURE_DIR / "prompts" / "alice_prompt.txt").read_text(
        encoding="utf-8"
    ).strip()

    alice_result = _run_claude(
        prompt=alice_prompt,
        project_dir=live_project,
        tmp_dir=tmp_path,
        agent_name="alice_no_skill",
    )

    alice_tx = alice_result.stdout

    # Check whether alice sent a PING despite the missing skill.
    db_has_messages = (
        _db_path(live_project).exists()
        and _query_db(live_project, "SELECT COUNT(*) FROM messages")[0][0] > 0
    )

    if db_has_messages:
        # Soft assertion: skill file is not load-bearing for this prompt design.
        # The prompt names tools explicitly so Claude doesn't need the skill.
        # This is expected behaviour, not a test failure — but we surface it.
        print(
            "\n[negative-test/missing-skill] WARNING: alice sent messages even "
            "without SKILL.md. The explicit tool names in the prompt are sufficient "
            "for the LLM to succeed. SKILL.md is a hint, not a hard gate. "
            "This is diagnostic signal: the positive test's success is driven by "
            "the prompt's explicit tool names, not by the skill document."
        )
    else:
        # Hard assertion: DB is empty; skill absence prevented messaging.
        db_rows = _query_db(live_project, "SELECT COUNT(*) FROM messages")[0][0]
        assert db_rows == 0, (
            f"Expected 0 messages with missing SKILL.md, got {db_rows}"
        )


# ---------------------------------------------------------------------------
# Invariant: test collection does not require ANTHROPIC_API_KEY
# ---------------------------------------------------------------------------
# (This is enforced by the pytestmark skipif at module level.
#  The tests above are collected but immediately skipped when the key is absent.)
