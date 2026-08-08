from pathlib import Path

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.multi_hop_orchestrator import MultiHopOrchestrator
from code_intelligence.registry import LanguageRegistry
from domain.context_resolution import (
    ContextResolutionResult,
    EvidenceTier,
    FileReference,
    TokenEstimate,
)
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner


def _build_index(tmp_path: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    return engine.build_index(tmp_path, scan.files)


def _empty_result(repository_root: str) -> ContextResolutionResult:
    return ContextResolutionResult(
        workspace_id=repository_root,
        contract_id="c1",
        repository_root=repository_root,
        language="python",
        confidence=0.0,
        token_estimate=TokenEstimate(
            raw_context_tokens=0, selected_context_tokens=0, compression_ratio=0.0
        ),
        resolution_reason="baseline: no target names",
    )


def _write_middleware_fixture(tmp_path: Path) -> None:
    (tmp_path / "middleware.py").write_text(
        '@app.middleware("http")\n'
        "async def log_requests(request, call_next):\n"
        "    return await process_request(call_next)\n"
    )
    (tmp_path / "processing.py").write_text(
        "async def process_request(call_next):\n    return call_next()\n"
    )
    (tmp_path / "unrelated.py").write_text("def totally_unconnected():\n    pass\n")


def test_no_op_when_query_matches_no_known_decorator(tmp_path: Path) -> None:
    _write_middleware_fixture(tmp_path)
    index = _build_index(tmp_path)
    baseline = _empty_result(str(tmp_path))
    orchestrator = MultiHopOrchestrator(index)

    result, report = orchestrator.enrich(baseline, "Explain how logging configuration works")

    assert result is baseline
    assert report.matched_decorator_names == ()
    assert report.hop1_proposed == 0
    assert report.hop2_new_files == ()


def test_hop1_finds_decorated_symbol_and_hop2_chains_into_its_call_graph(
    tmp_path: Path,
) -> None:
    """The core multi-hop scenario this spike exists to prove out: a
    decorator match (hop 1, LSE) whose survivor seeds existing call-graph
    expansion (hop 2, unchanged ARCF machinery) — chaining across two
    different relationship types in one traversal, which nothing in ARCF
    could do before this orchestrator."""
    _write_middleware_fixture(tmp_path)
    index = _build_index(tmp_path)
    baseline = _empty_result(str(tmp_path))
    orchestrator = MultiHopOrchestrator(index)

    result, report = orchestrator.enrich(
        baseline, "Explain the middleware pipeline and what happens during request processing."
    )

    file_paths = {f.file_path for f in result.candidate_files}
    assert "middleware.py" in file_paths, "hop 1 (decorator match) must find the registration"
    assert "processing.py" in file_paths, "hop 2 (call-graph chain) must find what it calls"
    assert "unrelated.py" not in file_paths, "the unconnected file must never enter the chain"

    assert report.matched_decorator_names == ("app.middleware",)
    assert report.hop1_proposed == 1
    assert report.hop1_pruned == ()
    assert "processing.py" in report.hop2_new_files

    middleware_ref = next(f for f in result.candidate_files if f.file_path == "middleware.py")
    assert middleware_ref.evidence_tier is EvidenceTier.EXPERIMENTAL
    # processing.py is hop 2's OWN call-graph-fan-out discovery — it gets
    # ContextResolver's standard SUPPORTING tag (hop-expansion is always
    # SUPPORTING regardless of entry_point_tier, unchanged from before
    # this spike), not EXPERIMENTAL. LSE attribution for it is tracked
    # via report.hop2_new_files instead, not the tier on the file itself.
    processing_ref = next(f for f in result.candidate_files if f.file_path == "processing.py")
    assert processing_ref.evidence_tier is EvidenceTier.SUPPORTING


def test_baseline_candidates_are_never_touched(tmp_path: Path) -> None:
    _write_middleware_fixture(tmp_path)
    index = _build_index(tmp_path)
    baseline_with_primary = _empty_result(str(tmp_path)).model_copy(
        update={
            "candidate_files": [
                FileReference(
                    file_path="unrelated.py",
                    reason="defines totally_unconnected",
                    language="python",
                    token_count=5,
                    evidence_tier=EvidenceTier.PRIMARY,
                )
            ]
        }
    )
    orchestrator = MultiHopOrchestrator(index)

    result, _ = orchestrator.enrich(
        baseline_with_primary, "Explain the middleware pipeline during request processing."
    )

    primary_ref = next(f for f in result.candidate_files if f.file_path == "unrelated.py")
    assert primary_ref.evidence_tier is EvidenceTier.PRIMARY
    assert primary_ref.reason == "defines totally_unconnected"


def test_ambiguity_cap_bounds_a_widely_used_decorator_before_hop2(tmp_path: Path) -> None:
    """This is the real safety net for this integration, worth being
    explicit about: a decorator match's `reason` string always contains
    the decorator name that made it match the query in the first place
    (see multi_hop_orchestrator.py's own docstring), so
    prune_experimental_candidates' lexical-relevance check is close to a
    no-op for THIS relationship type specifically — corroboration/
    relevance alone won't stop a widely-used decorator from surviving.
    The ambiguity cap (max_survivors, default 8) is what actually bounds
    it: exactly the FastAPI Depends/FastAPI scenario (one relationship
    hit by dozens of unrelated files) reproduced at small scale, proving
    the chain stays bounded instead of fanning every match into hop 2."""
    for i in range(10):
        directory = tmp_path / f"module_{i:02d}"
        directory.mkdir()
        (directory / "handler.py").write_text(
            f'@app.middleware("http")\ndef handler_{i}(request):\n    pass\n'
        )
    index = _build_index(tmp_path)
    baseline = _empty_result(str(tmp_path))
    orchestrator = MultiHopOrchestrator(index)

    result, report = orchestrator.enrich(baseline, "Explain the middleware pipeline.")

    assert report.matched_decorator_names == ("app.middleware",)
    assert report.hop1_proposed == 10
    assert len(report.hop1_pruned) == 2  # 10 proposed, default max_survivors=8

    experimental_files = [
        f for f in result.candidate_files if f.evidence_tier is EvidenceTier.EXPERIMENTAL
    ]
    assert len(experimental_files) == 8
