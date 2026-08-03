"""RepositoryLoader — clone a git repo or open a local one.

Reuses ARCF's own WorkspaceAnalyzer (git/language/framework detection,
for display) and RepositoryScanner (raw file inventory, for
DirectLLMRunner's baseline) directly — not reimplemented — so both
benchmark modes start from the IDENTICAL file inventory ARCF itself
would see. Isolating the effect of ARCF's selection logic, not the
effect of a different file listing, is the whole point of the
benchmark.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

import git
from domain.workspace import WorkspaceMetadata
from workspace.analyzer import WorkspaceAnalyzer
from workspace.scanner import RepositoryScanner, ScanResult


@dataclass(frozen=True)
class LoadedRepository:
    root: Path
    metadata: WorkspaceMetadata
    scan: ScanResult


class RepositoryLoader:
    def __init__(
        self,
        clone_root: Path,
        analyzer: WorkspaceAnalyzer,
        scanner: RepositoryScanner,
    ) -> None:
        self._clone_root = clone_root
        self._analyzer = analyzer
        self._scanner = scanner

    def open_local(self, path: str) -> LoadedRepository:
        root = Path(path).resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"{root} is not an existing directory")
        return self._load(root)

    def clone(self, url: str, ref: str | None = None) -> LoadedRepository:
        self._clone_root.mkdir(parents=True, exist_ok=True)
        dest = self._clone_root / self._slug_for(url)
        if dest.exists():
            shutil.rmtree(dest)
        if ref:
            git.Repo.clone_from(url, dest, branch=ref)
        else:
            git.Repo.clone_from(url, dest)
        return self._load(dest)

    def _load(self, root: Path) -> LoadedRepository:
        metadata = self._analyzer.analyze(root)
        scan = self._scanner.scan(root)
        return LoadedRepository(root=root, metadata=metadata, scan=scan)

    @staticmethod
    def _slug_for(url: str) -> str:
        """Last path segment only — a malicious `../../x` in the URL
        can't escape clone_root since only the basename is used."""
        name = url.rstrip("/").rsplit("/", 1)[-1]
        return name[:-4] if name.endswith(".git") else name
