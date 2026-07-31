"""LanguageRegistry — dispatches a file path to the LanguageAnalyzer
that should parse it.

The only place that knows which languages exist. CodeIntelligenceEngine
never checks a file extension itself; it always asks the registry.
"""

from code_intelligence.language_analyzer import LanguageAnalyzer


class LanguageRegistry:
    def __init__(self, analyzers: list[LanguageAnalyzer]) -> None:
        self._analyzers = analyzers

    def for_file(self, file_path: str) -> LanguageAnalyzer | None:
        for analyzer in self._analyzers:
            if analyzer.handles(file_path):
                return analyzer
        return None

    @property
    def languages(self) -> list[str]:
        return [analyzer.language for analyzer in self._analyzers]
