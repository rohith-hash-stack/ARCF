from pathlib import Path

import pytest
from workspace.analyzer import WorkspaceAnalyzer
from workspace.git_discovery import GitRepositoryDiscovery
from workspace.language_detection import LanguageDetector
from workspace.scanner import RepositoryScanner
from workspace.structure_analyzer import ProjectStructureAnalyzer

from benchmark.repository import RepositoryLoader


def _loader(tmp_path: Path) -> RepositoryLoader:
    return RepositoryLoader(
        clone_root=tmp_path / "clones",
        analyzer=WorkspaceAnalyzer(
            git_discovery=GitRepositoryDiscovery(),
            scanner=RepositoryScanner(),
            language_detector=LanguageDetector(),
            structure_analyzer=ProjectStructureAnalyzer(),
        ),
        scanner=RepositoryScanner(),
    )


def test_open_local_returns_metadata_and_scan(tmp_path: Path) -> None:
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("def foo():\n    pass\n")

    loaded = _loader(tmp_path).open_local(str(repo_dir))

    assert loaded.root == repo_dir.resolve()
    assert loaded.metadata.file_count == 1
    assert any(f.relative_path == "app.py" for f in loaded.scan.files)
    assert loaded.metadata.repository.is_git_repo is False


def test_open_local_raises_for_nonexistent_path(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        _loader(tmp_path).open_local(str(tmp_path / "does_not_exist"))


def test_slug_for_strips_git_suffix_and_traversal() -> None:
    assert RepositoryLoader._slug_for("https://github.com/org/repo.git") == "repo"
    assert RepositoryLoader._slug_for("https://github.com/org/repo") == "repo"
    assert RepositoryLoader._slug_for("https://example.com/../../etc") == "etc"
