from pathlib import Path

import pytest

from shared.errors import WorkspacePathError
from workspace.analyzer import WorkspaceAnalyzer
from workspace.git_discovery import GitRepositoryDiscovery
from workspace.language_detection import LanguageDetector
from workspace.scanner import RepositoryScanner
from workspace.structure_analyzer import ProjectStructureAnalyzer


def _analyzer() -> WorkspaceAnalyzer:
    return WorkspaceAnalyzer(
        git_discovery=GitRepositoryDiscovery(),
        scanner=RepositoryScanner(),
        language_detector=LanguageDetector(),
        structure_analyzer=ProjectStructureAnalyzer(),
    )


def test_analyze_produces_full_metadata(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]\n')
    (tmp_path / "app.py").write_text("print(1)")
    (tmp_path / ".env").write_text("SECRET=1")

    metadata = _analyzer().analyze(tmp_path)

    assert metadata.repository.is_git_repo is False
    assert metadata.file_count == 3
    assert any(lang.language == "Python" for lang in metadata.languages)
    assert any(fw.name == "FastAPI" for fw in metadata.frameworks)
    assert ".env" in metadata.sensitive_paths
    assert metadata.truncated is False


def test_analyze_raises_for_nonexistent_directory(tmp_path: Path) -> None:
    with pytest.raises(WorkspacePathError):
        _analyzer().analyze(tmp_path / "does_not_exist")
