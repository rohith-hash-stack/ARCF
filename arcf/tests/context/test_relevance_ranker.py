from context.relevance_ranker import RelevanceRanker
from context.task_profile import RANKING_PROFILES, RetrievalTaskType
from domain.code_intelligence import SymbolKind
from domain.context_resolution import (
    ContextResolutionResult,
    FileReference,
    SymbolReference,
    TokenEstimate,
)


def _symbol(name: str, file_path: str, kind: SymbolKind = SymbolKind.FUNCTION) -> SymbolReference:
    return SymbolReference(
        symbol_id=f"{file_path}::{name}",
        name=name,
        qualified_name=name,
        kind=kind,
        file_path=file_path,
        start_line=1,
        end_line=2,
    )


def _result(
    candidate_files: list[FileReference],
    entry_points: list[SymbolReference] | None = None,
    impacted_symbols: list[SymbolReference] | None = None,
) -> ContextResolutionResult:
    return ContextResolutionResult(
        workspace_id="ws",
        contract_id="c1",
        repository_root="/repo",
        language="python",
        candidate_files=candidate_files,
        entry_points=entry_points or [],
        impacted_symbols=impacted_symbols or [],
        confidence=1.0,
        token_estimate=TokenEstimate(
            raw_context_tokens=100, selected_context_tokens=50, compression_ratio=0.5
        ),
        resolution_reason="test",
    )


def test_defines_ranks_above_calls_ranks_above_extends() -> None:
    result = _result(
        [
            FileReference(
                file_path="c.py", reason="extends Base", language="python", token_count=10
            ),
            FileReference(
                file_path="a.py", reason="defines foo", language="python", token_count=10
            ),
            FileReference(
                file_path="b.py", reason="calls foo", language="python", token_count=10
            ),
        ]
    )
    ranked = RelevanceRanker().rank(result)
    assert [r.file_path for r in ranked] == ["a.py", "b.py", "c.py"]


def test_unknown_reason_gets_default_weight() -> None:
    result = _result(
        [FileReference(file_path="a.py", reason="related", language="python", token_count=5)]
    )
    ranked = RelevanceRanker().rank(result)
    assert ranked[0].relevance_score == 0.3


def test_entry_point_file_gets_bonus() -> None:
    result = _result(
        [
            FileReference(file_path="a.py", reason="calls foo", language="python", token_count=5),
            FileReference(file_path="b.py", reason="calls foo", language="python", token_count=5),
        ],
        entry_points=[_symbol("foo", "a.py")],
    )
    ranked = RelevanceRanker().rank(result)
    a_score = next(r.relevance_score for r in ranked if r.file_path == "a.py")
    b_score = next(r.relevance_score for r in ranked if r.file_path == "b.py")
    assert a_score > b_score


def test_more_impacted_symbols_scores_higher() -> None:
    result = _result(
        [
            FileReference(file_path="a.py", reason="calls foo", language="python", token_count=5),
            FileReference(file_path="b.py", reason="calls foo", language="python", token_count=5),
        ],
        impacted_symbols=[
            _symbol("x", "a.py"),
            _symbol("y", "a.py"),
            _symbol("z", "a.py"),
        ],
    )
    ranked = RelevanceRanker().rank(result)
    a_score = next(r.relevance_score for r in ranked if r.file_path == "a.py")
    b_score = next(r.relevance_score for r in ranked if r.file_path == "b.py")
    assert a_score > b_score


def test_score_never_exceeds_one() -> None:
    result = _result(
        [FileReference(file_path="a.py", reason="defines foo", language="python", token_count=5)],
        entry_points=[_symbol("foo", "a.py")],
        impacted_symbols=[_symbol(f"s{i}", "a.py") for i in range(10)],
    )
    ranked = RelevanceRanker().rank(result)
    assert ranked[0].relevance_score <= 1.0


def test_references_outranks_generic_evidence_default_weight() -> None:
    """"references: ..." (query-referenced files, context/evidence_fallback.py)
    is weighted above the default weight generic "evidence: <category>"
    files fall back to — the only pairing that actually occurs in
    practice, since both only ever appear together in an evidence-only
    fallback candidate list (never alongside defines/calls/extends)."""
    result = _result(
        [
            FileReference(
                file_path="a.py",
                reason="evidence: project metadata",
                language="unknown",
                token_count=10,
            ),
            FileReference(
                file_path="b.py",
                reason="references: query-referenced",
                language="python",
                token_count=10,
            ),
        ]
    )
    ranked = RelevanceRanker().rank(result)
    assert [r.file_path for r in ranked] == ["b.py", "a.py"]


def test_called_by_scores_the_same_as_calls() -> None:
    """ARCF Issue #9 fix (2026-08-08): ContextResolver emits "called by X
    (hop N)" for transitive callees, not "calls X" — the reason-verb
    table had no entry for "called", so these files silently fell to the
    generic default weight instead of the "calls" weight intended for
    call-graph relationships. Found via real SQLAlchemy data, where this
    suppressed both canonical files' scores in the repository_explanation
    profile."""
    result = _result(
        [
            FileReference(
                file_path="a.py", reason="calls foo", language="python", token_count=5
            ),
            FileReference(
                file_path="b.py",
                reason="called by foo (hop 1)",
                language="python",
                token_count=5,
            ),
        ]
    )
    ranked = RelevanceRanker().rank(result)
    a_score = next(r.relevance_score for r in ranked if r.file_path == "a.py")
    b_score = next(r.relevance_score for r in ranked if r.file_path == "b.py")
    assert a_score == b_score


def test_called_matches_calls_weight_in_every_profile() -> None:
    """The actual invariant issue #9 requires: "called" and "calls" score
    identically within any given profile — not that call-graph evidence
    always beats the generic default, which some profiles (CI_CD:
    "almost entirely evidence-contract-driven, not call-graph-driven")
    deliberately weight call-graph relationships below."""
    result = _result(
        [
            FileReference(
                file_path="a.py", reason="calls foo", language="python", token_count=5
            ),
            FileReference(
                file_path="b.py",
                reason="called by foo (hop 2)",
                language="python",
                token_count=5,
            ),
        ]
    )
    for task_type in RetrievalTaskType:
        ranked = RelevanceRanker().rank(result, profile=RANKING_PROFILES[task_type])
        a_score = next(r.relevance_score for r in ranked if r.file_path == "a.py")
        b_score = next(r.relevance_score for r in ranked if r.file_path == "b.py")
        assert a_score == b_score, f"{task_type} scored 'called by' differently from 'calls'"


def test_empty_candidates_returns_empty_list() -> None:
    result = _result([])
    assert RelevanceRanker().rank(result) == []


def test_no_profile_reproduces_pre_hardening_weights_exactly() -> None:
    result = _result(
        [
            FileReference(file_path="a.py", reason="defines foo", language="python", token_count=5),
            FileReference(file_path="b.py", reason="calls foo", language="python", token_count=5),
        ]
    )
    without_profile = RelevanceRanker().rank(result)
    with_unknown_profile = RelevanceRanker().rank(
        result, profile=RANKING_PROFILES[RetrievalTaskType.UNKNOWN]
    )
    assert without_profile == with_unknown_profile


def test_ci_cd_profile_ranks_evidence_above_calls() -> None:
    result = _result(
        [
            FileReference(
                file_path="workflow.yml",
                reason="evidence: CI/workflow files",
                language="yaml",
                token_count=5,
            ),
            FileReference(
                file_path="handler.py", reason="calls foo", language="python", token_count=5
            ),
        ]
    )
    ranked = RelevanceRanker().rank(result, profile=RANKING_PROFILES[RetrievalTaskType.CI_CD])
    assert [r.file_path for r in ranked] == ["workflow.yml", "handler.py"]


def test_bug_fix_profile_still_ranks_calls_above_generic_evidence() -> None:
    result = _result(
        [
            FileReference(
                file_path="config.py",
                reason="evidence: configuration",
                language="python",
                token_count=5,
            ),
            FileReference(
                file_path="caller.py", reason="calls foo", language="python", token_count=5
            ),
        ]
    )
    ranked = RelevanceRanker().rank(result, profile=RANKING_PROFILES[RetrievalTaskType.BUG_FIX])
    assert [r.file_path for r in ranked] == ["caller.py", "config.py"]


def test_every_ranking_profile_produces_a_valid_deterministic_order() -> None:
    result = _result(
        [
            FileReference(file_path="a.py", reason="defines foo", language="python", token_count=5),
            FileReference(file_path="b.py", reason="calls foo", language="python", token_count=5),
            FileReference(
                file_path="c.py", reason="evidence: configuration", language="python", token_count=5
            ),
        ]
    )
    for task_type in RetrievalTaskType:
        ranked_once = RelevanceRanker().rank(result, profile=RANKING_PROFILES[task_type])
        ranked_again = RelevanceRanker().rank(result, profile=RANKING_PROFILES[task_type])
        assert ranked_once == ranked_again
        assert {r.file_path for r in ranked_once} == {"a.py", "b.py", "c.py"}


def test_ranking_is_deterministic() -> None:
    result = _result(
        [
            FileReference(file_path="a.py", reason="defines foo", language="python", token_count=5),
            FileReference(file_path="b.py", reason="calls foo", language="python", token_count=5),
        ]
    )
    first = RelevanceRanker().rank(result)
    second = RelevanceRanker().rank(result)
    assert first == second
