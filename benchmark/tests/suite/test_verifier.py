import sys
from pathlib import Path

from benchmark.suite.verifier import run_verification


def test_passing_command(tmp_path: Path) -> None:
    result = run_verification(tmp_path, f'"{sys.executable}" -c "exit(0)"', ".", 10)
    assert result.passed is True


def test_failing_command(tmp_path: Path) -> None:
    result = run_verification(tmp_path, f'"{sys.executable}" -c "exit(1)"', ".", 10)
    assert result.passed is False


def test_captures_output(tmp_path: Path) -> None:
    result = run_verification(
        tmp_path, f'"{sys.executable}" -c "print(123); exit(1)"', ".", 10
    )
    assert "123" in result.output_tail
    assert result.passed is False


def test_timeout_is_treated_as_failure(tmp_path: Path) -> None:
    result = run_verification(
        tmp_path, f'"{sys.executable}" -c "import time; time.sleep(5)"', ".", 1
    )
    assert result.passed is False
    assert "TIMED OUT" in result.output_tail


def test_unknown_command_fails_gracefully(tmp_path: Path) -> None:
    result = run_verification(tmp_path, "this-command-does-not-exist-anywhere", ".", 5)
    assert result.passed is False
