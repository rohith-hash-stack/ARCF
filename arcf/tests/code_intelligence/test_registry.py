from code_intelligence.registry import LanguageRegistry
from domain.code_intelligence import FileAnalysis


class _FakeAnalyzer:
    def __init__(self, language: str, extension: str) -> None:
        self._language = language
        self._extension = extension

    @property
    def language(self) -> str:
        return self._language

    def handles(self, file_path: str) -> bool:
        return file_path.endswith(self._extension)

    def analyze_file(
        self, file_path: str, source_text: str, workspace_files: frozenset[str]
    ) -> FileAnalysis:
        return FileAnalysis(file_path=file_path, language=self._language)


def test_dispatches_to_matching_analyzer() -> None:
    py = _FakeAnalyzer("python", ".py")
    go = _FakeAnalyzer("go", ".go")
    registry = LanguageRegistry([py, go])

    assert registry.for_file("main.py") is py
    assert registry.for_file("main.go") is go


def test_returns_none_for_unregistered_extension() -> None:
    registry = LanguageRegistry([_FakeAnalyzer("python", ".py")])
    assert registry.for_file("main.rs") is None


def test_languages_property_lists_registered_languages() -> None:
    registry = LanguageRegistry([_FakeAnalyzer("python", ".py"), _FakeAnalyzer("go", ".go")])
    assert registry.languages == ["python", "go"]
