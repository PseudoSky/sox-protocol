# SPDX-License-Identifier: Apache-2.0
"""Tests for fixture loading: YAML parsing, schema validation, pending flag."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from conformance_runner import Fixture, load_fixture, load_fixtures


class TestLoadFixture:
    """Tests for load_fixture()."""

    def test_loads_minimal_valid_fixture(self, minimal_fixture_file: Path) -> None:
        fixture = load_fixture(minimal_fixture_file)
        assert fixture.name == "minimal-test"
        assert fixture.spec_ref == "spec/protocol.md"
        assert fixture.pending is False
        assert len(fixture.sequence) == 1
        assert fixture.sequence[0]["id"] == "step-1"

    def test_pending_flag_defaults_false(self, minimal_fixture_file: Path) -> None:
        fixture = load_fixture(minimal_fixture_file)
        assert fixture.pending is False

    def test_pending_flag_true(self, pending_fixture_file: Path) -> None:
        fixture = load_fixture(pending_fixture_file)
        assert fixture.pending is True

    def test_missing_required_keys_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("name: no-sequence\nspec_ref: x\ndescription: y\n")
        with pytest.raises(ValueError, match="missing required keys"):
            load_fixture(bad)

    def test_sequence_not_list_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad2.yaml"
        bad.write_text(
            "name: x\nspec_ref: x\ndescription: y\nsequence: not-a-list\n"
        )
        with pytest.raises(ValueError, match="'sequence' must be a list"):
            load_fixture(bad)

    def test_not_a_mapping_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad3.yaml"
        bad.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_fixture(bad)

    def test_agents_parsed(self, minimal_fixture_file: Path) -> None:
        fixture = load_fixture(minimal_fixture_file)
        assert len(fixture.agents) == 1
        assert fixture.agents[0]["id"] == "agent-a"

    def test_setup_empty_by_default(self, tmp_path: Path) -> None:
        f = tmp_path / "f.yaml"
        f.write_text(
            textwrap.dedent("""\
                name: x
                spec_ref: x
                description: y
                sequence:
                  - id: s1
                    as_agent: agent-a
                    operation: recv
                    input: {}
            """)
        )
        fixture = load_fixture(f)
        assert fixture.setup == []
        assert fixture.assertions == []
        assert fixture.teardown == []

    def test_raw_preserved(self, minimal_fixture_file: Path) -> None:
        fixture = load_fixture(minimal_fixture_file)
        assert "name" in fixture.raw

    def test_description_parsed(self, minimal_fixture_file: Path) -> None:
        fixture = load_fixture(minimal_fixture_file)
        assert "Minimal" in fixture.description


class TestLoadFixtures:
    """Tests for load_fixtures()."""

    def test_loads_multiple_fixtures(
        self, tmp_fixture_dir: Path, minimal_fixture_yaml: str
    ) -> None:
        for i in range(3):
            sub = tmp_fixture_dir / f"cat{i}"
            sub.mkdir()
            (sub / f"fix{i}.yaml").write_text(minimal_fixture_yaml)
        fixtures = load_fixtures(tmp_fixture_dir)
        assert len(fixtures) == 3

    def test_category_filter(
        self, tmp_fixture_dir: Path, minimal_fixture_yaml: str
    ) -> None:
        cat_a = tmp_fixture_dir / "identity-verification"
        cat_b = tmp_fixture_dir / "send-recv-basic"
        cat_a.mkdir()
        cat_b.mkdir()
        (cat_a / "fix.yaml").write_text(minimal_fixture_yaml)
        (cat_b / "fix.yaml").write_text(minimal_fixture_yaml)

        fixtures = load_fixtures(tmp_fixture_dir, category="identity-verification")
        assert len(fixtures) == 1
        assert "identity-verification" in str(fixtures[0].path)

    def test_multi_category_filter(
        self, tmp_fixture_dir: Path, minimal_fixture_yaml: str
    ) -> None:
        for cat in ("identity-verification", "send-recv-basic", "threading"):
            sub = tmp_fixture_dir / cat
            sub.mkdir()
            (sub / "fix.yaml").write_text(minimal_fixture_yaml)

        fixtures = load_fixtures(
            tmp_fixture_dir, category="identity-verification,send-recv-basic"
        )
        assert len(fixtures) == 2

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        fixtures = load_fixtures(empty)
        assert fixtures == []

    def test_bad_fixture_propagates_error(
        self, tmp_fixture_dir: Path
    ) -> None:
        bad = tmp_fixture_dir / "bad.yaml"
        bad.write_text("- not: a mapping\n")
        with pytest.raises(ValueError, match="Failed to load fixture"):
            load_fixtures(tmp_fixture_dir)

    def test_sorted_by_path(
        self, tmp_fixture_dir: Path, minimal_fixture_yaml: str
    ) -> None:
        sub = tmp_fixture_dir / "cat"
        sub.mkdir()
        (sub / "02-fix.yaml").write_text(minimal_fixture_yaml)
        (sub / "01-fix.yaml").write_text(minimal_fixture_yaml)
        fixtures = load_fixtures(tmp_fixture_dir)
        paths = [f.path.name for f in fixtures]
        assert paths == sorted(paths)


class TestRealConformanceFixtures:
    """Smoke-test that all real spec/conformance fixtures parse without error."""

    def test_all_real_fixtures_parse(self) -> None:
        from pathlib import Path as P
        repo_root = P(__file__).resolve().parents[2]
        conformance_root = repo_root / "spec" / "conformance"
        if not conformance_root.exists():
            pytest.skip("spec/conformance not found")
        fixtures = load_fixtures(conformance_root)
        assert len(fixtures) > 0
        for f in fixtures:
            assert f.name
            assert f.spec_ref
