"""Workspace Analyzer — orchestrates Phase 4's deterministic discovery
pipeline into one WorkspaceMetadata snapshot.

Assumes workspace_root has already been cleared by the caller's access
policy (WorkspaceContractService checks the allowlist) — this class
validates the path exists and does the analysis, not the "who's allowed
to point ARCF at this path" decision.
"""

from pathlib import Path

from domain.workspace import WorkspaceMetadata
from shared.errors import WorkspacePathError
from workspace.framework_detection import FrameworkDetector
from workspace.git_discovery import GitRepositoryDiscovery
from workspace.language_detection import LanguageDetector
from workspace.permissions import PermissionManager
from workspace.scanner import RepositoryScanner
from workspace.structure_analyzer import ProjectStructureAnalyzer


class WorkspaceAnalyzer:
    def __init__(
        self,
        git_discovery: GitRepositoryDiscovery,
        scanner: RepositoryScanner,
        language_detector: LanguageDetector,
        structure_analyzer: ProjectStructureAnalyzer,
    ) -> None:
        self._git_discovery = git_discovery
        self._scanner = scanner
        self._language_detector = language_detector
        self._structure_analyzer = structure_analyzer

    def analyze(self, workspace_root: Path) -> WorkspaceMetadata:
        if not workspace_root.is_dir():
            raise WorkspacePathError(f"{workspace_root} is not an existing directory")

        permissions = PermissionManager(workspace_root)
        framework_detector = FrameworkDetector(permissions)

        repository = self._git_discovery.discover(workspace_root)
        scan_result = self._scanner.scan(workspace_root)
        languages = self._language_detector.detect(scan_result.files)
        structure = self._structure_analyzer.analyze(scan_result.files)
        frameworks = framework_detector.detect(scan_result.files)
        sensitive_paths = [
            file.relative_path
            for file in scan_result.files
            if permissions.is_sensitive(file.relative_path)
        ]

        return WorkspaceMetadata(
            workspace_root=str(permissions.workspace_root),
            repository=repository,
            languages=languages,
            frameworks=frameworks,
            structure=structure,
            file_count=len(scan_result.files),
            truncated=scan_result.truncated,
            sensitive_paths=sensitive_paths,
        )
