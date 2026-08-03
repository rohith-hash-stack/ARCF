from contracts.domain_classifier import DomainClassifier


def test_classifies_known_domain_by_keyword() -> None:
    classifier = DomainClassifier()
    assert classifier.classify("Fix the failing Playwright test for login") == "testing"
    assert classifier.classify("Add a new REST API endpoint for users") == "backend"
    assert classifier.classify("Update the React component styling") == "frontend"


def test_unknown_when_no_keywords_match() -> None:
    classifier = DomainClassifier()
    assert classifier.classify("do the thing please") == "unknown"


def test_agrees_with_returns_true_when_deterministic_guess_is_unknown() -> None:
    classifier = DomainClassifier()
    assert classifier.agrees_with("do the thing please", "backend") is True


def test_agrees_with_returns_true_when_guesses_match() -> None:
    classifier = DomainClassifier()
    assert classifier.agrees_with("fix the failing pytest test", "testing") is True


def test_agrees_with_returns_false_on_contradiction() -> None:
    classifier = DomainClassifier()
    assert classifier.agrees_with("fix the failing pytest test", "frontend") is False
