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


def test_implementation_noun_does_not_false_match_implement_feature_keyword() -> None:
    """Real bug, found 2026-08-11 via scripts/contract_creation_slm1_
    experiment.py (a real SLM-1-vs-deterministic-classifier agreement
    run against real queries): "implement" (feature keyword) substring-
    matched inside "implementation" (an existing-code noun, not a
    feature request), so this exact real query tied "feature" against
    the literal word "refactor" and picked "feature" via dict order —
    wrong. "implementation" must not count as an "implement" hit; the
    query's own literal "refactor" must win outright."""
    classifier = TaskClassifier()
    text = (
        "Refactor a custom matcher implementation so that failure messages "
        "remain descriptive without duplicating formatting logic."
    )
    assert classifier.classify(text) == "refactor"


def test_implement_still_matches_its_own_verb_forms() -> None:
    """The fix must stay narrowly scoped to the "-ation" suffix — every
    other real inflection of "implement" (as a verb, not the derived
    noun "implementation") must keep matching, same as before."""
    classifier = TaskClassifier()
    assert classifier.classify("Implement a new feature for dark mode") == "feature"
    assert classifier.classify("This class implements the interface") == "feature"
    assert classifier.classify("We implemented the login flow yesterday") == "feature"


def test_other_currently_correct_substring_matches_are_unaffected() -> None:
    """The fix only excludes the "-ation" shape — plural/inflected forms
    of every OTHER keyword (not just "implement") must keep matching
    exactly as before, since only "implement" -> "implementation" is a
    proven, real false positive."""
    classifier = TaskClassifier()
    assert classifier.classify("Write unit tests for the new module") == "test"
    assert classifier.classify("The build is failing with several fixes needed") == "bug_fix"
