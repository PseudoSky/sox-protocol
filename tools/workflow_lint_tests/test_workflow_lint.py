"""Tests for tools/workflow_lint.py.

Each test builds a minimal in-memory ``.workflow/`` corpus inside a tmp
directory, runs the linter, and asserts the expected error/warning shape.
Goal: 100% line coverage of workflow_lint.py.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from textwrap import dedent

import pytest

import workflow_lint as wl

# ---------------------------------------------------------------------------
# Corpus helpers
# ---------------------------------------------------------------------------


def _phase(
    phase_id: str,
    *,
    title: str = "Sample phase",
    agent: str = "python-pro",
    profile: str = "code-python",
    estimated_effort: str = "1h",
    prereqs: list[str] | None = None,
    unblocks: list[str] | None = None,
    parallelizable_with: list[str] | None = None,
    writes: list[str] | None = None,
    reads: list[str] | None = None,
    context_size: str = "small",
    inputs_section: str = "",
) -> str:
    prereqs = prereqs if prereqs is not None else []
    unblocks = unblocks if unblocks is not None else []
    parallelizable_with = parallelizable_with if parallelizable_with is not None else []
    writes = writes if writes is not None else ["packages/python/src/foo/**"]
    reads = reads if reads is not None else ["spec/foo.md"]

    def _list(xs: list[str]) -> str:
        return "[" + ", ".join(xs) + "]"

    header = dedent(
        f"""\
        ---
        phase_id: {phase_id}
        title: {title}
        agent: {agent}
        profile: {profile}
        estimated_effort: {estimated_effort}
        prereqs: {_list(prereqs)}
        unblocks: {_list(unblocks)}
        parallelizable_with: {_list(parallelizable_with)}
        writes: {_list(writes)}
        reads: {_list(reads)}
        context_size: {context_size}
        ---

        # {title}
        """
    )
    return header + "\n" + inputs_section + "\n"


def _state_md(rows: list[tuple[str, str, str]], next_action: str | None) -> str:
    lines = [
        "---",
        "engagement: test",
        "---",
        "",
        "# State",
        "",
        "| Phase | Title | Status |",
        "|-------|-------|--------|",
    ]
    for pid, title, status in rows:
        lines.append(f"| {pid} | {title} | `{status}` |")
    lines.append("")
    if next_action:
        lines.append(f"Currently next action: `{next_action}` is `READY`.")
    return "\n".join(lines) + "\n"


def _make_engagement(
    plans_dir: Path,
    slug: str,
    phases: dict[str, str],
    state_rows: list[tuple[str, str, str]] | None = None,
    next_action: str | None = None,
    write_state: bool = True,
) -> Path:
    eng = plans_dir / slug
    (eng / "phases").mkdir(parents=True, exist_ok=True)
    for pid, content in phases.items():
        (eng / "phases" / f"{pid}.md").write_text(content)
    if write_state:
        rows = state_rows if state_rows is not None else [
            (pid, "Sample phase", "READY") for pid in phases
        ]
        (eng / "STATE.md").write_text(_state_md(rows, next_action))
    return eng


def _clean_corpus(tmp_path: Path) -> Path:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {
        "01-spec": _phase(
            "01-spec",
            profile="spec",
            unblocks=["02-implement"],
            writes=["spec/foo.md"],
        ),
        "02-implement": _phase(
            "02-implement",
            profile="code-python",
            prereqs=["01-spec"],
            writes=["packages/python/src/foo/**"],
        ),
    }
    _make_engagement(
        plans,
        "sample",
        phases,
        state_rows=[
            ("01-spec", "Spec", "DONE"),
            ("02-implement", "Implement", "READY"),
        ],
        next_action="02-implement",
    )
    return workflow


# ---------------------------------------------------------------------------
# Tests (≥6, covering every branch)
# ---------------------------------------------------------------------------


def test_clean_corpus_passes(tmp_path: Path) -> None:
    workflow = _clean_corpus(tmp_path)
    result = wl.lint(workflow)
    assert result.errors == [], [i.as_dict() for i in result.errors]
    assert result.checks_run > 0


def test_missing_prereqs_phase_fails(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {
        "01-impl": _phase(
            "01-impl",
            prereqs=["99-ghost"],  # dangling
        ),
    }
    _make_engagement(plans, "eng", phases, next_action="01-impl")
    result = wl.lint(workflow)
    checks = {e.check for e in result.errors}
    assert "dangling_prereqs" in checks


def test_cyclic_dependency_fails(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {
        "01-a": _phase("01-a", prereqs=["02-b"]),
        "02-b": _phase("02-b", prereqs=["01-a"]),
    }
    _make_engagement(
        plans,
        "cyclic",
        phases,
        state_rows=[("01-a", "A", "READY"), ("02-b", "B", "READY")],
        next_action="01-a",
    )
    result = wl.lint(workflow)
    assert any(e.check == "cyclic_dependency" for e in result.errors)


def test_bad_profile_fails(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {
        "01-x": _phase("01-x", profile="not-a-real-profile"),
    }
    _make_engagement(plans, "badprof", phases, next_action="01-x")
    result = wl.lint(workflow)
    assert any(e.check == "invalid_profile" for e in result.errors)


def test_frontmatter_schema_mismatch_fails(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    # Missing required keys, mismatched phase_id, bad reads/writes types.
    bad_body = dedent(
        """\
        ---
        phase_id: 01-mismatch
        title: Bad
        ---

        # Body
        """
    )
    eng = plans / "schema"
    (eng / "phases").mkdir(parents=True)
    (eng / "phases" / "01-different.md").write_text(bad_body)
    (eng / "STATE.md").write_text(
        _state_md([("01-different", "Bad", "READY")], "01-different")
    )
    result = wl.lint(workflow)
    checks = {e.check for e in result.errors}
    assert "frontmatter_schema" in checks
    assert "phase_id_filename_mismatch" in checks


def test_no_frontmatter_fails(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    eng = plans / "nofm"
    (eng / "phases").mkdir(parents=True)
    (eng / "phases" / "01-bare.md").write_text("# Just a heading, no frontmatter\n")
    (eng / "STATE.md").write_text(
        _state_md([("01-bare", "Bare", "READY")], "01-bare")
    )
    result = wl.lint(workflow)
    assert any(e.check == "frontmatter_missing" for e in result.errors)


def test_state_orphan_and_missing_rows(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {"01-real": _phase("01-real")}
    _make_engagement(
        plans,
        "drift",
        phases,
        state_rows=[
            ("99-ghost", "Ghost", "READY"),  # orphan: no file
        ],
        next_action="99-ghost",
    )
    result = wl.lint(workflow)
    checks = {e.check for e in result.errors}
    assert "state_orphan" in checks
    assert "state_missing" in checks


def test_state_missing_file(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {"01-x": _phase("01-x")}
    _make_engagement(plans, "nostate", phases, write_state=False)
    result = wl.lint(workflow)
    assert any(e.check == "state_missing_file" for e in result.errors)


def test_next_action_not_ready(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {"01-x": _phase("01-x")}
    _make_engagement(
        plans,
        "stale",
        phases,
        state_rows=[("01-x", "X", "DONE")],
        next_action="01-x",
    )
    result = wl.lint(workflow)
    assert any(e.check == "next_action_not_ready" for e in result.errors)


def test_unknown_agent_warns(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {
        "01-x": _phase("01-x", agent="totally-made-up-agent"),
    }
    _make_engagement(plans, "unkagent", phases, next_action="01-x")
    result = wl.lint(workflow)
    assert any(w.check == "unknown_agent" for w in result.warnings)


def test_invalid_writes_type_fails(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    body = dedent(
        """\
        ---
        phase_id: 01-bad
        title: Bad writes
        agent: python-pro
        profile: code-python
        estimated_effort: 1h
        prereqs: []
        unblocks: []
        parallelizable_with: []
        writes: not-a-list
        reads: []
        context_size: small
        ---
        """
    )
    eng = plans / "badwrites"
    (eng / "phases").mkdir(parents=True)
    (eng / "phases" / "01-bad.md").write_text(body)
    (eng / "STATE.md").write_text(_state_md([("01-bad", "Bad", "READY")], "01-bad"))
    result = wl.lint(workflow)
    assert any(e.check == "invalid_writes" for e in result.errors)


def test_empty_writes_warns(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {
        "01-x": _phase(
            "01-x",
            profile="code-python",
            writes=[],
        ),
    }
    _make_engagement(plans, "emptyw", phases, next_action="01-x")
    result = wl.lint(workflow)
    assert any(w.check == "empty_writes" for w in result.warnings)


def test_planning_no_consumer_warns(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {
        "01-plan": _phase(
            "01-plan",
            profile="planning",
            unblocks=[],
        ),
    }
    _make_engagement(plans, "lonelyplan", phases, next_action="01-plan")
    result = wl.lint(workflow)
    assert any(w.check == "planning_no_consumer" for w in result.warnings)


def test_inputs_path_missing_warns(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    inputs = "## Inputs\n\n- `/this/path/definitely/does/not/exist.md`\n\n## Body\n"
    phases = {"01-x": _phase("01-x", inputs_section=inputs)}
    _make_engagement(plans, "inputs", phases, next_action="01-x")
    result = wl.lint(workflow)
    assert any(w.check == "input_path_missing" for w in result.warnings)


def test_plans_dir_missing(tmp_path: Path) -> None:
    workflow = tmp_path / "nope"
    workflow.mkdir()
    result = wl.lint(workflow)
    assert any(e.check == "plans_dir_missing" for e in result.errors)


def test_engagement_filter(tmp_path: Path) -> None:
    workflow = _clean_corpus(tmp_path)
    # Add a second broken engagement
    plans = workflow / "plans"
    bad_phases = {"01-cycle": _phase("01-cycle", prereqs=["01-cycle"])}
    _make_engagement(plans, "broken", bad_phases, next_action="01-cycle")
    # Filter to clean engagement only — should pass.
    result = wl.lint(workflow, engagement_filter="sample")
    assert not result.errors
    # Filter to broken — should fail.
    result2 = wl.lint(workflow, engagement_filter="broken")
    assert result2.errors


def test_json_output_validates_as_json(tmp_path: Path, monkeypatch) -> None:
    workflow = _clean_corpus(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["workflow_lint.py", str(workflow), "--json"],
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = wl.main()
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    for key in ("checks_run", "elapsed_ms", "error_count", "warning_count", "issues"):
        assert key in parsed


def test_main_human_output_clean(tmp_path: Path, monkeypatch, capsys) -> None:
    workflow = _clean_corpus(tmp_path)
    monkeypatch.setattr(sys, "argv", ["workflow_lint.py", str(workflow)])
    rc = wl.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK" in captured.out


def test_main_human_output_with_errors(tmp_path: Path, monkeypatch, capsys) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {"01-x": _phase("01-x", profile="invalid-profile")}
    _make_engagement(plans, "eng", phases, next_action="01-x")
    monkeypatch.setattr(sys, "argv", ["workflow_lint.py", str(workflow)])
    rc = wl.main()
    captured = capsys.readouterr()
    assert rc == 1
    assert "ERROR" in captured.out


def test_main_strict_promotes_warnings(tmp_path: Path, monkeypatch) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {"01-x": _phase("01-x", agent="totally-made-up-agent")}
    _make_engagement(plans, "eng", phases, next_action="01-x")
    monkeypatch.setattr(
        sys,
        "argv",
        ["workflow_lint.py", str(workflow), "--strict"],
    )
    rc = wl.main()
    assert rc == 1


# --- frontmatter parser unit tests (cover edge cases) ----------------------


def test_parse_frontmatter_no_delimiter() -> None:
    assert wl.parse_frontmatter("no frontmatter here\n") is None


def test_parse_frontmatter_unterminated() -> None:
    assert wl.parse_frontmatter("---\nkey: value\nno close\n") is None


def test_parse_frontmatter_empty_lines_and_comments() -> None:
    text = "---\n# comment line\n\nkey: value\n---\nbody\n"
    fm = wl.parse_frontmatter(text)
    assert fm == {"key": "value"}


def test_parse_frontmatter_block_scalar() -> None:
    text = "---\nblock: |\n  line1\n  line2\nkey: value\n---\n"
    fm = wl.parse_frontmatter(text)
    assert fm["block"] == "line1\nline2"
    assert fm["key"] == "value"


def test_parse_frontmatter_inline_list_quoted() -> None:
    text = "---\nitems: [\"a b\", 'c d', plain]\n---\n"
    fm = wl.parse_frontmatter(text)
    assert fm["items"] == ["a b", "c d", "plain"]


def test_parse_frontmatter_empty_list() -> None:
    text = "---\nitems: []\n---\n"
    fm = wl.parse_frontmatter(text)
    assert fm["items"] == []


def test_parse_frontmatter_empty_block_scalar() -> None:
    text = "---\nblock: |\nkey: value\n---\n"
    fm = wl.parse_frontmatter(text)
    assert fm["block"] == ""


def test_parse_frontmatter_skips_unmatched_lines() -> None:
    text = "---\n: bogus line with no key\nkey: value\n---\n"
    fm = wl.parse_frontmatter(text)
    assert fm == {"key": "value"}


def test_has_cycle_no_cycle() -> None:
    g = {"a": ["b"], "b": ["c"], "c": []}
    assert wl.has_cycle(g) is None


def test_has_cycle_dangling_ignored() -> None:
    g = {"a": ["missing"], "b": []}
    assert wl.has_cycle(g) is None


def test_has_cycle_self_loop() -> None:
    g = {"a": ["a"]}
    assert wl.has_cycle(g) is not None


def test_parse_state_md_alternate_next_action(tmp_path: Path) -> None:
    state = tmp_path / "STATE.md"
    state.write_text(
        "# State\n\n"
        "| Phase | Title | Status |\n"
        "|-------|-------|--------|\n"
        "| 01-foo | Foo | `READY` |\n\n"
        "Currently next action:\n\n"
        "  `01-foo`: do the thing.\n"
    )
    parsed = wl.parse_state_md(state)
    assert parsed["next_action"] == "01-foo"
    assert parsed["phase_rows"][0]["phase_id"] == "01-foo"


def test_lint_result_helpers() -> None:
    r = wl.LintResult()
    r.error("e", "p", "c", "m")
    r.warning("e", "p", "c", "m")
    assert len(r.errors) == 1
    assert len(r.warnings) == 1
    d = r.as_dict()
    assert d["error_count"] == 1
    assert d["warning_count"] == 1


def test_state_md_separator_and_blank_rows(tmp_path: Path) -> None:
    state = tmp_path / "STATE.md"
    state.write_text(
        "# State\n"
        "|     |     |\n"  # blank-cell row → no cells, hits `continue`
        "| Phase | Title | Status |\n"
        "|-------|-------|--------|\n"
        "| 01-x | X | `READY` |\n"
    )
    parsed = wl.parse_state_md(state)
    assert parsed["phase_rows"][0]["phase_id"] == "01-x"


def test_phase_dir_missing_skips_glob(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    eng = plans / "no-phases-dir"
    eng.mkdir()
    (eng / "STATE.md").write_text(_state_md([], None))
    result = wl.lint(workflow)
    # No frontmatter errors because no phase files; STATE.md exists but empty.
    assert not any(e.check.startswith("frontmatter") for e in result.errors)


def test_feedback_files_are_skipped(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {"01-x": _phase("01-x")}
    eng = _make_engagement(plans, "fb", phases, next_action="01-x")
    # Drop a feedback file that should be ignored
    (eng / "phases" / "01-x.feedback-1.md").write_text("# noise\n")
    result = wl.lint(workflow)
    assert not result.errors


def test_invalid_agent_empty_string(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {"01-x": _phase("01-x", agent="")}
    _make_engagement(plans, "ea", phases, next_action="01-x")
    result = wl.lint(workflow)
    assert any(e.check == "invalid_agent" for e in result.errors)


def test_non_string_list_items(tmp_path: Path) -> None:
    """Force prereqs to contain a non-string by writing raw YAML and a non-list ref.

    Hits the `if not isinstance(ref, str): continue` branch and the
    `if not isinstance(refs, list): continue` branch, plus the
    `invalid_writes_item` branch.
    """
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    body = dedent(
        """\
        ---
        phase_id: 01-x
        title: T
        agent: python-pro
        profile: code-python
        estimated_effort: 1h
        prereqs: scalar-not-list
        unblocks: []
        parallelizable_with: []
        writes: [packages/python/src/foo/**]
        reads: [spec/foo.md]
        context_size: small
        ---
        """
    )
    eng = plans / "weird"
    (eng / "phases").mkdir(parents=True)
    (eng / "phases" / "01-x.md").write_text(body)
    (eng / "STATE.md").write_text(_state_md([("01-x", "T", "READY")], "01-x"))
    result = wl.lint(workflow)
    # No crash — prereqs as scalar is silently ignored.
    assert not any(e.check == "dangling_prereqs" for e in result.errors)


def test_non_string_writes_item(tmp_path: Path, monkeypatch) -> None:
    """Force a non-string entry inside the writes list.

    The simple YAML parser treats every list element as a string, so we
    monkey-patch parse_frontmatter for one call to inject the bad type
    and exercise the `invalid_writes_item` branch.
    """
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    phases = {"01-x": _phase("01-x")}
    _make_engagement(plans, "nsi", phases, next_action="01-x")

    real = wl.parse_frontmatter

    def fake(text: str):
        fm = real(text)
        if fm and fm.get("phase_id") == "01-x":
            fm["writes"] = [123]  # non-string
            fm["prereqs"] = [42]  # non-string ref
        return fm

    monkeypatch.setattr(wl, "parse_frontmatter", fake)
    result = wl.lint(workflow)
    assert any(e.check == "invalid_writes_item" for e in result.errors)


def test_skips_readme_named_dir_in_plans(tmp_path: Path) -> None:
    """Hit the `engagement_dir.name == 'README.md'` skip branch."""
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    # An actual directory literally named 'README.md' (rare but the linter handles it).
    (plans / "README.md").mkdir()
    phases = {"01-x": _phase("01-x")}
    _make_engagement(plans, "real", phases, next_action="01-x")
    result = wl.lint(workflow)
    assert not result.errors


def test_skips_readme_and_non_dirs_in_plans(tmp_path: Path) -> None:
    workflow = tmp_path / ".workflow"
    plans = workflow / "plans"
    plans.mkdir(parents=True)
    # Drop a README.md and a regular file at plans/ level — both must be ignored.
    (plans / "README.md").write_text("# plans\n")
    (plans / "stray.txt").write_text("noise\n")
    phases = {"01-x": _phase("01-x")}
    _make_engagement(plans, "real", phases, next_action="01-x")
    result = wl.lint(workflow)
    assert not result.errors


def test_invoke_as_module_subprocess() -> None:
    """Smoke test: ``python -m`` style invocation via subprocess to cover the
    ``if __name__ == '__main__'`` guard.
    """
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tools" / "workflow_lint.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "Validate" in proc.stdout
