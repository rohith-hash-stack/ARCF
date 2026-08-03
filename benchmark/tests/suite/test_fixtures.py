from pathlib import Path

import pytest

from benchmark.suite.fixtures import FixtureApplyError, apply_bug_fixture
from benchmark.suite.models import BugFixture


def test_applies_exact_match(tmp_path: Path) -> None:
    target = tmp_path / "mod.py"
    target.write_text("def f():\n    return 1\n")
    apply_bug_fixture(tmp_path, BugFixture(file_path="mod.py", find="return 1", replace="return 2"))
    assert target.read_text() == "def f():\n    return 2\n"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FixtureApplyError, match="does not exist"):
        apply_bug_fixture(
            tmp_path, BugFixture(file_path="nope.py", find="x", replace="y")
        )


def test_zero_matches_raises(tmp_path: Path) -> None:
    target = tmp_path / "mod.py"
    target.write_text("def f():\n    return 1\n")
    with pytest.raises(FixtureApplyError, match="found 0"):
        apply_bug_fixture(
            tmp_path, BugFixture(file_path="mod.py", find="not present", replace="x")
        )


def test_ambiguous_match_raises(tmp_path: Path) -> None:
    target = tmp_path / "mod.py"
    target.write_text("x = 1\nx = 1\n")
    with pytest.raises(FixtureApplyError, match="found 2"):
        apply_bug_fixture(tmp_path, BugFixture(file_path="mod.py", find="x = 1", replace="x = 2"))
