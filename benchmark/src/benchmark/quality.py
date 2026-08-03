"""Structural quality signals for a generated answer — computed the
same way regardless of mode, so Direct/ARCF/ARCF Local are directly
comparable. See domain/models.py:QualityMetrics for why
compilation_success/test_success are left as None here rather than
faked.
"""

import re

from benchmark.domain.models import QualityMetrics

_MARKDOWN_HEADER_RE = re.compile(r"^### (\S+)", re.MULTILINE)
_DIFF_GIT_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.MULTILINE)
_UNIFIED_DIFF_RE = re.compile(r"^(?:---|\+\+\+) (?:[ab]/)?(\S+)", re.MULTILINE)
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


def build_quality_metrics(generated_output: str) -> QualityMetrics:
    return QualityMetrics(
        answer_length=len(generated_output),
        modified_files=extract_modified_files(generated_output),
    )
