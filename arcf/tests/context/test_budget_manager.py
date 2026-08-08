from pathlib import Path

from context.budget_manager import ContextBudgetManager
from context.compressor import SymbolRangeCompressor
from context.relevance_ranker import RankedFile
from domain.code_intelligence import SymbolKind
from domain.context_resolution import (
    ContextResolutionResult,
    EvidenceTier,
    SymbolReference,
    TokenEstimate,
)
from infrastructure.cost import CostEstimator
from workspace.permissions import PermissionManager


def _ranked(
    file_path: str,
    token_count: int,
    score: float = 0.9,
    evidence_tier: EvidenceTier = EvidenceTier.PRIMARY,
) -> RankedFile:
    return RankedFile(
        file_path=file_path,
        relevance_score=score,
        reason="defines foo",
        language="python",
        token_count=token_count,
        evidence_tier=evidence_tier,
    )


def _symbol(file_path: str, start: int, end: int) -> SymbolReference:
    return SymbolReference(
        symbol_id=f"{file_path}::foo",
        name="foo",
        qualified_name="foo",
        kind=SymbolKind.FUNCTION,
        file_path=file_path,
        start_line=start,
        end_line=end,
    )


def _empty_result(entry_points: list[SymbolReference] | None = None) -> ContextResolutionResult:
    return ContextResolutionResult(
        workspace_id="ws",
        contract_id="c1",
        repository_root="/repo",
        language="python",
        entry_points=entry_points or [],
        confidence=1.0,
        token_estimate=TokenEstimate(
            raw_context_tokens=0, selected_context_tokens=0, compression_ratio=0.0
        ),
        resolution_reason="test",
    )


def _manager(tmp_path: Path) -> ContextBudgetManager:
    permissions = PermissionManager(tmp_path)
    return ContextBudgetManager(permissions, CostEstimator(), SymbolRangeCompressor(permissions))


def test_includes_files_that_fit_in_full(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=10)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=1000)

    assert len(packaged) == 1
    assert packaged[0].truncated is False
    assert used == 10
    assert excluded == 0


def test_compresses_file_that_does_not_fit_in_full(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("\n".join(f"line {i}" for i in range(1, 200)) + "\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=100_000)]  # far larger than the real file's tokens
    result = _empty_result(entry_points=[_symbol("a.py", 50, 52)])

    packaged, used, excluded = manager.select(ranked, result, max_tokens=200)

    assert len(packaged) == 1
    assert packaged[0].truncated is True
    assert "line 50" in packaged[0].content
    assert excluded == 0


def test_excludes_file_with_no_symbols_when_it_does_not_fit(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=100_000)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=200)

    assert packaged == []
    assert used == 0
    assert excluded == 1


def test_stops_once_budget_exhausted(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a(): pass\n")
    (tmp_path / "b.py").write_text("def b(): pass\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=10), _ranked("b.py", token_count=10)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=10)

    assert [p.file_path for p in packaged] == ["a.py"]
    assert excluded == 1


def test_compressed_excerpt_includes_a_constructor_symbol_added_by_context_resolver(
    tmp_path: Path,
) -> None:
    # Mirrors what ContextResolver._enrich_with_constructors now does: the
    # constructor symbol (near the top of the file) rides along in
    # impacted_symbols alongside the selected method far below it — the
    # compressor should pick up both ranges, proving the excerpt isn't
    # severed from its class's initialization context.
    lines = ["class AuthService:", "    def __init__(self, db):", "        self.db = db", ""]
    lines += [f"    # padding {i}" for i in range(1, 60)]
    lines += ["    def authenticate(self, user):", "        return self.db.check(user)"]
    (tmp_path / "service.py").write_text("\n".join(lines) + "\n")

    manager = _manager(tmp_path)
    ranked = [_ranked("service.py", token_count=100_000)]
    method_symbol = SymbolReference(
        symbol_id="service.py::authenticate",
        name="authenticate",
        qualified_name="AuthService.authenticate",
        kind=SymbolKind.METHOD,
        file_path="service.py",
        start_line=len(lines) - 1,
        end_line=len(lines),
        parent_symbol_id="service.py::AuthService",
    )
    constructor_symbol = SymbolReference(
        symbol_id="service.py::__init__",
        name="__init__",
        qualified_name="AuthService.__init__",
        kind=SymbolKind.METHOD,
        file_path="service.py",
        start_line=2,
        end_line=3,
        parent_symbol_id="service.py::AuthService",
    )
    result = _empty_result(entry_points=[method_symbol]).model_copy(
        update={"impacted_symbols": [constructor_symbol]}
    )

    packaged, _, _ = manager.select(ranked, result, max_tokens=1000)

    assert len(packaged) == 1
    assert packaged[0].truncated is True
    assert "def __init__" in packaged[0].content
    assert "def authenticate" in packaged[0].content


def test_deleted_file_between_resolution_and_packaging_is_excluded_not_fatal(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    ranked = [_ranked("gone.py", token_count=10)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=1000)

    assert packaged == []
    assert used == 0
    assert excluded == 1


def _big_file_with_symbol_near_line(tmp_path: Path, name: str, symbol_line: int) -> Path:
    # Mirrors the real FastAPI regression: a huge central file where the
    # matched symbol is one small part of it (routing.py: 49K tokens
    # total, request_response defined a few hundred lines in).
    lines = [f"# padding {i}" for i in range(1, symbol_line - 1)]
    lines += ["def request_response():", "    pass"]
    lines += [f"# padding {i}" for i in range(symbol_line + 2, symbol_line + 2000)]
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n")
    return path


def test_supporting_evidence_is_compressed_even_though_it_would_fit_in_full(
    tmp_path: Path,
) -> None:
    """Evidence-preserving context packaging, core case: a SUPPORTING file
    (e.g. reached via lexical-probe recovery or call-graph expansion) with
    a known symbol location gets compressed to that symbol's range even
    when the full file would easily fit the remaining budget — a fan-out
    match shouldn't spend the same budget as the thing actually being
    asked about just because it happens to live in a large file."""
    _big_file_with_symbol_near_line(tmp_path, "routing.py", symbol_line=500)
    manager = _manager(tmp_path)
    symbol = SymbolReference(
        symbol_id="routing.py::request_response",
        name="request_response",
        qualified_name="request_response",
        kind=SymbolKind.FUNCTION,
        file_path="routing.py",
        start_line=500,
        end_line=501,
    )
    # token_count reflects the real (large) file — plenty of budget room.
    ranked = [_ranked("routing.py", token_count=15_000, evidence_tier=EvidenceTier.SUPPORTING)]
    result = _empty_result(entry_points=[symbol])

    packaged, used, excluded = manager.select(ranked, result, max_tokens=100_000)

    assert len(packaged) == 1
    assert packaged[0].truncated is True
    assert "def request_response" in packaged[0].content
    assert "padding 1\n" in packaged[0].content or packaged[0].content.startswith("# lines")
    assert used < 15_000, "compressed excerpt must be far smaller than the full file"
    assert excluded == 0


def test_primary_evidence_stays_full_even_with_a_known_symbol_location(tmp_path: Path) -> None:
    """The flip side of the case above: PRIMARY evidence (a confident
    direct match) keeps today's full-file-if-it-fits behavior even though
    it also has a symbol location that COULD be compressed — tiering must
    only change SUPPORTING files' treatment, never PRIMARY's."""
    _big_file_with_symbol_near_line(tmp_path, "background.py", symbol_line=5)
    manager = _manager(tmp_path)
    symbol = SymbolReference(
        symbol_id="background.py::BackgroundTasks",
        name="BackgroundTasks",
        qualified_name="BackgroundTasks",
        kind=SymbolKind.CLASS,
        file_path="background.py",
        start_line=5,
        end_line=6,
    )
    ranked = [_ranked("background.py", token_count=100, evidence_tier=EvidenceTier.PRIMARY)]
    result = _empty_result(entry_points=[symbol])

    packaged, used, excluded = manager.select(ranked, result, max_tokens=100_000)

    assert len(packaged) == 1
    assert packaged[0].truncated is False
    assert used == 100
    assert excluded == 0


def test_supporting_evidence_with_no_symbol_location_falls_back_to_full_file(
    tmp_path: Path,
) -> None:
    """A SUPPORTING file with no associated symbol (e.g. a glob-matched
    "evidence: <category>" file like README.md or pyproject.toml — there
    is no symbol location to extract a range *around*) has nothing to
    compress against, so it keeps the plain full-if-it-fits behavior
    rather than being excluded for lack of a compressible region."""
    (tmp_path / "README.md").write_text("# Demo\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("README.md", token_count=10, evidence_tier=EvidenceTier.SUPPORTING)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=1000)

    assert len(packaged) == 1
    assert packaged[0].truncated is False
    assert used == 10
    assert excluded == 0


def test_fastapi_style_scenario_keeps_small_primary_file_and_shrinks_large_supporting_one(
    tmp_path: Path,
) -> None:
    """End-to-end regression for the real FastAPI finding: a tiny file
    that actually answers the question (PRIMARY, background.py-style)
    plus a huge file only reached because a loosely-matched symbol lives
    there (SUPPORTING, routing.py-style). Success criteria (per the
    evidence-preserving packaging design): both files are retained, the
    real answer file stays intact, and the large supporting file is cut
    down to its relevant region instead of consuming the whole budget."""
    _big_file_with_symbol_near_line(tmp_path, "routing.py", symbol_line=500)
    (tmp_path / "background.py").write_text(
        "class BackgroundTasks:\n    def add_task(self, func):\n        ...\n"
    )
    manager = _manager(tmp_path)

    routing_symbol = SymbolReference(
        symbol_id="routing.py::request_response",
        name="request_response",
        qualified_name="request_response",
        kind=SymbolKind.FUNCTION,
        file_path="routing.py",
        start_line=500,
        end_line=501,
    )
    background_symbol = SymbolReference(
        symbol_id="background.py::BackgroundTasks",
        name="BackgroundTasks",
        qualified_name="BackgroundTasks",
        kind=SymbolKind.CLASS,
        file_path="background.py",
        start_line=1,
        end_line=3,
    )
    ranked = [
        _ranked("routing.py", token_count=49_000, evidence_tier=EvidenceTier.SUPPORTING),
        _ranked("background.py", token_count=20, evidence_tier=EvidenceTier.PRIMARY),
    ]
    result = _empty_result(entry_points=[routing_symbol, background_symbol])

    packaged, used, excluded = manager.select(ranked, result, max_tokens=100_000)

    by_path = {p.file_path: p for p in packaged}
    assert set(by_path) == {"routing.py", "background.py"}
    assert by_path["background.py"].truncated is False
    assert "class BackgroundTasks" in by_path["background.py"].content
    assert by_path["routing.py"].truncated is True
    assert "def request_response" in by_path["routing.py"].content
    assert used < 49_000 + 20, "total tokens used must be far below the two files' full size"
    assert excluded == 0
