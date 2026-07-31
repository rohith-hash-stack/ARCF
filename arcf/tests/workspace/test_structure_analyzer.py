from workspace.scanner import ScannedFile
from workspace.structure_analyzer import ProjectStructureAnalyzer


def _file(path: str) -> ScannedFile:
    return ScannedFile(relative_path=path, extension="", size_bytes=1)


def test_detects_src_layout() -> None:
    files = [
        _file("pyproject.toml"),
        _file("src/mypackage/__init__.py"),
        _file("tests/test_x.py"),
    ]
    structure = ProjectStructureAnalyzer().analyze(files)
    assert structure.layout == "src-layout"
    assert "pyproject.toml" in structure.manifest_files
    assert "tests" in structure.test_directories


def test_detects_flat_layout() -> None:
    files = [_file("pyproject.toml"), _file("mymodule.py")]
    structure = ProjectStructureAnalyzer().analyze(files)
    assert structure.layout == "flat-layout"


def test_detects_monorepo() -> None:
    files = [_file("packages/a/package.json"), _file("packages/b/package.json")]
    structure = ProjectStructureAnalyzer().analyze(files)
    assert structure.layout == "monorepo"


def test_unknown_layout_when_no_signals() -> None:
    files = [_file("notes.txt")]
    structure = ProjectStructureAnalyzer().analyze(files)
    assert structure.layout == "unknown"


def test_finds_nested_test_directories() -> None:
    files = [_file("app/__tests__/foo.test.js")]
    structure = ProjectStructureAnalyzer().analyze(files)
    assert "app/__tests__" in structure.test_directories
