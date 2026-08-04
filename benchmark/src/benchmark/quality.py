"""Structural quality signals for a generated answer — computed the
same way regardless of mode, so Direct/ARCF/ARCF Local are directly
comparable. See domain/models.py:QualityMetrics for why
compilation_success/test_success are left as None here rather than
faked.

count_changed_lines has the same honest-gap shape: it counts +/- lines
in unified-diff-formatted output (a format runners/base.py's prompt
template explicitly permits for ad-hoc Direct/ARCF runs), but returns
0 for the suite's own "### path" + full-file-block format (suite/
patcher.py's FORMAT_ADDENDUM) — a full replacement file isn't a diff,
so counting changed lines there would require diffing against the
original file content on disk, which this text-only signal never sees.
That gap is tracked in arcf/docs/ARCF_V2.3_VALIDATION_READINESS_REPORT.md
as a known limitation, not silently patched over with a guess.
"""

import re

from benchmark.domain.models import QualityMetrics

_MARKDOWN_HEADER_RE = re.compile(r"^### (\S+)", re.MULTILINE)
_DIFF_GIT_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.MULTILINE)
_UNIFIED_DIFF_RE = re.compile(r"^(?:---|\+\+\+) (?:[ab]/)?(\S+)", re.MULTILINE)
_DIFF_CHANGED_LINE_RE = re.compile(r"^[+-](?![+-]{2})", re.MULTILINE)
_IGNORED_DIFF_PATHS = {"/dev/null"}


def extract_modified_files(text: str) -> list[str]:
    """Parses file paths out of the two header styles the benchmark's
    own prompt template (runners/base.py) asks the LLM to use: markdown
    "### path" sections, or a unified diff / `git diff` header. Order
    of first appearance is preserved; duplicates are dropped.
    """
    seen: dict[str, None] = {}

    for match in _DIFF_GIT_RE.finditer(text):
        seen.setdefault(match.group(1), None)
        seen.setdefault(match.group(2), None)

    for match in _UNIFIED_DIFF_RE.finditer(text):
        path = match.group(1)
        if path not in _IGNORED_DIFF_PATHS:
            seen.setdefault(path, None)

    for match in _MARKDOWN_HEADER_RE.finditer(text):
        seen.setdefault(match.group(1), None)

    return list(seen.keys())


def count_changed_lines(text: str) -> int:
    """Counts +/- lines in unified-diff-formatted text, excluding the
    `+++`/`---` file-header lines. Returns 0 when text has no unified-
    diff hunks at all (e.g. the suite's full-file-block format) — see
    this module's docstring for why that's an honest gap, not a bug.
    """
    if not _UNIFIED_DIFF_RE.search(text) and not _DIFF_GIT_RE.search(text):
        return 0
    return len(_DIFF_CHANGED_LINE_RE.findall(text))


def build_quality_metrics(generated_output: str) -> QualityMetrics:
    return QualityMetrics(
        answer_length=len(generated_output),
        modified_files=extract_modified_files(generated_output),
        lines_changed=count_changed_lines(generated_output),
    )
