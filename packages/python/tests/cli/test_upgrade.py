# SPDX-License-Identifier: Apache-2.0
"""Tests for ``sox-protocol upgrade``.

Coverage areas:
- ``_discover_db_path`` for sqlite:////, sqlite:///, memory://, missing
  .mcp.json, falling back to env, non-existent fields.
- ``upgrade_command`` flow: file refresh + migration; ``--quiet``;
  ``--no-migrate``; non-SQLite backing store (no migration step).
- ``_run_migration`` smoke against a real tmp DB (creates fresh + idempotent
  re-migration is a no-op).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from sox_protocol.cli.upgrade import (
    _discover_db_path,
    _run_migration,
    upgrade_command,
)


def _write_mcp_json(project_dir: Path, env: dict[str, str]) -> None:
    """Helper: write a minimal .mcp.json with the given sox env block."""
    cfg = {"mcpServers": {"sox": {"env": env}}}
    (project_dir / ".mcp.json").write_text(json.dumps(cfg))


# ---------------------------------------------------------------------------
# _discover_db_path
# ---------------------------------------------------------------------------


def test_discover_db_path_sqlite_absolute(tmp_path: Path) -> None:
    """sqlite:/// → absolute Path returned."""
    target = tmp_path / "sub" / "messages.db"
    _write_mcp_json(tmp_path, {"SOX_BACKING_STORE": f"sqlite:///{target}"})
    found = _discover_db_path(tmp_path)
    assert found == Path(str(target))


def test_discover_db_path_sqlite_quad_slash(tmp_path: Path) -> None:
    """sqlite://// (urlparse returns //path; we collapse to /path)."""
    target = tmp_path / "messages.db"
    _write_mcp_json(tmp_path, {"SOX_BACKING_STORE": f"sqlite:///{target}"})
    found = _discover_db_path(tmp_path)
    assert found is not None
    # Path should not start with double slash
    assert not str(found).startswith("//")


def test_discover_db_path_memory_returns_none(tmp_path: Path) -> None:
    """memory:// scheme → no on-disk file → returns None."""
    _write_mcp_json(tmp_path, {"SOX_BACKING_STORE": "memory://"})
    assert _discover_db_path(tmp_path) is None


def test_discover_db_path_sqlite_memory_uri_returns_none(tmp_path: Path) -> None:
    """sqlite://:memory: → ephemeral → returns None."""
    _write_mcp_json(tmp_path, {"SOX_BACKING_STORE": "sqlite:///:memory:"})
    assert _discover_db_path(tmp_path) is None


def test_discover_db_path_missing_mcp_json_returns_none(tmp_path: Path) -> None:
    """No .mcp.json + no env → None."""
    monkeypatch_env: dict[str, str] = {}
    with patch.dict("os.environ", monkeypatch_env, clear=True):
        assert _discover_db_path(tmp_path) is None


def test_discover_db_path_falls_back_to_env(tmp_path: Path) -> None:
    """No .mcp.json but SOX_BACKING_STORE in env → use env."""
    target = tmp_path / "fromenv.db"
    with patch.dict("os.environ", {"SOX_BACKING_STORE": f"sqlite:///{target}"}):
        found = _discover_db_path(tmp_path)
    assert found == Path(str(target))


def test_discover_db_path_unknown_scheme_returns_none(tmp_path: Path) -> None:
    """nats:// / redis:// / file:// / anything-other-than-sqlite → None."""
    _write_mcp_json(tmp_path, {"SOX_BACKING_STORE": "redis://localhost:6379"})
    assert _discover_db_path(tmp_path) is None


def test_discover_db_path_malformed_mcp_json(tmp_path: Path) -> None:
    """Malformed .mcp.json is logged and ignored — falls back to env (none here)."""
    (tmp_path / ".mcp.json").write_text("{not valid json")
    with patch.dict("os.environ", {}, clear=True):
        assert _discover_db_path(tmp_path) is None


# ---------------------------------------------------------------------------
# _run_migration — async smoke tests
# ---------------------------------------------------------------------------


def test_run_migration_fresh_db_stamps_latest(tmp_path: Path) -> None:
    """Fresh DB: SqliteStore.initialize() runs schema.sql + stamps target version."""
    db_path = tmp_path / "fresh.db"
    starting, applied, target = asyncio.run(_run_migration(db_path))
    assert starting == "0.0"
    # Fresh DB initialized via SqliteStore — the chain doesn't run because
    # schema.sql produces the latest shape.  We expect applied=[].
    assert applied == []
    # Target should be a non-empty semver-ish string.
    assert target

    # Schema version stamped.
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT value FROM _sox_meta WHERE key='schema_version'").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == target


def test_run_migration_idempotent(tmp_path: Path) -> None:
    """Running twice on the same DB applies nothing the second time."""
    db_path = tmp_path / "twice.db"
    asyncio.run(_run_migration(db_path))
    starting, applied, target = asyncio.run(_run_migration(db_path))
    assert applied == []
    assert starting == target


# ---------------------------------------------------------------------------
# upgrade_command — full flow with mocked installer
# ---------------------------------------------------------------------------


def test_upgrade_command_runs_install_and_migration(tmp_path: Path, capsys) -> None:
    """upgrade refreshes files (via real installer) AND migrates."""
    rc = upgrade_command(
        argparse.Namespace(project_dir=tmp_path, quiet=False, no_migrate=False, skip_pip=True, check_only=False)
    )
    assert rc == 0
    out = capsys.readouterr().out
    # skip_pip=True → Step 1/3 reports SKIPPED, Step 2/3 + 3/3 still run.
    assert "Step 1/3" in out
    assert "Step 2/3" in out
    assert "Step 3/3" in out
    assert "Upgrade complete" in out
    # Files written by the installer:
    assert (tmp_path / ".mcp.json").is_file()
    assert (tmp_path / ".sox" / "messages.db").is_file()


def test_upgrade_command_quiet_suppresses_output(tmp_path: Path, capsys) -> None:
    """--quiet suppresses the per-step log."""
    rc = upgrade_command(
        argparse.Namespace(project_dir=tmp_path, quiet=True, no_migrate=False, skip_pip=True, check_only=False)
    )
    assert rc == 0
    out = capsys.readouterr().out
    # In quiet mode, the per-step log AND the final summary are suppressed.
    assert "Step 1/3" not in out
    assert "Step 2/3" not in out
    assert "Step 3/3" not in out


def test_upgrade_command_no_migrate(tmp_path: Path, capsys) -> None:
    """--no-migrate skips the SQLite step."""
    rc = upgrade_command(
        argparse.Namespace(project_dir=tmp_path, quiet=False, no_migrate=True, skip_pip=True, check_only=False)
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "SKIPPED (--no-migrate)" in out
    # The DB is still created by the installer's _update_mcp_json side-effect
    # (or rather: the install step writes .mcp.json which references .sox/messages.db
    # but doesn't create the DB itself).  We only assert that the migrate path
    # was not executed.


def test_upgrade_command_non_sqlite_backing_store_skips_migration(
    tmp_path: Path, capsys
) -> None:
    """If the backing store is non-SQLite, the migration step prints + skips cleanly."""
    # Run install first so .mcp.json exists.
    upgrade_command(
        argparse.Namespace(project_dir=tmp_path, quiet=True, no_migrate=False, skip_pip=True, check_only=False)
    )
    # Overwrite .mcp.json with a non-SQLite backing store URL.
    cfg_path = tmp_path / ".mcp.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["mcpServers"]["sox"]["env"]["SOX_BACKING_STORE"] = "memory://"
    cfg_path.write_text(json.dumps(cfg))

    capsys.readouterr()  # clear previous output
    rc = upgrade_command(
        argparse.Namespace(project_dir=tmp_path, quiet=False, no_migrate=False, skip_pip=True, check_only=False)
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "No SQLite backing store found" in out


# ---------------------------------------------------------------------------
# PyPI version check + pip-upgrade behavior (0.1.6+)
# ---------------------------------------------------------------------------


def test_check_packages_marks_outdated_correctly(monkeypatch) -> None:
    """_check_packages compares local vs PyPI and flags outdated rows."""
    from sox_protocol.cli import upgrade as up

    fake_local = {"sox-protocol": "0.1.0", "sox-plugin-schema-strict": "1.0.0"}
    fake_remote = {"sox-protocol": "0.1.5", "sox-plugin-schema-strict": "1.0.0"}
    monkeypatch.setattr(up, "_local_version", fake_local.get)
    monkeypatch.setattr(up, "_fetch_latest_pypi_version", fake_remote.get)

    rows = up._check_packages()
    by_name = {r[0]: r for r in rows}
    assert by_name["sox-protocol"] == ("sox-protocol", "0.1.0", "0.1.5", True)
    # Equal versions → not outdated.
    assert by_name["sox-plugin-schema-strict"][3] is False


def test_check_packages_handles_missing_local_or_remote(monkeypatch) -> None:
    """Missing local install or unreachable PyPI → not outdated, no crash."""
    from sox_protocol.cli import upgrade as up

    monkeypatch.setattr(up, "_local_version", lambda _name: None)
    monkeypatch.setattr(up, "_fetch_latest_pypi_version", lambda _name: None)
    rows = up._check_packages(("sox-protocol",))
    assert rows == [("sox-protocol", None, None, False)]


def test_check_only_reports_drift_and_exits(tmp_path, capsys, monkeypatch) -> None:
    """--check-only prints the table and returns 0 without touching anything."""
    from sox_protocol.cli import upgrade as up

    monkeypatch.setattr(up, "_local_version", lambda name: {
        "sox-protocol": "0.1.0",
        "sox-plugin-schema-strict": "1.0.0",
    }.get(name))
    monkeypatch.setattr(up, "_fetch_latest_pypi_version", lambda name: {
        "sox-protocol": "0.1.5",
        "sox-plugin-schema-strict": "1.0.0",
    }.get(name))
    # Sentinel: pip_upgrade and install must NOT be called.
    pip_called = False

    def _no_pip(*_a, **_k):
        nonlocal pip_called
        pip_called = True
        return 0

    monkeypatch.setattr(up, "_pip_upgrade", _no_pip)

    rc = upgrade_command(argparse.Namespace(
        project_dir=tmp_path, quiet=False,
        no_migrate=False, skip_pip=False, check_only=True,
    ))
    assert rc == 0
    assert pip_called is False
    out = capsys.readouterr().out
    assert "upgrade available" in out
    assert "sox-protocol" in out


def test_pip_upgrade_only_runs_for_outdated_and_reexecs(monkeypatch, tmp_path) -> None:
    """When PyPI reports newer, _pip_upgrade is called and we re-exec."""
    from sox_protocol.cli import upgrade as up

    monkeypatch.setattr(up, "_local_version", lambda name: "0.1.0")
    monkeypatch.setattr(up, "_fetch_latest_pypi_version", lambda name: "0.1.5")

    pip_calls: list[list[str]] = []

    def _fake_pip(packages, *, quiet):
        pip_calls.append(list(packages))
        return 0

    reexec_calls: list[tuple[str, ...]] = []

    def _fake_reexec(*args):
        reexec_calls.append(args)
        # Don't actually exec — let upgrade_command return.
        raise SystemExit(0)

    monkeypatch.setattr(up, "_pip_upgrade", _fake_pip)
    monkeypatch.setattr(up, "_reexec_self", _fake_reexec)

    with __import__("pytest").raises(SystemExit):
        upgrade_command(argparse.Namespace(
            project_dir=tmp_path, quiet=True,
            no_migrate=False, skip_pip=False, check_only=False,
        ))

    assert len(pip_calls) == 1
    # Both tracked packages are flagged outdated → both upgraded.
    assert "sox-protocol" in pip_calls[0]
    assert "sox-plugin-schema-strict" in pip_calls[0]
    assert len(reexec_calls) == 1


def test_pip_upgrade_failure_returns_nonzero(monkeypatch, tmp_path, capsys) -> None:
    """If pip exits non-zero, upgrade_command returns the same code without re-exec."""
    from sox_protocol.cli import upgrade as up

    monkeypatch.setattr(up, "_local_version", lambda name: "0.1.0")
    monkeypatch.setattr(up, "_fetch_latest_pypi_version", lambda name: "0.1.5")
    monkeypatch.setattr(up, "_pip_upgrade", lambda packages, *, quiet: 7)

    reexec_called = False

    def _fake_reexec(*_args):
        nonlocal reexec_called
        reexec_called = True

    monkeypatch.setattr(up, "_reexec_self", _fake_reexec)

    rc = upgrade_command(argparse.Namespace(
        project_dir=tmp_path, quiet=False,
        no_migrate=False, skip_pip=False, check_only=False,
    ))
    assert rc == 7
    assert reexec_called is False
    out = capsys.readouterr().out
    assert "[FAIL]" in out


def test_skip_pip_short_circuits_to_install_step(tmp_path, capsys, monkeypatch) -> None:
    """--skip-pip prints SKIPPED and proceeds to file refresh + migration."""
    from sox_protocol.cli import upgrade as up

    # If anything in the pip path is hit, fail loudly.
    monkeypatch.setattr(up, "_check_packages",
                        lambda *_a, **_k: pytest.fail("pip path executed despite --skip-pip"))

    rc = upgrade_command(argparse.Namespace(
        project_dir=tmp_path, quiet=False,
        no_migrate=False, skip_pip=True, check_only=False,
    ))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Step 1/3" in out
    assert "SKIPPED (--skip-pip)" in out
    assert "Step 2/3" in out  # install step still ran
    assert "Step 3/3" in out  # migrate step still ran


def test_check_only_with_no_drift_reports_up_to_date(tmp_path, capsys, monkeypatch) -> None:
    """All packages at latest → 'All tracked packages are up to date.'"""
    from sox_protocol.cli import upgrade as up

    monkeypatch.setattr(up, "_local_version", lambda _name: "1.0.0")
    monkeypatch.setattr(up, "_fetch_latest_pypi_version", lambda _name: "1.0.0")

    rc = upgrade_command(argparse.Namespace(
        project_dir=tmp_path, quiet=False,
        no_migrate=False, skip_pip=False, check_only=True,
    ))
    assert rc == 0
    out = capsys.readouterr().out
    assert "All tracked packages are up to date." in out
