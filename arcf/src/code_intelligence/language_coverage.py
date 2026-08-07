"""LanguageCoverage (ARCF architecture hardening §5, §13) — deterministic
language capability registry.

Cross-references workspace/language_detection.py's extension-based
LanguageDetector output against LanguageRegistry's registered analyzers
so an unsupported language is reported, not silently assumed away.
Multi-language analyzer scaffolding itself (Python, TypeScript/JavaScript,
Java, C#, Go, Kotlin) already exists — see interfaces/api/app.py's
LanguageRegistry construction — the real gap this module closes is
*reporting* coverage, not adding more analyzers.
"""

from dataclasses import dataclass

from code_intelligence.registry import LanguageRegistry
from workspace.language_detection import LanguageDetector
from workspace.scanner import ScannedFile

# LanguageDetector's display names (Title Case, or "C#") -> the lowercase
# key each LanguageAnalyzer.language property returns. A display name
# with no entry here has no registered analyzer today, by definition.
DETECTOR_NAME_TO_ANALYZER_LANGUAGE: dict[str, str] = {
    "Python": "python",
    "TypeScript": "typescript",
    "JavaScript": "typescript",  # same analyzer handles both dialects
    "Java": "java",
    "Go": "go",
    "C#": "csharp",
    "Kotlin": "kotlin",
}


@dataclass(frozen=True)
class LanguageCoverage:
    languages_detected: tuple[str, ...]
    """Every language LanguageDetector found at least one file for,
    ranked by file count (its own existing ordering)."""
    languages_supported: tuple[str, ...]
    """Subset of languages_detected that have a registered
    LanguageAnalyzer able to index them."""
    languages_unsupported: tuple[str, ...]
    """Subset of languages_detected with no registered analyzer — these
    files are counted by the scanner but never indexed."""
    files_skipped_count: int
    """Total files never analyzed: every file in an unsupported detected
    language, plus files whose extension LanguageDetector doesn't even
    recognize."""


def compute_language_coverage(
    files: list[ScannedFile], registry: LanguageRegistry
) -> LanguageCoverage:
    stats = LanguageDetector().detect(files)
    registered_languages = set(registry.languages)

    detected: list[str] = []
    supported: list[str] = []
    unsupported: list[str] = []
    recognized_file_count = 0

    for stat in stats:
        detected.append(stat.language)
        recognized_file_count += stat.file_count
        analyzer_language = DETECTOR_NAME_TO_ANALYZER_LANGUAGE.get(stat.language)
        if analyzer_language is not None and analyzer_language in registered_languages:
            supported.append(stat.language)
        else:
            unsupported.append(stat.language)

    unsupported_set = set(unsupported)
    files_skipped = sum(stat.file_count for stat in stats if stat.language in unsupported_set)
    # Files LanguageDetector doesn't recognize the extension of at all.
    files_skipped += len(files) - recognized_file_count

    return LanguageCoverage(
        languages_detected=tuple(detected),
        languages_supported=tuple(supported),
        languages_unsupported=tuple(unsupported),
        files_skipped_count=files_skipped,
    )
