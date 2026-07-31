from contracts.task_classifier import TaskClassifier


def test_classifies_known_task_by_keyword() -> None:
    classifier = TaskClassifier()
    assert classifier.classify("Fix the broken login flow") == "bug_fix"
    assert classifier.classify("Add support for dark mode") == "feature"
    assert classifier.classify("Refactor the auth module to simplify it") == "refactor"


def test_unknown_when_no_keywords_match() -> None:
    classifier = TaskClassifier()
    assert classifier.classify("do the thing please") == "unknown"


def test_agrees_with_returns_true_when_deterministic_guess_is_unknown() -> None:
    classifier = TaskClassifier()
    assert classifier.agrees_with("do the thing please", "feature") is True


def test_agrees_with_returns_false_on_contradiction() -> None:
    classifier = TaskClassifier()
    assert classifier.agrees_with("fix the broken login flow", "feature") is False
