"""Deterministic task classification — the same role as DomainClassifier,
scoped to *what kind* of change is being requested rather than *where*.
"""

import re

TASK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "bug_fix": ("fix", "bug", "broken", "failing", "error", "crash", "regression"),
    "feature": ("add", "implement", "create", "new feature", "support for"),
    "refactor": ("refactor", "clean up", "restructure", "simplify", "reorganize"),
    "documentation": ("document", "readme", "explain", "changelog"),
    "test": ("test", "coverage", "assert", "spec", "unit tests"),
}


def _keyword_present(keyword: str, text_lower: str) -> bool:
    """Plain substring match, except a keyword immediately followed by
    "ation" doesn't count — real bug found 2026-08-11
    (scripts/contract_creation_slm1_experiment.py, a real SLM-1-vs-
    deterministic-classifier agreement experiment): "implement" (a
    feature-REQUEST verb) substring-matched inside "implementation" (an
    EXISTING-code noun — a materially different meaning), so "Refactor a
    custom matcher implementation..." tied "feature" against the query's
    own literal word "refactor" and picked "feature" via dict
    iteration order. "-ation" reliably turns a verb into a different
    derived noun in English (implement/implementation, observe/
    observation) — excluding that one suffix shape is a small, targeted
    fix for the proven case, not a general stemmer; every other
    currently-correct substring match (test/tests, fix/fixes, spec/
    specs, ...) is deliberately left untouched."""
    return re.search(re.escape(keyword) + r"(?!ation)", text_lower) is not None


class TaskClassifier:
    def classify(self, text: str) -> str:
        text_lower = text.lower()
        scores = {
            task: sum(1 for keyword in keywords if _keyword_present(keyword, text_lower))
            for task, keywords in TASK_KEYWORDS.items()
        }
        best_task, best_score = max(scores.items(), key=lambda item: item[1])
        return best_task if best_score > 0 else "unknown"

    def agrees_with(self, text: str, claimed_task: str) -> bool:
        deterministic_guess = self.classify(text)
        return deterministic_guess == "unknown" or deterministic_guess == claimed_task
