from contracts.clarification import ClarificationPlanner


def test_no_questions_when_everything_known_and_confident() -> None:
    planner = ClarificationPlanner(confidence_threshold=0.6)
    questions = planner.plan(
        domain="testing", task="bug_fix", entities=["login_test.py"], confidence=0.9
    )
    assert questions == []


def test_asks_about_domain_when_unknown() -> None:
    planner = ClarificationPlanner()
    questions = planner.plan(domain="unknown", task="bug_fix", entities=["x"], confidence=0.9)
    assert any("system" in q.lower() for q in questions)


def test_asks_about_task_when_unknown() -> None:
    planner = ClarificationPlanner()
    questions = planner.plan(domain="backend", task="unknown", entities=["x"], confidence=0.9)
    assert any("kind of change" in q.lower() for q in questions)


def test_asks_for_entities_when_none_given() -> None:
    planner = ClarificationPlanner()
    questions = planner.plan(domain="backend", task="bug_fix", entities=[], confidence=0.9)
    assert any("files, functions" in q.lower() for q in questions)


def test_generic_question_when_low_confidence_but_nothing_specific_missing() -> None:
    planner = ClarificationPlanner(confidence_threshold=0.6)
    questions = planner.plan(
        domain="backend", task="bug_fix", entities=["x"], confidence=0.5
    )
    assert len(questions) == 1
    assert "more detail" in questions[0].lower()


def test_no_generic_question_added_when_specific_gaps_already_flagged() -> None:
    planner = ClarificationPlanner(confidence_threshold=0.9)
    questions = planner.plan(domain="unknown", task="bug_fix", entities=["x"], confidence=0.1)
    # confidence is below threshold, but a specific question already exists,
    # so no redundant generic question is appended
    assert len(questions) == 1
