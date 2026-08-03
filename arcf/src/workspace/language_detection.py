"""Language Detection (Phase 4 deliverable).

Deterministic extension-to-language lookup over the scanner's file
inventory — no heuristic content sniffing, no ML classifier. Percentage
is relative to files that mapped to a known language, not the total
file count, so a repo full of images/lockfiles doesn't dilute the
signal for the languages that are actually there.
"""

from collections import Counter

from domain.workspace import LanguageStat
from workspace.scanner import ScannedFile

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".less": "Less",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".md": "Markdown",
    ".vue": "Vue",
}


class LanguageDetector:
    def detect(self, files: list[ScannedFile]) -> list[LanguageStat]:
        counts: Counter[str] = Counter()
        for file in files:
            language = EXTENSION_LANGUAGE_MAP.get(file.extension)
            if language is not None:
                counts[language] += 1

        total = sum(counts.values())
        if total == 0:
            return []

        stats = [
            LanguageStat(
                language=language,
                file_count=count,
                percentage=round(count / total * 100, 2),
            )
            for language, count in counts.items()
        ]
        return sorted(stats, key=lambda stat: stat.file_count, reverse=True)
