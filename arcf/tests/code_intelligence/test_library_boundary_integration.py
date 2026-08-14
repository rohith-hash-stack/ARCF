"""End-to-end Phase 2 check: DependencyManifestParser + LibraryBoundaryClassifier
against a small synthetic repo, run twice independently, asserting
byte-identical classification. This is the integration-level form of the
"byte-identical index across repeated runs" acceptance test agreed for
ARCF-DI — see arcf-di/PROGRESS.md and BLUEPRINT.md Phase 9."""

import json
from pathlib import Path

from code_intelligence.library_boundary import LibraryBoundaryClassifier
from domain.code_intelligence import ImportReference, SourceLocation
from workspace.dependency_manifest import DependencyManifestParser
from workspace.permissions import PermissionManager
from workspace.scanner import RepositoryScanner


def _loc(file_path: str) -> SourceLocation:
    return SourceLocation(file_path=file_path, start_line=1, end_line=1)


def _classify_repo(tmp_path: Path) -> list[dict]:
    scan = RepositoryScanner().scan(tmp_path)
    dependencies = DependencyManifestParser(PermissionManager(tmp_path)).parse(scan.files)
    classifier = LibraryBoundaryClassifier(dependencies)

    loc = _loc("app/main.py")
    imports = [
        # repository-internal: already resolved by the (simulated) analyzer
        ImportReference(
            source_file="app/main.py",
            raw_module=".sibling",
            resolved_file_path="app/sibling.py",
            location=loc,
        ),
        # stdlib
        ImportReference(source_file="app/main.py", raw_module="os.path", location=loc),
        # declared external
        ImportReference(source_file="app/main.py", raw_module="requests", location=loc),
        # unresolved: not declared, not stdlib
        ImportReference(source_file="app/main.py", raw_module="mystery_pkg", location=loc),
    ]
    results = classifier.classify(imports, language="python")
    return [
        {
            "raw_module": r.raw_module,
            "resolved_kind": r.resolved_kind,
            "resolved_library": r.resolved_library,
        }
        for r in results
    ]


def test_classification_is_byte_identical_across_independent_runs(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests>=2.28.0\n")

    first_run = _classify_repo(tmp_path)
    second_run = _classify_repo(tmp_path)

    assert json.dumps(first_run, sort_keys=True) == json.dumps(second_run, sort_keys=True)
    assert first_run == [
        {"raw_module": ".sibling", "resolved_kind": "repository", "resolved_library": None},
        {"raw_module": "os.path", "resolved_kind": "stdlib", "resolved_library": None},
        {"raw_module": "requests", "resolved_kind": "external", "resolved_library": "requests"},
        {"raw_module": "mystery_pkg", "resolved_kind": "unresolved", "resolved_library": None},
    ]
