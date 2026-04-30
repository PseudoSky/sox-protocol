# SPDX-License-Identifier: Apache-2.0
"""Tests for RunResult, FixtureResult, StepResult diff formatting, exit codes."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from conformance_runner import (
    Fixture,
    FixtureResult,
    RunResult,
    StepResult,
    _diff_str,
    _matches,
    evaluate_assertions,
    load_fixture,
    run,
    run_fixture,
)
from conformance_runner_tests.conftest import FakeTarget


def _make_fixture(tmp_path: Path, name: str = "test-fixture") -> Fixture:
    p = tmp_path / f"{name}.yaml"
    p.write_text(
        textwrap.dedent(f"""\
            name: {name}
            spec_ref: spec/protocol.md
            description: test
            agents:
              - id: agent-a
                credential: secret-a
            sequence:
              - id: step-1
                as_agent: agent-a
                operation: recv
                input: {{}}
            assertions: []
        """),
        encoding="utf-8",
    )
    return load_fixture(p)


class TestMatchesHelper:
    """Tests for the _matches() subset-match helper."""

    def test_exact_string_match(self) -> None:
        ok, _ = _matches("hello", "hello", {})
        assert ok

    def test_string_mismatch(self) -> None:
        ok, reason = _matches("hello", "world", {})
        assert not ok
        assert "world" in reason

    def test_any_string_wildcard(self) -> None:
        ok, _ = _matches("{{any_string}}", "anything", {})
        assert ok

    def test_any_string_wildcard_rejects_non_string(self) -> None:
        ok, reason = _matches("{{any_string}}", 42, {})
        assert not ok
        assert "any_string" in reason

    def test_any_number_wildcard(self) -> None:
        ok, _ = _matches("{{any_number}}", 3.14, {})
        assert ok

    def test_any_number_wildcard_rejects_string(self) -> None:
        ok, _ = _matches("{{any_number}}", "not-a-number", {})
        assert not ok

    def test_any_array_wildcard(self) -> None:
        ok, _ = _matches("{{any_array}}", [1, 2, 3], {})
        assert ok

    def test_any_array_rejects_dict(self) -> None:
        ok, _ = _matches("{{any_array}}", {"key": "val"}, {})
        assert not ok

    def test_any_object_wildcard(self) -> None:
        ok, _ = _matches("{{any_object}}", {"a": 1}, {})
        assert ok

    def test_any_bool_wildcard(self) -> None:
        ok, _ = _matches("{{any_bool}}", True, {})
        assert ok

    def test_capture_reference_matches(self) -> None:
        captures = {"step-1.message_id": "msg-abc"}
        ok, _ = _matches("{{capture:step-1.message_id}}", "msg-abc", captures)
        assert ok

    def test_capture_reference_mismatch(self) -> None:
        captures = {"step-1.message_id": "msg-abc"}
        ok, reason = _matches("{{capture:step-1.message_id}}", "msg-xyz", captures)
        assert not ok
        assert "msg-abc" in reason

    def test_capture_key_not_found(self) -> None:
        ok, reason = _matches("{{capture:missing.key}}", "val", {})
        assert not ok
        assert "not found" in reason

    def test_dict_subset_match(self) -> None:
        ok, _ = _matches({"a": 1}, {"a": 1, "b": 2}, {})
        assert ok

    def test_dict_missing_key(self) -> None:
        ok, reason = _matches({"a": 1, "c": 3}, {"a": 1}, {})
        assert not ok
        assert "'c'" in reason

    def test_dict_nested_mismatch(self) -> None:
        ok, reason = _matches({"a": {"b": 1}}, {"a": {"b": 2}}, {})
        assert not ok

    def test_list_subset_match(self) -> None:
        ok, _ = _matches([1, 2], [1, 2, 3], {})
        assert ok

    def test_list_too_short(self) -> None:
        ok, reason = _matches([1, 2, 3], [1, 2], {})
        assert not ok
        assert "at least 3" in reason

    def test_scalar_integer_match(self) -> None:
        ok, _ = _matches(42, 42, {})
        assert ok

    def test_scalar_integer_mismatch(self) -> None:
        ok, reason = _matches(42, 43, {})
        assert not ok

    def test_actual_not_dict_when_expected_dict(self) -> None:
        ok, reason = _matches({"a": 1}, "not-a-dict", {})
        assert not ok
        assert "dict" in reason

    def test_actual_not_list_when_expected_list(self) -> None:
        ok, reason = _matches([1], "not-a-list", {})
        assert not ok
        assert "list" in reason


class TestDiffStr:
    """Tests for _diff_str() formatting."""

    def test_diff_shows_expected_and_actual(self) -> None:
        diff = _diff_str({"a": 1}, {"a": 2})
        assert "expected" in diff
        assert "actual" in diff

    def test_identical_values_empty_diff(self) -> None:
        diff = _diff_str({"a": 1}, {"a": 1})
        assert diff == ""

    def test_diff_is_string(self) -> None:
        diff = _diff_str({"x": 1}, {"x": 9})
        assert isinstance(diff, str)


class TestEvaluateAssertions:
    """Tests for evaluate_assertions()."""

    def _step(self, step_id: str, messages: list) -> dict:
        return {
            step_id: StepResult(
                step_id=step_id,
                ok=True,
                output={"drained_at": 1.0, "messages": messages},
            )
        }

    def test_no_loss_passes(self) -> None:
        steps = self._step("recv-1", [{"message_id": "m1"}])
        errors = evaluate_assertions(
            [{"type": "no_loss", "recv_step": "recv-1", "min": 1}], steps
        )
        assert errors == []

    def test_no_loss_fails(self) -> None:
        steps = self._step("recv-1", [])
        errors = evaluate_assertions(
            [{"type": "no_loss", "recv_step": "recv-1", "min": 1}], steps
        )
        assert len(errors) == 1
        assert "no_loss" in errors[0]

    def test_no_duplication_passes(self) -> None:
        steps = self._step("recv-1", [
            {"message_id": "m1"},
            {"message_id": "m2"},
        ])
        errors = evaluate_assertions(
            [{"type": "no_duplication", "recv_step": "recv-1"}], steps
        )
        assert errors == []

    def test_no_duplication_fails(self) -> None:
        steps = self._step("recv-1", [
            {"message_id": "m1"},
            {"message_id": "m1"},
        ])
        errors = evaluate_assertions(
            [{"type": "no_duplication", "recv_step": "recv-1"}], steps
        )
        assert len(errors) == 1

    def test_no_redelivery_passes(self) -> None:
        steps = self._step("recv-2", [])
        errors = evaluate_assertions(
            [{"type": "no_redelivery", "recv_step": "recv-2", "expected_count": 0}],
            steps,
        )
        assert errors == []

    def test_no_redelivery_fails(self) -> None:
        steps = self._step("recv-2", [{"message_id": "m1"}])
        errors = evaluate_assertions(
            [{"type": "no_redelivery", "recv_step": "recv-2", "expected_count": 0}],
            steps,
        )
        assert len(errors) == 1

    def test_ordering_passes(self) -> None:
        steps = self._step("recv-1", [
            {"message_id": "m1", "channel": "ch", "seq": 1},
            {"message_id": "m2", "channel": "ch", "seq": 2},
            {"message_id": "m3", "channel": "ch", "seq": 3},
        ])
        errors = evaluate_assertions(
            [{"type": "ordering", "recv_step": "recv-1", "channel": "ch", "by": "seq"}],
            steps,
        )
        assert errors == []

    def test_ordering_fails(self) -> None:
        steps = self._step("recv-1", [
            {"message_id": "m1", "channel": "ch", "seq": 3},
            {"message_id": "m2", "channel": "ch", "seq": 1},
        ])
        errors = evaluate_assertions(
            [{"type": "ordering", "recv_step": "recv-1", "channel": "ch", "by": "seq"}],
            steps,
        )
        assert len(errors) == 1

    def test_received_count_passes(self) -> None:
        steps = self._step("recv-1", [{"message_id": "m1"}, {"message_id": "m2"}])
        errors = evaluate_assertions(
            [{"type": "received_count", "recv_step": "recv-1", "min": 2, "max": 2}],
            steps,
        )
        assert errors == []

    def test_received_count_fails_below_min(self) -> None:
        steps = self._step("recv-1", [])
        errors = evaluate_assertions(
            [{"type": "received_count", "recv_step": "recv-1", "min": 2, "max": 5}],
            steps,
        )
        assert len(errors) == 1

    def test_no_channel_leak_passes(self) -> None:
        steps = self._step("recv-1", [{"message_id": "m1", "channel": "team/eng"}])
        errors = evaluate_assertions(
            [{"type": "no_channel_leak", "recv_step": "recv-1", "forbidden_channel": "ops/eng"}],
            steps,
        )
        assert errors == []

    def test_no_channel_leak_fails(self) -> None:
        steps = self._step("recv-1", [{"message_id": "m1", "channel": "ops/eng"}])
        errors = evaluate_assertions(
            [{"type": "no_channel_leak", "recv_step": "recv-1", "forbidden_channel": "ops/eng"}],
            steps,
        )
        assert len(errors) == 1

    def test_all_channels_match_pattern_passes(self) -> None:
        steps = self._step("recv-1", [
            {"message_id": "m1", "channel": "team/eng"},
            {"message_id": "m2", "channel": "team/ops"},
        ])
        errors = evaluate_assertions(
            [{"type": "all_channels_match_pattern", "recv_step": "recv-1", "pattern": "team/*"}],
            steps,
        )
        assert errors == []

    def test_all_channels_match_pattern_fails(self) -> None:
        steps = self._step("recv-1", [
            {"message_id": "m1", "channel": "other/chan"},
        ])
        errors = evaluate_assertions(
            [{"type": "all_channels_match_pattern", "recv_step": "recv-1", "pattern": "team/*"}],
            steps,
        )
        assert len(errors) == 1

    def test_all_receivers_got_message_passes(self) -> None:
        step_results = {
            "recv-a": StepResult(
                step_id="recv-a", ok=True,
                output={"drained_at": 1.0, "messages": [{"message_id": "m1"}]},
            ),
            "recv-b": StepResult(
                step_id="recv-b", ok=True,
                output={"drained_at": 1.0, "messages": [{"message_id": "m2"}]},
            ),
        }
        errors = evaluate_assertions(
            [{"type": "all_receivers_got_message", "recv_steps": ["recv-a", "recv-b"]}],
            step_results,
        )
        assert errors == []

    def test_all_receivers_got_message_fails(self) -> None:
        step_results = {
            "recv-a": StepResult(
                step_id="recv-a", ok=True,
                output={"drained_at": 1.0, "messages": []},
            ),
        }
        errors = evaluate_assertions(
            [{"type": "all_receivers_got_message", "recv_steps": ["recv-a"]}],
            step_results,
        )
        assert len(errors) == 1

    def test_unknown_assertion_type_produces_error(self) -> None:
        errors = evaluate_assertions(
            [{"type": "totally_unknown_type"}], {}
        )
        assert len(errors) == 1
        assert "Unknown assertion" in errors[0]

    def test_schema_valid_is_informational(self) -> None:
        errors = evaluate_assertions(
            [{"type": "schema_valid"}], {}
        )
        assert errors == []


class TestFixtureResult:
    """Tests for FixtureResult summary and detail output."""

    def test_summary_line_pass(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "pass-test")
        result = FixtureResult(fixture=fixture, passed=True, skipped=False)
        assert "PASS" in result.summary_line()

    def test_summary_line_fail(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "fail-test")
        result = FixtureResult(fixture=fixture, passed=False, skipped=False)
        assert "FAIL" in result.summary_line()

    def test_summary_line_skip(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "skip-test")
        result = FixtureResult(fixture=fixture, passed=True, skipped=True)
        assert "SKIP" in result.summary_line()

    def test_detail_empty_for_passing(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        result = FixtureResult(fixture=fixture, passed=True, skipped=False)
        assert result.detail() == ""

    def test_detail_empty_for_skipped(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        result = FixtureResult(fixture=fixture, passed=True, skipped=True)
        assert result.detail() == ""

    def test_detail_includes_error_for_failure(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        result = FixtureResult(
            fixture=fixture,
            passed=False,
            skipped=False,
            error="Something went wrong",
        )
        assert "Something went wrong" in result.detail()

    def test_detail_includes_step_failure(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        result = FixtureResult(
            fixture=fixture,
            passed=False,
            skipped=False,
            step_results=[
                StepResult(step_id="step-bad", ok=False, output=None, error="bad value")
            ],
        )
        assert "step-bad" in result.detail()
        assert "bad value" in result.detail()

    def test_detail_includes_assertion_errors(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        result = FixtureResult(
            fixture=fixture,
            passed=False,
            skipped=False,
            assertion_errors=["no_loss failed"],
        )
        assert "no_loss failed" in result.detail()


class TestRunResult:
    """Tests for RunResult aggregation and reporting."""

    def _make_fr(
        self, tmp_path: Path, passed: bool, skipped: bool = False, idx: int = 0
    ) -> FixtureResult:
        fixture = _make_fixture(tmp_path, f"fixture-{idx}")
        return FixtureResult(fixture=fixture, passed=passed, skipped=skipped)

    def test_passed_count(self, tmp_path: Path) -> None:
        rr = RunResult()
        rr.fixture_results = [
            self._make_fr(tmp_path, True, idx=0),
            self._make_fr(tmp_path, True, idx=1),
            self._make_fr(tmp_path, False, idx=2),
        ]
        assert rr.passed == 2

    def test_failed_count(self, tmp_path: Path) -> None:
        rr = RunResult()
        rr.fixture_results = [
            self._make_fr(tmp_path, False, idx=0),
            self._make_fr(tmp_path, True, idx=1),
        ]
        assert rr.failed == 1

    def test_skipped_count(self, tmp_path: Path) -> None:
        rr = RunResult()
        rr.fixture_results = [
            self._make_fr(tmp_path, True, skipped=True, idx=0),
            self._make_fr(tmp_path, True, skipped=False, idx=1),
        ]
        assert rr.skipped == 1

    def test_total_count(self, tmp_path: Path) -> None:
        rr = RunResult()
        rr.fixture_results = [
            self._make_fr(tmp_path, True, idx=i) for i in range(5)
        ]
        assert rr.total == 5

    def test_exit_code_zero_all_pass(self, tmp_path: Path) -> None:
        rr = RunResult()
        rr.fixture_results = [self._make_fr(tmp_path, True, idx=0)]
        assert rr.exit_code == 0

    def test_exit_code_one_on_failure(self, tmp_path: Path) -> None:
        rr = RunResult()
        rr.fixture_results = [self._make_fr(tmp_path, False, idx=0)]
        assert rr.exit_code == 1

    def test_report_contains_summary_line(self, tmp_path: Path) -> None:
        rr = RunResult()
        rr.fixture_results = [self._make_fr(tmp_path, True, idx=0)]
        report = rr.report()
        assert "Results:" in report
        assert "passed" in report

    def test_report_contains_fixture_path(self, tmp_path: Path) -> None:
        rr = RunResult()
        rr.fixture_results = [self._make_fr(tmp_path, True, idx=0)]
        report = rr.report()
        assert "fixture-0" in report


class TestRunFixture:
    """Tests for run_fixture() integration."""

    def test_run_fixture_passes_with_fake_target(
        self, tmp_path: Path, fake_target: FakeTarget
    ) -> None:
        fixture = _make_fixture(tmp_path)
        with patch("conformance_runner._make_target", return_value=fake_target):
            result = run_fixture(fixture, str(tmp_path), strict=False)
        assert result.passed

    def test_run_fixture_fails_on_target_start_error(
        self, tmp_path: Path
    ) -> None:
        fixture = _make_fixture(tmp_path)
        bad_target = FakeTarget()

        def bad_start(agent_id: str) -> None:
            raise RuntimeError("cannot start")

        bad_target.start = bad_start  # type: ignore[method-assign]

        with patch("conformance_runner._make_target", return_value=bad_target):
            result = run_fixture(fixture, str(tmp_path), strict=False)
        assert not result.passed
        assert "cannot start" in (result.error or "")

    def test_run_fixture_handles_sleep_step(self, tmp_path: Path) -> None:
        p = tmp_path / "sleep-fix.yaml"
        p.write_text(
            textwrap.dedent("""\
                name: sleep-test
                spec_ref: spec/protocol.md
                description: sleep step test
                agents:
                  - id: agent-a
                    credential: secret-a
                sequence:
                  - id: sleep-1
                    type: sleep
                    milliseconds: 1
                  - id: step-2
                    as_agent: agent-a
                    operation: recv
                    input: {}
                assertions: []
            """),
            encoding="utf-8",
        )
        fixture = load_fixture(p)
        fake = FakeTarget()
        with patch("conformance_runner._make_target", return_value=fake):
            result = run_fixture(fixture, str(tmp_path), strict=False)
        assert result.passed

    def test_run_fixture_expected_error_matches(self, tmp_path: Path) -> None:
        p = tmp_path / "err-fix.yaml"
        p.write_text(
            textwrap.dedent("""\
                name: error-test
                spec_ref: spec/protocol.md
                description: error match test
                agents:
                  - id: agent-a
                    credential: secret-a
                sequence:
                  - id: step-err
                    as_agent: agent-a
                    operation: recv
                    input: {}
                    expected_error:
                      message: "{{any_string}}"
                assertions: []
            """),
            encoding="utf-8",
        )
        fixture = load_fixture(p)
        error_target = FakeTarget({"recv": {"_rpc_error": {"message": "REJECTED"}}})
        with patch("conformance_runner._make_target", return_value=error_target):
            result = run_fixture(fixture, str(tmp_path), strict=False)
        assert result.passed

    def test_run_fixture_expected_error_but_got_success_fails(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "err-fail.yaml"
        p.write_text(
            textwrap.dedent("""\
                name: error-fail-test
                spec_ref: spec/protocol.md
                description: expected error but got success
                agents:
                  - id: agent-a
                    credential: secret-a
                sequence:
                  - id: step-ok
                    as_agent: agent-a
                    operation: recv
                    input: {}
                    expected_error:
                      error_code: AUTH_FAILED
                assertions: []
            """),
            encoding="utf-8",
        )
        fixture = load_fixture(p)
        success_target = FakeTarget({"recv": {"drained_at": 1.0, "messages": []}})
        with patch("conformance_runner._make_target", return_value=success_target):
            result = run_fixture(fixture, str(tmp_path), strict=False)
        assert not result.passed

    def test_run_fixture_unexpected_rpc_error_fails(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "rpc-fail.yaml"
        p.write_text(
            textwrap.dedent("""\
                name: rpc-fail-test
                spec_ref: spec/protocol.md
                description: unexpected rpc error
                agents:
                  - id: agent-a
                    credential: secret-a
                sequence:
                  - id: step-rpc
                    as_agent: agent-a
                    operation: recv
                    input: {}
                    expected_output:
                      drained_at: "{{any_number}}"
                      messages: []
                assertions: []
            """),
            encoding="utf-8",
        )
        fixture = load_fixture(p)
        error_target = FakeTarget({"recv": {"_rpc_error": {"message": "SERVER_ERROR"}}})
        with patch("conformance_runner._make_target", return_value=error_target):
            result = run_fixture(fixture, str(tmp_path), strict=False)
        assert not result.passed


class TestMainCLI:
    """Tests for the main() CLI entry point."""

    def test_main_exits_zero_with_passing_fixtures(
        self, tmp_path: Path, fake_target: FakeTarget
    ) -> None:
        from conformance_runner import main
        conf_dir = tmp_path / "conformance"
        conf_dir.mkdir()
        cat = conf_dir / "send-recv-basic"
        cat.mkdir()
        (cat / "fix.yaml").write_text(
            textwrap.dedent("""\
                name: cli-test
                spec_ref: spec/protocol.md
                description: cli test
                agents:
                  - id: agent-a
                    credential: secret-a
                sequence:
                  - id: s1
                    as_agent: agent-a
                    operation: recv
                    input: {}
                assertions: []
            """),
            encoding="utf-8",
        )
        with patch("conformance_runner._make_target", return_value=fake_target):
            rc = main([
                "--target", str(tmp_path),
                "--conformance-root", str(conf_dir),
                "--strict",
            ])
        assert rc == 0

    def test_main_exits_one_on_missing_conformance_root(
        self, tmp_path: Path
    ) -> None:
        from conformance_runner import main
        rc = main([
            "--target", str(tmp_path),
            "--conformance-root", str(tmp_path / "nonexistent"),
        ])
        assert rc == 1

    def test_main_exits_zero_when_no_fixtures(self, tmp_path: Path) -> None:
        from conformance_runner import main
        empty = tmp_path / "empty-conformance"
        empty.mkdir()
        rc = main([
            "--target", str(tmp_path),
            "--conformance-root", str(empty),
        ])
        assert rc == 0

    def test_main_category_filter_applied(
        self, tmp_path: Path, fake_target: FakeTarget
    ) -> None:
        from conformance_runner import main
        conf_dir = tmp_path / "conformance"
        for cat in ("identity-verification", "send-recv-basic"):
            (conf_dir / cat).mkdir(parents=True)
            (conf_dir / cat / "fix.yaml").write_text(
                textwrap.dedent(f"""\
                    name: {cat}-test
                    spec_ref: spec/protocol.md
                    description: {cat}
                    agents:
                      - id: agent-a
                        credential: secret-a
                    sequence:
                      - id: s1
                        as_agent: agent-a
                        operation: recv
                        input: {{}}
                    assertions: []
                """),
                encoding="utf-8",
            )
        with patch("conformance_runner._make_target", return_value=fake_target):
            rc = main([
                "--target", str(tmp_path),
                "--conformance-root", str(conf_dir),
                "--category", "identity-verification",
            ])
        assert rc == 0
        # Only 1 fixture should have run
        assert len(fake_target.calls) == 1
