"""Deterministic task classification — the same role as DomainClassifier,
scoped to *what kind* of change is being requested rather than *where*.
"""

TASK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "bug_fix": ("fix", "bug", "broken", "failing", "error", "crash", "regression"),
    "feature": ("add", "implement", "create", "new feature", "support for"),
    "refactor": ("refactor", "clean up", "restructure", "simplify", "reorganize"),
    "documentation": ("document", "readme", "explain", "changelog"),
    "test": ("test", "coverage", "assert", "spec", "unit tests"),
}


class TaskClassifier:
    def classify(self, text: str) -> str:
        text_lower = text.lower()
        scores = {
            task: sum(1 for keyword in keywords if keyword in text_lower)
            for task, keywords in TASK_KEYWORDS.items()
        }
        best_task, best_score = max(scores.items(), key=lambda item: item[1])
        return best_task if best_score > 0 else "unknown"

    def agrees_with(self, text: str, claimed_task: str) -> bool:
        deterministic_guess = self.classify(text)
        return deterministic_guess == "unknown" or deterministic_guess == claimed_task
