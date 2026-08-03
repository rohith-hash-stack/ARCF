"""Runs a task's verify_command as a subprocess inside a scratch repo,
with a hard timeout — this is the actual execution oracle behind
tests_passed. Exit code 0 is the only thing that counts as passing;
non-zero (including timeout) is a failure, never silently treated as
"inconclusive" — an inconclusive verify command would make
tests_passed meaningless.

verify_command is split with shlex's POSIX mode (the default): any
Windows path substituted into the command (e.g. the {python}
placeholder SuiteRunner fills in) MUST be double-quoted in the task
definition — POSIX-mode shlex only treats backslashes literally inside
quotes, and mangles them outside quotes.
"""

import os
import shlex
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    passed: bool
    output_tail: str


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_verification(
    scratch_repo_root: Path,
    verify_command: str,
    verify_cwd: str,
    timeout_seconds: int,
    extra_env: dict[str, str] | None = None,
) -> VerificationResult:
    cwd = scratch_repo_root / verify_cwd
    env = {**os.environ, **(extra_env or {})}

    try:
        result = subprocess.run(
            shlex.split(verify_command),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return VerificationResult(passed=result.returncode == 0, output_tail=output[-2000:])
    except subprocess.TimeoutExpired as exc:
        partial = _decode(exc.stdout) + _decode(exc.stderr)
        return VerificationResult(
            passed=False, output_tail=f"TIMED OUT after {timeout_seconds}s\n{partial[-1800:]}"
        )
    except OSError as exc:
        return VerificationResult(passed=False, output_tail=f"Failed to run verify command: {exc}")
