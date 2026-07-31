"""Deterministic domain classification — no LLM involved.

Exists to corroborate SLM-1's semantic guess, not replace it: the final
domain label still comes from the SLM (nuanced requests need real
understanding), but agreement between this keyword lookup and the SLM's
claim is a concrete, reproducible signal ConfidenceEngine uses. A
disagreement means either the request is ambiguous or the SLM
hallucinated a domain — both are reasons to lower confidence.
"""

DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "frontend": ("react", "vue", "css", "html", "ui", "component", "frontend", "browser"),
    "backend": ("api", "endpoint", "server", "database", "backend", "service", "controller"),
    "testing": ("test", "pytest", "playwright", "spec", "unit test", "e2e", "assertion"),
    "infrastructure": ("docker", "kubernetes", "ci", "pipeline", "deploy", "terraform", "infra"),
    "data": ("dataset", "schema", "migration", "sql", "etl", "data pipeline"),
    "documentation": ("readme", "docs", "documentation", "changelog"),
}


class DomainClassifier:
    def classify(self, text: str) -> str:
        text_lower = text.lower()
        scores = {
            domain: sum(1 for keyword in keywords if keyword in text_lower)
            for domain, keywords in DOMAIN_KEYWORDS.items()
        }
        best_domain, best_score = max(scores.items(), key=lambda item: item[1])
        return best_domain if best_score > 0 else "unknown"

    def agrees_with(self, text: str, claimed_domain: str) -> bool:
        deterministic_guess = self.classify(text)
        return deterministic_guess == "unknown" or deterministic_guess == claimed_domain
