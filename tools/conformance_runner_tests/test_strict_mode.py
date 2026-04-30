# SPDX-License-Identifier: Apache-2.0
"""Tests for strict mode: pending fixtures skipped under --strict; counted non-strict."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from conformance_runner import (
    Fixture,
    FixtureResult,
    RunResult,
    load_fixture,
    load_fixtures,
    run,
    run_fixture,
)
from conformance_runner_tests.conftest import FakeTarget


def _write_fixture(path: Path, pending: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        name: test-fixture
        spec_ref: spec/protocol.md
        description: test
        {"pending: true" if pending else ""}
        agents:
          - id: agent-a
            credential: secret-a
        sequence:
          - id: step-1
            as_agent: agent-a
            operation: recv
            input: {{}}
        assertions: []
    """)
    path.write_text(content, encoding="utf-8")
    return path


class TestStrictModeSkipsPending:
    """Pending fixtures are skipped in --strict mode."""

    def test_pending_fixture_skipped_in_strict(self, tmp_path: Path) -> None:
        fixture_path = _write_fixture(tmp_path / "cat" / "fix.yaml", pending=True)
        fixture = load_fixture(fixture_path)
        assert fixture.pending is True

        result = run_fixture(fixture, str(tmp_path), strict=True)
        assert result.skipped is True
        assert result.passed is True  # Skipped counts as not-failed

    def test_pending_fixture_runs_in_non_strict(
        self, tmp_path: Path, fake_target: FakeTarget
    ) -> None:
        fixture_path = _write_fixture(tmp_path / "cat" / "fix.yaml", pending=True)
        fixture = load_fixture(fixture_path)

        # patch _make_target to return our fake
        with patch("conformance_runner._make_target", return_value=fake_target):
            result = run_fixture(fixture, str(tmp_path), strict=False)
        assert result.skipped is False

    def test_non_pending_fixture_runs_in_strict(
        self, tmp_path: Path, fake_target: FakeTarget
    ) -> None:
        fixture_path = _write_fixture(tmp_path / "cat" / "fix.yaml", pending=False)
        fixture = load_fixture(fixture_path)

        with patch("conformance_runner._make_target", return_value=fake_target):
            result = run_fixture(fixture, str(tmp_path), strict=True)
        assert result.skipped is False


class TestRunResultCounting:
    """RunResult correctly counts pending vs non-pending results."""

    def _make_fixture(self, tmp_path: Path, pending: bool = False) -> Fixture:
        p = _write_fixture(tmp_path / f"fix-{pending}.yaml", pending=pending)
        return load_fixture(p)

    def test_skipped_count_in_run_result(self, tmp_path: Path) -> None:
        fixtures: list[Fixture] = []
        for i, pending in enumerate([True, True, False]):
            p = tmp_path / f"fix{i}.yaml"
            _write_fixture(p, pending=pending)
            fixtures.append(load_fixture(p))

        fake = FakeTarget()
        with patch("conformance_runner._make_target", return_value=fake):
            result = run(str(tmp_path), fixtures, strict=True)

        assert result.skipped == 2
        assert result.total == 3

    def test_pending_in_non_strict_adds_to_total(self, tmp_path: Path) -> None:
        fixtures: list[Fixture] = []
        for i, pending in enumerate([True, False]):
            p = tmp_path / f"fix{i}.yaml"
            _write_fixture(p, pending=pending)
            fixtures.append(load_fixture(p))

        fake = FakeTarget()
        with patch("conformance_runner._make_target", return_value=fake):
            result = run(str(tmp_path), fixtures, strict=False)

        assert result.total == 2
        assert result.skipped == 0


class TestStrictModeExitCode:
    """Exit code is 0 when all non-skipped fixtures pass."""

    def test_all_skipped_exit_code_zero(self, tmp_path: Path) -> None:
        result = RunResult()
        fixture_path = _write_fixture(tmp_path / "fix.yaml", pending=True)
        fixture = load_fixture(fixture_path)
        result.fixture_results.append(
            FixtureResult(fixture=fixture, passed=True, skipped=True)
        )
        assert result.exit_code == 0

    def test_one_failure_exit_code_one(self, tmp_path: Path) -> None:
        result = RunResult()
        fixture_path = _write_fixture(tmp_path / "fix.yaml", pending=False)
        fixture = load_fixture(fixture_path)
        result.fixture_results.append(
            FixtureResult(
                fixture=fixture,
                passed=False,
                skipped=False,
                error="Something failed",
            )
        )
        assert result.exit_code == 1

    def test_mixed_pass_and_skip_exit_code_zero(self, tmp_path: Path) -> None:
        result = RunResult()
        for i, (passed, skipped) in enumerate([(True, False), (True, True)]):
            p = _write_fixture(tmp_path / f"fix{i}.yaml", pending=skipped)
            f = load_fixture(p)
            result.fixture_results.append(
                FixtureResult(fixture=f, passed=passed, skipped=skipped)
            )
        assert result.exit_code == 0
