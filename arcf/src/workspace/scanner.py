"""Repository Scanner (Phase 4 deliverable).

Bounded, deterministic file-tree walk producing the raw file inventory
that language/framework/structure detection consume. Caps at max_files
so a pathological monorepo can't hang a request; sets truncated=True
when the cap is hit so callers know the inventory is partial rather
than silently wrong. followlinks=False so a symlinked directory can't
walk the scan outside workspace_root.
"""

import os
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        ".next",
        "target",
        "vendor",
    }
)

DEFAULT_MAX_FILES = 20_000


@dataclass(frozen=True)
class ScannedFile:
    relative_path: str
    extension: str
    size_bytes: int


@dataclass(frozen=True)
class ScanResult:
    files: list[ScannedFile]
    truncated: bool


class RepositoryScanner:
    def __init__(self, max_files: int = DEFAULT_MAX_FILES) -> None:
        self._max_files = max_files

    def scan(self, workspace_root: Path) -> ScanResult:
        files: list[ScannedFile] = []
        truncated = False

        for dirpath, dirnames, filenames in os.walk(workspace_root, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRECTORY_NAMES)

            for filename in sorted(filenames):
                if len(files) >= self._max_files:
                    truncated = True
                    break

                full_path = Path(dirpath) / filename
                try:
                    size_bytes = full_path.stat().st_size
                except OSError:
                    continue  # broken symlink or permission error; skip, don't fail the scan

                relative_path = full_path.relative_to(workspace_root).as_posix()
                files.append(
                    ScannedFile(
                        relative_path=relative_path,
                        extension=full_path.suffix.lower(),
                        size_bytes=size_bytes,
                    )
                )

            if truncated:
                break

        return ScanResult(files=files, truncated=truncated)
