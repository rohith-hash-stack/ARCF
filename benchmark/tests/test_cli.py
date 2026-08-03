from benchmark.cli import _parse_args
from benchmark.domain.models import BenchmarkMode


def test_default_modes_are_all_three() -> None:
    args = _parse_args(["compare", "--repo", "/repo", "--task", "fix bug"])
    assert set(args.modes) == {"direct", "arcf", "arcf_local"}


def test_modes_can_be_restricted() -> None:
    args = _parse_args(
        ["compare", "--repo", "/repo", "--task", "fix bug", "--modes", "direct", "arcf"]
    )
    assert args.modes == ["direct", "arcf"]


def test_mode_choices_match_benchmark_mode_enum() -> None:
    args = _parse_args(["compare", "--repo", "/repo", "--task", "x", "--modes", "arcf_local"])
    assert args.modes == [BenchmarkMode.ARCF_LOCAL.value]


def test_suite_run_requires_mode_choice_from_hyphenated_names() -> None:
    args = _parse_args(["suite", "run", "--suite", "pilot", "--mode", "arcf-remote"])
    assert args.suite == "pilot"
    assert args.mode == "arcf-remote"


def test_suite_report_parses() -> None:
    args = _parse_args(["suite", "report", "--suite", "pilot"])
    assert args.suite == "pilot"


def test_suite_setup_parses() -> None:
    args = _parse_args(["suite", "setup", "--repo", "todomvc", "--yes"])
    assert args.repo == "todomvc"
    assert args.yes is True
