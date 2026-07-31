import json
from pathlib import Path

from workspace.framework_detection import FrameworkDetector
from workspace.permissions import PermissionManager
from workspace.scanner import RepositoryScanner


def test_detects_fastapi_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["fastapi>=0.115", "pydantic>=2.9"]\n'
    )
    scan = RepositoryScanner().scan(tmp_path)
    detector = FrameworkDetector(PermissionManager(tmp_path))
    names = {match.name for match in detector.detect(scan.files)}
    assert "FastAPI" in names


def test_detects_react_from_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    scan = RepositoryScanner().scan(tmp_path)
    detector = FrameworkDetector(PermissionManager(tmp_path))
    assert any(match.name == "React" for match in detector.detect(scan.files))


def test_detects_django_from_marker_file(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("#!/usr/bin/env python")
    scan = RepositoryScanner().scan(tmp_path)
    detector = FrameworkDetector(PermissionManager(tmp_path))
    django = next(match for match in detector.detect(scan.files) if match.name == "Django")
    assert "manage.py" in django.evidence


def test_no_matches_for_empty_workspace(tmp_path: Path) -> None:
    scan = RepositoryScanner().scan(tmp_path)
    detector = FrameworkDetector(PermissionManager(tmp_path))
    assert detector.detect(scan.files) == []


def test_combines_dependency_and_marker_evidence(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"next": "^14.0.0"}}))
    (tmp_path / "next.config.js").write_text("module.exports = {}")
    scan = RepositoryScanner().scan(tmp_path)
    detector = FrameworkDetector(PermissionManager(tmp_path))
    match = next(m for m in detector.detect(scan.files) if m.name == "Next.js")
    assert "next" in match.evidence
    assert "next.config.js" in match.evidence


def test_ignores_malformed_manifest(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{not valid json")
    scan = RepositoryScanner().scan(tmp_path)
    detector = FrameworkDetector(PermissionManager(tmp_path))
    assert detector.detect(scan.files) == []
