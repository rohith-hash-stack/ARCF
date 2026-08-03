"""Applies a BugFixture to a scratch repo copy before the pipeline
runs, for Bug Fixing category tasks. find/replace is an exact substring
match — a fixture that doesn't match the current source is a fixture
bug (arcf/todomvc changed underneath it), and that should fail loudly
at fixture-application time, not silently produce a task with nothing
actually broken.
"""

from pathlib import Path

from benchmark.suite.models import BugFixture


class FixtureApplyError(Exception):
    pass


def apply_bug_fixture(scratch_repo_root: Path, fixture: BugFixture) -> None:
    target = scratch_repo_root / fixture.file_path
    if not target.is_file():
        raise FixtureApplyError(f"Fixture target {fixture.file_path} does not exist")

    original = target.read_text(encoding="utf-8")
    occurrences = original.count(fixture.find)
    if occurrences != 1:
        raise FixtureApplyError(
            f"Fixture find-text expected exactly 1 match in {fixture.file_path}, "
            f"found {occurrences} — fixture is stale or ambiguous"
        )

    target.write_text(original.replace(fixture.find, fixture.replace), encoding="utf-8")
