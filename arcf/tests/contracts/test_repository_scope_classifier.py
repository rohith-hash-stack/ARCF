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


def test_explanation_verb_scopes_request_without_a_repository_noun() -> None:
    """Classifier-gap fix, layer 1 (§4.1 of the 2026-08-06 handoff):
    conceptual questions like "Explain how X works" never say "repo"/
    "codebase"/"project", but an explanation verb is still almost always
    about this tool's attached workspace — same reasoning
    _DEBUGGING_STRONG_TRIGGERS already established for debugging
    phrases."""
    classifier = RepositoryScopeClassifier()
    examples = (
        "Explain how dependency injection works internally and how "
        "request-scoped dependencies are resolved.",
        "Describe how the Fiber reconciler performs work scheduling "
        "differently from the legacy stack reconciler.",
        "Summarize how App Router streaming with React Server "
        "Components works.",
    )
    for query in examples:
        result = classifier.classify(query)
        assert result.repository_scope is True, query
        assert result.task_type == "repository_documentation", query


def test_debugging_verb_scopes_request_without_a_repository_noun() -> None:
    """Same fix as the explanation-verb case above, applied to the
    debugging side: real Batch 1 data ("Debug an N+1 query issue
    introduced by a recent ORM refactor.") named no repository/codebase/
    project word, so it fell through to unscoped even though "debug" is
    an unambiguous action verb for this tool. Only the action verbs
    (debug/diagnose/investigate) are ungated, not the passive nouns
    (error/exception/crash/...), since those appear in plenty of
    non-debugging requests too."""
    classifier = RepositoryScopeClassifier()
    result = classifier.classify(
        "Debug an N+1 query issue introduced by a recent ORM refactor."
    )
    assert result.repository_scope is True
    assert result.task_type == "repository_debugging"


def test_debugging_noun_alone_stays_unscoped_without_repository_context() -> None:
    """The passive/descriptive debugging words (unlike the action verbs)
    stay gated — "exception" alone, naming a concrete resolvable symbol,
    shouldn't force repository-wide evidence expansion the way a bare
    "debug"/"diagnose"/"investigate" request should."""
    classifier = RepositoryScopeClassifier()
    result = classifier.classify("Fix the null pointer exception in authenticate()")
    assert result.repository_scope is False
    assert result.task_type == "unscoped"
