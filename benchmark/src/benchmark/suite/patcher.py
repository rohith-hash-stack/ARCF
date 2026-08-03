"""Applies a mode's generated_output to a scratch repo copy.

Unified diffs are notoriously easy for an LLM to get subtly wrong
(hunk offsets, context lines) in ways that make `git apply` fail for
reasons that have nothing to do with whether the underlying fix is
right — that would make tests_passed measure diff-formatting luck
instead of correctness. So the suite runner asks every mode, via
FORMAT_ADDENDUM appended to the task prompt (task-agnostic, identical
across all three modes and all tasks — not per-task tuning), to
respond with ONLY "### path" headers followed by a fenced code block of
the COMPLETE resulting file content. That is one of the two formats
runners/base.py's compile_prompt already told the model was acceptable
("a unified diff or complete file contents") — this just makes it the
only one, for measurement reliability.

protected_path_prefixes is a hard write-time guard, not a scoring rule:
even if a model's output includes a "### tests/test_auth.py" block, it
is never written — a model cannot pass Bug Fixing verification by
rewriting the oracle test instead of fixing the source.
"""

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

FORMAT_ADDENDUM = """

IMPORTANT — output format (required, no exceptions):
Respond with ONLY one or more sections in exactly this shape, for every file you create or \
modify. Do not use a unified diff. Do not include any text outside these sections.

### path/to/file.ext
```
<the COMPLETE resulting content of the file, not a diff or excerpt>
```
"""

_FILE_BLOCK_RE = re.compile(
    r"^### (?P<path>\S+)\r?\n```[^\n]*\r?\n(?P<content>.*?)\r?\n```", re.MULTILINE | re.DOTALL
)


class FileBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    content: str


class PatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    applied: bool
    written_paths: list[str]
    skipped_protected_paths: list[str]


def parse_file_blocks(text: str) -> list[FileBlock]:
    return [
        FileBlock(path=m.group("path"), content=m.group("content"))
        for m in _FILE_BLOCK_RE.finditer(text)
    ]


def apply_output_to_repo(
    scratch_repo_root: Path,
    generated_output: str,
    protected_path_prefixes: list[str],
) -> PatchResult:
    blocks = parse_file_blocks(generated_output)
    written: list[str] = []
    skipped: list[str] = []

    for block in blocks:
        normalized = block.path.replace("\\", "/").lstrip("/")
        if any(normalized.startswith(prefix) for prefix in protected_path_prefixes):
            skipped.append(normalized)
            continue

        target = scratch_repo_root / normalized
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(block.content + "\n", encoding="utf-8")
        written.append(normalized)

    return PatchResult(
        applied=bool(written), written_paths=written, skipped_protected_paths=skipped
    )
