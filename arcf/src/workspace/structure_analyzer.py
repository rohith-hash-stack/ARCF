"""Project Structure Analyzer (Phase 4 deliverable).

Infers layout conventions (src-layout, flat-layout, monorepo) and
locates manifest/test directories from the scanner's file inventory —
directory-name and path-shape heuristics only, no parsing of file
contents (that's framework_detection.py's job, for the manifests
themselves).
"""

from domain.workspace import ProjectLayout, ProjectStructure
from workspace.scanner import ScannedFile

MANIFEST_FILENAMES: frozenset[str] = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "Gemfile",
        "composer.json",
    }
)

TEST_DIRECTORY_NAMES: frozenset[str] = frozenset({"tests", "test", "__tests__", "spec"})


class ProjectStructureAnalyzer:
    def analyze(self, files: list[ScannedFile]) -> ProjectStructure:
        manifest_paths: set[str] = set()
        manifest_dirs: set[str] = set()
        test_directories: set[str] = set()
        has_root_level_files = False
        has_src_dir_files = False

        for file in files:
            parts = file.relative_path.split("/")
            filename = parts[-1]
            directory = "/".join(parts[:-1])

            if filename in MANIFEST_FILENAMES:
                manifest_paths.add(file.relative_path)
                manifest_dirs.add(directory)

            if len(parts) == 1:
                has_root_level_files = True
            elif parts[0] == "src":
                has_src_dir_files = True

            for name in TEST_DIRECTORY_NAMES:
                if name in parts[:-1]:
                    test_directories.add("/".join(parts[: parts.index(name) + 1]))
                    break

        layout: ProjectLayout
        if has_src_dir_files:
            layout = "src-layout"
        elif len(manifest_dirs) > 1:
            layout = "monorepo"
        elif manifest_paths and has_root_level_files:
            layout = "flat-layout"
        else:
            layout = "unknown"

        return ProjectStructure(
            layout=layout,
            manifest_files=sorted(manifest_paths),
            test_directories=sorted(test_directories),
        )
