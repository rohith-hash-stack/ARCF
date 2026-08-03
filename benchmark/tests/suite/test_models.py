import pytest
from pydantic import ValidationError

from benchmark.suite.models import BugFixture, SuiteTask, TaskCategory


def test_suite_task_defaults() -> None:
    task = SuiteTask(
        id="t1", category=TaskCategory.REPOSITORY_UNDERSTANDING, subcategory="x",
        repo_key="arcf", task_prompt="explain something",
    )
    assert task.expected_grounding == []
    assert task.expected_path_prefixes == []
    assert task.protected_path_prefixes == []
    assert task.bug_fixture is None
    assert task.verify_command is None
    assert task.verify_cwd == "."
    assert task.verify_timeout_seconds == 60


def test_suite_task_is_frozen() -> None:
    task = SuiteTask(
        id="t1", category=TaskCategory.BUG_FIXING, subcategory="x",
        repo_key="arcf", task_prompt="fix it",
    )
    with pytest.raises(ValidationError):
        task.id = "other"


def test_bug_fixture_requires_all_fields() -> None:
    with pytest.raises(ValidationError):
        BugFixture(file_path="x.py", find="a")  # type: ignore[call-arg]


def test_task_category_values() -> None:
    assert TaskCategory.REPOSITORY_UNDERSTANDING.value == "repository_understanding"
    assert TaskCategory.BUG_FIXING.value == "bug_fixing"
    assert TaskCategory.REFACTORING.value == "refactoring"
    assert TaskCategory.TEST_GENERATION.value == "test_generation"
