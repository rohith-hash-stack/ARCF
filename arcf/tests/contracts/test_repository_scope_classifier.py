from contracts.repository_scope_classifier import RepositoryScopeClassifier


def test_classifies_documentation_request_as_repository_scoped() -> None:
    classifier = RepositoryScopeClassifier()
    result = classifier.classify(
        "Generate clear documentation for this repository's test suite, including setup, "
        "execution, and contribution guidelines."
    )
    assert result.repository_scope is True
    assert result.task_type == "repository_documentation"


def test_strong_trigger_phrases_are_scoped_even_without_repository_word() -> None:
    classifier = RepositoryScopeClassifier()
    for phrase in (
        "please write a README for this",
        "generate documentation for the auth module",
        "explain this repository to a new hire",
        "summarize the test suite",
    ):
        assert classifier.classify(phrase).repository_scope is True


def test_unrelated_request_is_not_repository_scoped() -> None:
    classifier = RepositoryScopeClassifier()
    result = classifier.classify("Fix the null pointer exception in authenticate()")
    assert result.repository_scope is False
    assert result.task_type == "unscoped"


def test_empty_request_is_not_repository_scoped() -> None:
    classifier = RepositoryScopeClassifier()
    result = classifier.classify("")
    assert result.repository_scope is False


def test_debugging_examples_classify_as_repository_debugging() -> None:
    classifier = RepositoryScopeClassifier()
    examples = (
        "I'm seeing a failing test in this repo",
        "Help me debug this failure",
        "Diagnose this error in the repository",
        "Suggest the first places to inspect",
        "Investigate why this test is failing",
        "Find the likely root cause of this regression",
        "Help me diagnose this repository failure",
        "Investigate why this code is failing",
        "Find the likely root cause",
    )
    for query in examples:
        result = classifier.classify(query)
        assert result.repository_scope is True, query
        assert result.task_type == "repository_debugging", query


def test_debugging_takes_precedence_over_documentation_language() -> None:
    classifier = RepositoryScopeClassifier()
    result = classifier.classify(
        "Explain this repository's failing test and document the root cause"
    )
    assert result.task_type == "repository_debugging"


def test_non_debugging_request_is_not_repository_debugging() -> None:
    classifier = RepositoryScopeClassifier()
    result = classifier.classify("Add a new field to the user profile form")
    assert result.task_type != "repository_debugging"
    assert result.repository_scope is False
