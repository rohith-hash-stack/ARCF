from pathlib import Path

from context.budget_manager import ContextBudgetManager
from context.compressor import SymbolRangeCompressor
from context.relevance_ranker import RankedFile
from context.task_profile import RetrievalTaskType
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
    justification_chain: tuple[str, ...] = (),
) -> RankedFile:
    return RankedFile(
        file_path=file_path,
        relevance_score=score,
        reason="defines foo",
        language="python",
        token_count=token_count,
        evidence_tier=evidence_tier,
        justification_chain=justification_chain,
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


def _boilerplate_ranked(file_path: str, token_count: int, category: str) -> RankedFile:
    return RankedFile(
        file_path=file_path,
        relevance_score=0.5,
        reason=f"evidence: {category}",
        language="yaml",
        token_count=token_count,
        evidence_tier=EvidenceTier.SUPPORTING,
    )


def test_boilerplate_evidence_category_is_head_truncated_not_kept_full(tmp_path: Path) -> None:
    """arcf-repo-sweep-50 cost investigation (scripts/
    context_budget_filler_diagnosis.py): a large CI-workflow file has no
    symbol location, so the symbol-anchored compression trigger can't
    touch it — before this fix it fell all the way through to
    full-if-fits, which is how 3 of 12 real sweep queries ended up
    96-100% boilerplate by packaged token count. 'CI/workflow files' is
    in `_BOILERPLATE_EVIDENCE_CATEGORIES`, so it must now be truncated
    to the small cap regardless of how much budget remains."""
    (tmp_path / "build.yml").write_text("name: CI\n" + ("  - run: echo noop\n" * 2000))
    manager = _manager(tmp_path)
    ranked = [_boilerplate_ranked("build.yml", token_count=6393, category="CI/workflow files")]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=100_000)

    assert len(packaged) == 1
    assert packaged[0].truncated is True
    assert used < 200, "boilerplate should be capped near _BOILERPLATE_FILLER_MAX_TOKENS, not kept full"
    assert excluded == 0


def test_readme_category_is_explicitly_exempt_from_boilerplate_truncation(tmp_path: Path) -> None:
    """The same diagnosis (see this file's other boilerplate test) found
    a real case — gvisor, 'Explain how gVisor separates application
    syscalls from the host kernel' — where 'project structure' (README)
    content was the actual grounding for a correct answer. Truncating
    every no-symbol SUPPORTING file indiscriminately would have risked
    that case, so 'project structure' must stay OUT of
    `_BOILERPLATE_EVIDENCE_CATEGORIES` and keep the plain
    full-if-it-fits behavior, same as before this fix existed."""
    (tmp_path / "README.md").write_text("# Architecture\n" + ("Real explanatory prose. " * 400))
    manager = _manager(tmp_path)
    ranked = [_boilerplate_ranked("README.md", token_count=2000, category="project structure")]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=100_000)

    assert len(packaged) == 1
    assert packaged[0].truncated is False
    assert used == 2000
    assert excluded == 0


def test_boilerplate_truncation_frees_budget_for_other_files(tmp_path: Path) -> None:
    """Functional proof the recovered budget actually gets used: without
    truncation a single large CI file would exhaust a small budget and
    exclude everything ranked after it; with truncation, a real file
    ranked second now fits too."""
    (tmp_path / "build.yml").write_text("name: CI\n" + ("  - run: echo noop\n" * 2000))
    (tmp_path / "real.py").write_text("def handles_auth():\n    return True\n")
    manager = _manager(tmp_path)
    ranked = [
        _boilerplate_ranked("build.yml", token_count=6393, category="CI/workflow files"),
        _ranked("real.py", token_count=200, score=0.8),
    ]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=6500)

    assert {p.file_path for p in packaged} == {"build.yml", "real.py"}
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


def test_falloff_gate_excludes_candidate_below_gamma_of_top_score(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    (tmp_path / "b.py").write_text("def bar():\n    pass\n")
    manager = _manager(tmp_path)
    # 0.4 < 0.45 * 1.0, so b.py should be pruned even though plenty of
    # budget remains.
    ranked = [_ranked("a.py", token_count=10, score=1.0), _ranked("b.py", token_count=10, score=0.4)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=10_000)

    assert {p.file_path for p in packaged} == {"a.py"}
    assert excluded == 1


def test_falloff_gate_keeps_candidate_at_or_above_gamma_of_top_score(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    (tmp_path / "b.py").write_text("def bar():\n    pass\n")
    manager = _manager(tmp_path)
    # 0.45 == 0.45 * 1.0 exactly -- the gate is >=, not >, so this stays.
    ranked = [_ranked("a.py", token_count=10, score=1.0), _ranked("b.py", token_count=10, score=0.45)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=10_000)

    assert {p.file_path for p in packaged} == {"a.py", "b.py"}


def test_falloff_gate_halts_rather_than_skips_once_triggered(tmp_path: Path) -> None:
    # A pathological case where a LATER candidate would individually still
    # clear the threshold on its own score, but the gate halts at the
    # first failure rather than resuming -- ranked_files being sorted
    # descending means this shouldn't occur from real RelevanceRanker
    # output, but the halt behavior itself (not a per-item skip) is the
    # documented contract and must hold regardless of input order.
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    (tmp_path / "b.py").write_text("def mid():\n    pass\n")
    (tmp_path / "c.py").write_text("def bar():\n    pass\n")
    manager = _manager(tmp_path)
    ranked = [
        _ranked("a.py", token_count=10, score=1.0),
        _ranked("b.py", token_count=10, score=0.1),
        _ranked("c.py", token_count=10, score=0.9),
    ]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=10_000)

    assert {p.file_path for p in packaged} == {"a.py"}
    assert excluded == 2


def test_supporting_evidence_compression_uses_ast_scope_not_plain_margin(
    tmp_path: Path,
) -> None:
    # Feature C wiring: SUPPORTING ("secondary") candidates route through
    # extract_with_ast_scope, not the plain extract() -- proven here by
    # two things plain extract() (margin_lines=2 default) could never
    # produce: the leading import header riding along, and a margin wide
    # enough to be 5 (not 2) lines around the symbol.
    lines = ["import os", "from pkg import thing", ""]
    lines += [f"line {i}" for i in range(4, 300)]
    (tmp_path / "routing.py").write_text("\n".join(lines) + "\n")
    manager = _manager(tmp_path)
    symbol = SymbolReference(
        symbol_id="routing.py::handler",
        name="handler",
        qualified_name="handler",
        kind=SymbolKind.FUNCTION,
        file_path="routing.py",
        start_line=200,
        end_line=200,
    )
    ranked = [_ranked("routing.py", token_count=15_000, evidence_tier=EvidenceTier.SUPPORTING)]
    result = _empty_result(entry_points=[symbol])

    packaged, used, excluded = manager.select(ranked, result, max_tokens=100_000)

    assert len(packaged) == 1
    content = packaged[0].content
    assert "import os" in content
    assert "from pkg import thing" in content
    assert "line 195" in content  # 200 - 5, the AST-scope margin
    assert "line 198" in content  # would already be inside a plain-margin-2 range too
    assert excluded == 0


def test_primary_evidence_compression_still_uses_plain_extract(tmp_path: Path) -> None:
    # The doesn't-fit-in-full PRIMARY path is deliberately untouched by
    # Feature C -- same file/symbol shape as the SUPPORTING case above,
    # but PRIMARY, and forced to compress by a tight budget rather than
    # the evidence-tier trigger. No header should ride along, since plain
    # extract() only ever takes a margin around the symbol itself.
    lines = ["import os", "from pkg import thing", ""]
    lines += [f"line {i}" for i in range(4, 300)]
    (tmp_path / "routing.py").write_text("\n".join(lines) + "\n")
    manager = _manager(tmp_path)
    symbol = SymbolReference(
        symbol_id="routing.py::handler",
        name="handler",
        qualified_name="handler",
        kind=SymbolKind.FUNCTION,
        file_path="routing.py",
        start_line=200,
        end_line=200,
    )
    ranked = [_ranked("routing.py", token_count=100_000, evidence_tier=EvidenceTier.PRIMARY)]
    result = _empty_result(entry_points=[symbol])

    packaged, used, excluded = manager.select(ranked, result, max_tokens=200)

    assert len(packaged) == 1
    content = packaged[0].content
    assert "import os" not in content
    assert "line 200" in content


def _fn_symbol(file_path: str, name: str, start: int, end: int) -> SymbolReference:
    return SymbolReference(
        symbol_id=f"{file_path}::{name}",
        name=name,
        qualified_name=name,
        kind=SymbolKind.FUNCTION,
        file_path=file_path,
        start_line=start,
        end_line=end,
    )


def test_focal_supporting_candidate_keeps_full_body(tmp_path: Path) -> None:
    (tmp_path / "focal.py").write_text(
        "def handler():\n    do_real_work()\n    return 1\n"
    )
    manager = _manager(tmp_path)
    ranked = [_ranked("focal.py", token_count=10, score=0.9, evidence_tier=EvidenceTier.SUPPORTING)]
    result = _empty_result(entry_points=[_fn_symbol("focal.py", "handler", 1, 3)])

    packaged, used, excluded = manager.select(ranked, result, max_tokens=10_000)

    assert "do_real_work" in packaged[0].content
    assert "implementation omitted" not in packaged[0].content


def test_second_supporting_candidate_gets_skeleton_only(tmp_path: Path) -> None:
    (tmp_path / "focal.py").write_text("def handler():\n    do_real_work()\n")
    (tmp_path / "secondary.py").write_text(
        "def helper():\n    unrelated_body_content()\n    return 2\n"
    )
    manager = _manager(tmp_path)
    ranked = [
        _ranked("focal.py", token_count=10, score=0.9, evidence_tier=EvidenceTier.SUPPORTING),
        _ranked("secondary.py", token_count=10, score=0.8, evidence_tier=EvidenceTier.SUPPORTING),
    ]
    result = _empty_result(
        entry_points=[
            _fn_symbol("focal.py", "handler", 1, 2),
            _fn_symbol("secondary.py", "helper", 1, 3),
        ]
    )

    packaged, used, excluded = manager.select(ranked, result, max_tokens=10_000)

    by_path = {p.file_path: p for p in packaged}
    assert "do_real_work" in by_path["focal.py"].content
    assert "unrelated_body_content" not in by_path["secondary.py"].content
    assert "implementation omitted" in by_path["secondary.py"].content


def test_hop_one_linked_secondary_candidate_keeps_full_body(tmp_path: Path) -> None:
    # Feature 2 safety fallback: a secondary candidate reached via a
    # direct (hop-1) call-graph edge is exempted from skeletonization.
    (tmp_path / "focal.py").write_text("def handler():\n    do_real_work()\n")
    (tmp_path / "linked.py").write_text(
        "def caller():\n    linked_body_content()\n    return 3\n"
    )
    manager = _manager(tmp_path)
    ranked = [
        _ranked("focal.py", token_count=10, score=0.9, evidence_tier=EvidenceTier.SUPPORTING),
        _ranked(
            "linked.py",
            token_count=10,
            score=0.8,
            evidence_tier=EvidenceTier.SUPPORTING,
            justification_chain=("defines handler", "called by caller"),
        ),
    ]
    result = _empty_result(
        entry_points=[
            _fn_symbol("focal.py", "handler", 1, 2),
            _fn_symbol("linked.py", "caller", 1, 3),
        ]
    )

    packaged, used, excluded = manager.select(ranked, result, max_tokens=10_000)

    by_path = {p.file_path: p for p in packaged}
    assert "linked_body_content" in by_path["linked.py"].content
    assert "implementation omitted" not in by_path["linked.py"].content


def test_falloff_gate_is_a_noop_for_a_single_candidate(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=10, score=0.05)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=10_000)

    assert {p.file_path for p in packaged} == {"a.py"}
    assert excluded == 0


def test_task_type_tightens_budget_ceiling(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=2000, score=0.9)]

    packaged, used, excluded = manager.select(
        ranked, _empty_result(), max_tokens=8000, task_type=RetrievalTaskType.REPOSITORY_EXPLANATION
    )

    # 2000 tokens is well under the plain 8000 ceiling but over the
    # 1200 lookup-tier ceiling -- must be excluded, not included.
    assert packaged == []
    assert excluded == 1


def test_task_type_never_raises_the_ceiling_above_max_tokens(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=2000, score=0.9)]

    # A caller-set 1000-token ceiling is TIGHTER than the 4500
    # cross-module tier -- task_type must never loosen it.
    packaged, used, excluded = manager.select(
        ranked, _empty_result(), max_tokens=1000, task_type=RetrievalTaskType.ARCHITECTURE_UNDERSTANDING
    )

    assert packaged == []
    assert excluded == 1


def test_task_type_none_leaves_max_tokens_unchanged(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=2000, score=0.9)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=8000)

    assert {p.file_path for p in packaged} == {"a.py"}
    assert excluded == 0


def test_unknown_and_bug_fix_task_types_use_the_cross_module_tier(tmp_path: Path) -> None:
    # Moved from the 2500 (logic) tier to 4500 (cross-module) after real
    # Consul measurement showed a real query's grounding quality costed
    # by the tighter cap -- see _BUDGET_TIER_BY_TASK_TYPE's own comment.
    # 3500 proves this: it clears 2500 (the old tier) but not the plain
    # 8000 max_tokens, so passing means the CURRENT (4500) tier is what's
    # actually in effect, not the old one or no cap at all.
    (tmp_path / "unknown.py").write_text("x = 1\n")
    (tmp_path / "bugfix.py").write_text("x = 1\n")
    manager = _manager(tmp_path)

    for task_type, file_path in (
        (RetrievalTaskType.UNKNOWN, "unknown.py"),
        (RetrievalTaskType.BUG_FIX, "bugfix.py"),
    ):
        ranked = [_ranked(file_path, token_count=3500, score=0.9)]
        packaged, used, excluded = manager.select(
            ranked, _empty_result(), max_tokens=8000, task_type=task_type
        )
        assert {p.file_path for p in packaged} == {file_path}
        assert excluded == 0
