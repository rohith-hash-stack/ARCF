"""Deterministic clarification planning.

Decides *whether* to ask and *what* to ask from concrete gaps (missing
domain/task/entities) plus the confidence score, rather than asking the
SLM whether it's confident — an ambiguous request should always
surface the same questions given the same extracted facts.
"""


class ClarificationPlanner:
    def __init__(self, confidence_threshold: float = 0.6) -> None:
        self._threshold = confidence_threshold

    def plan(
        self, domain: str, task: str, entities: list[str], confidence: float
    ) -> list[str]:
        questions: list[str] = []

        if domain == "unknown":
            questions.append(
                "Which part of the system does this affect "
                "(e.g. backend, frontend, tests, infrastructure)?"
            )
        if task == "unknown":
            questions.append(
                "What kind of change is this: a bug fix, a new feature, a refactor, "
                "or something else?"
            )
        if not entities:
            questions.append("Can you name the specific files, functions, or components involved?")

        if confidence < self._threshold and not questions:
            questions.append("Could you provide a bit more detail about what you'd like done?")

        return questions
