from code_intelligence.language_coverage import compute_language_coverage
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from workspace.scanner import ScannedFile


def _file(path: str) -> ScannedFile:
    extension = "." + path.rsplit(".", 1)[-1] if "." in path else ""
    return ScannedFile(relative_path=path, extension=extension, size_bytes=1)


def test_fully_supported_repository_has_no_unsupported_languages() -> None:
    files = [_file("app.py"), _file("utils.py")]
    registry = LanguageRegistry([PythonLanguageAnalyzer()])
    coverage = compute_language_coverage(files, registry)

    assert coverage.languages_detected == ("Python",)
    assert coverage.languages_supported == ("Python",)
    assert coverage.languages_unsupported == ()
    assert coverage.files_skipped_count == 0


def test_unregistered_language_is_reported_unsupported() -> None:
    files = [_file("app.py"), _file("worker.go")]
    registry = LanguageRegistry([PythonLanguageAnalyzer()])
    coverage = compute_language_coverage(files, registry)

    assert "Go" in coverage.languages_detected
    assert "Go" in coverage.languages_unsupported
    assert "Go" not in coverage.languages_supported
    assert coverage.files_skipped_count == 1


def test_javascript_and_typescript_both_map_to_the_typescript_analyzer() -> None:
    files = [_file("index.ts"), _file("legacy.js")]
    registry = LanguageRegistry([TypeScriptLanguageAnalyzer()])
    coverage = compute_language_coverage(files, registry)

    assert set(coverage.languages_supported) == {"TypeScript", "JavaScript"}
    assert coverage.files_skipped_count == 0


def test_completely_unrecognized_extension_counts_toward_skipped() -> None:
    files = [_file("app.py"), _file("data.bin")]
    registry = LanguageRegistry([PythonLanguageAnalyzer()])
    coverage = compute_language_coverage(files, registry)

    assert coverage.files_skipped_count == 1
    assert "Python" in coverage.languages_supported


def test_no_files_yields_empty_coverage() -> None:
    registry = LanguageRegistry([PythonLanguageAnalyzer()])
    coverage = compute_language_coverage([], registry)

    assert coverage.languages_detected == ()
    assert coverage.files_skipped_count == 0
