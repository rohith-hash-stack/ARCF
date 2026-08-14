"""ARCF-DI Phase 9 — the determinism/validation benchmark suite
BLUEPRINT.md calls for, consolidated here rather than re-scattered:
most of its test classes already exist, one per phase that introduced
the property they check (Phase 1's id-reproducibility test, Phase 2's
classification-byte-identity test, Phase 3's resolver ablation, Phase
4/5/6/7/8's own same-process reproducibility checks). This file adds
what was genuinely missing — checks that only make sense once multiple
phases are combined, not any single phase's own isolated unit test:

- Reproducibility across runs, but at the INTEGRATION level: the full
  Phase 3->4->5 chain (resolve, build records, summarize) run twice,
  independently, byte-identical output — not just one phase's own
  output in isolation.
- Ambiguity handling traced end-to-end: a real name collision (the
  documented `New()`-collision shape) survives all the way from
  CallGraph resolution through BehavioralRecord.ambiguous_calls into
  the final summary, never silently lost at any hop.
- Citation integrity as a general invariant, not just specific
  accept/reject fixtures: for any record, every citation
  render_template ever produces is provably a member of that record's
  own citable_evidence_ids — checked across a range of records, not one
  hand-picked example.

See arcf-di/PROGRESS.md's Phase 9 entry for the full mapping from
BLUEPRINT.md's test-class list to the specific test(s) that satisfy
each one, including the ones that already existed before this file.
"""

import json

from code_intelligence.behavioral_record import BehavioralRecordBuilder
from code_intelligence.call_graph import CallGraph
from code_intelligence.integrity import verify_integrity
from code_intelligence.library_boundary import LibraryBoundaryClassifier
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.symbol_index import SymbolIndex
from context.evidence_summarizer import citable_evidence_ids, render_template
from domain.audit import AuditStamp, PersistedBehavioralRecord
from domain.behavioral_record import BehavioralRecord
from domain.code_intelligence import (
    CallReference,
    DeclaredDependency,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)
from infrastructure.behavioral_record_store import InMemoryBehavioralRecordStore


def _function(name: str, file_path: str) -> Symbol:
    return Symbol(
        id=f"{file_path}::{name}",
        name=name,
        qualified_name=name,
        kind=SymbolKind.FUNCTION,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=1, end_line=6),
    )


def _call(caller_id: str | None, callee_name: str, file_path: str) -> CallReference:
    return CallReference(
        caller_id=caller_id,
        callee_name=callee_name,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=3, end_line=3),
    )


def _build_pipeline(
    symbols: list[Symbol], calls: list[CallReference], file_analyses: dict[str, FileAnalysis]
) -> list[BehavioralRecord]:
    """Phases 3 (mandatory disambiguation) -> 4 (behavioral records),
    combined -- the same "small pipeline" shape a real indexing run
    would use, kept in-memory/no I/O so this suite runs fast."""
    symbol_index = SymbolIndex(symbols)
    resolver = ReferenceResolver(symbol_index)
    graph = CallGraph(calls, resolver, mandatory_disambiguation=True)
    builder = BehavioralRecordBuilder(symbol_index, graph, file_analyses)
    return builder.build_all()


def _fixture() -> tuple[list[Symbol], list[CallReference], dict[str, FileAnalysis]]:
    """A small multi-file "repo" combining: a clean resolvable call
    (login -> authenticate), a real name collision mirroring the
    documented New()-collision shape (tied_a/tied_b, no locality
    signal), and a classified external-library import."""
    login = _function("login", "service.py")
    authenticate = _function("authenticate", "auth.py")
    tied_a = _function("New", "pkg1/a.go")
    tied_b = _function("New", "pkg2/b.go")
    caller = _function("Run", "pkg3/main.go")

    symbols = [login, authenticate, tied_a, tied_b, caller]
    calls = [
        _call(login.id, "authenticate", "service.py"),
        _call(caller.id, "New", "pkg3/main.go"),
    ]

    requests_import = ImportReference(
        source_file="service.py",
        raw_module="requests",
        location=SourceLocation(file_path="service.py", start_line=1, end_line=1),
    )
    classifier = LibraryBoundaryClassifier(
        dependencies=[
            DeclaredDependency(
                name="requests",
                ecosystem="pip",
                manifest_location=SourceLocation(
                    file_path="requirements.txt", start_line=1, end_line=1
                ),
            )
        ]
    )
    [classified_import] = classifier.classify([requests_import], language="python")

    file_analyses = {
        "service.py": FileAnalysis(
            file_path="service.py", language="python", imports=[classified_import]
        ),
    }
    return symbols, calls, file_analyses


# --- Reproducibility across runs (integration level) ---------------------


def test_full_pipeline_byte_identical_across_independent_runs() -> None:
    symbols, calls, file_analyses = _fixture()

    first = _build_pipeline(symbols, calls, file_analyses)
    second = _build_pipeline(symbols, calls, file_analyses)

    first_json = json.dumps([r.model_dump(mode="json") for r in first], sort_keys=True)
    second_json = json.dumps([r.model_dump(mode="json") for r in second], sort_keys=True)
    assert first_json == second_json


def test_full_pipeline_including_summaries_byte_identical() -> None:
    symbols, calls, file_analyses = _fixture()

    def _summaries_json() -> str:
        records = _build_pipeline(symbols, calls, file_analyses)
        summaries = [render_template(r) for r in records]
        return json.dumps([s.model_dump(mode="json") for s in summaries], sort_keys=True)

    assert _summaries_json() == _summaries_json()


# --- Ambiguity handling, traced end-to-end --------------------------------


def test_ambiguous_call_survives_from_resolution_through_summary() -> None:
    symbols, calls, file_analyses = _fixture()
    records = _build_pipeline(symbols, calls, file_analyses)

    caller_record = next(r for r in records if r.symbol_id == "pkg3/main.go::Run")
    assert caller_record.disambiguation_aware is True
    assert len(caller_record.ambiguous_calls) == 1
    ambiguous = caller_record.ambiguous_calls[0]
    assert ambiguous.callee_name == "New"
    assert len(ambiguous.candidates) == 2

    summary = render_template(caller_record)
    # Never silently dropped: either the ambiguity is visible in the
    # summary's text+citations, or the record is honestly flagged
    # insufficient rather than pretending resolution succeeded cleanly.
    if not summary.insufficient_evidence:
        assert ambiguous.call_id in summary.citations
        assert "ambiguous" in summary.text.lower()


def test_clean_call_has_no_ambiguity_anywhere_in_the_chain() -> None:
    symbols, calls, file_analyses = _fixture()
    records = _build_pipeline(symbols, calls, file_analyses)

    login_record = next(r for r in records if r.symbol_id == "service.py::login")
    assert login_record.ambiguous_calls == []
    assert login_record.disambiguation_aware is True


# --- Citation integrity, as a general invariant ---------------------------


def test_every_template_citation_is_a_real_evidence_id_on_its_own_record() -> None:
    symbols, calls, file_analyses = _fixture()
    records = _build_pipeline(symbols, calls, file_analyses)

    checked = 0
    for record in records:
        summary = render_template(record)
        allowed = citable_evidence_ids(record)
        assert set(summary.citations) <= allowed
        checked += 1
    assert checked == len(records) > 0


# --- Library-boundary correctness (cross-phase: Phase 2 classification ---
# --- feeding Phase 4's external_libraries_used) ---------------------------


def test_classified_external_import_reaches_the_behavioral_record() -> None:
    symbols, calls, file_analyses = _fixture()
    records = _build_pipeline(symbols, calls, file_analyses)

    login_record = next(r for r in records if r.symbol_id == "service.py::login")
    assert login_record.external_libraries_used == ["requests"]


# --- Persistence + integrity, exercised together --------------------------


def test_persisted_records_pass_integrity_check_against_the_same_pipeline() -> None:
    symbols, calls, file_analyses = _fixture()
    symbol_index = SymbolIndex(symbols)
    resolver = ReferenceResolver(symbol_index)
    graph = CallGraph(calls, resolver, mandatory_disambiguation=True)
    builder = BehavioralRecordBuilder(symbol_index, graph, file_analyses)

    store = InMemoryBehavioralRecordStore()
    stamp = AuditStamp(commit_sha="c1", resolver_version="v1", schema_version="v1")
    symbol_ids = [s.id for s in symbols if s.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD)]
    for symbol_id in symbol_ids:
        record = builder.build(symbol_id)
        assert record is not None
        store.save(PersistedBehavioralRecord(stamp=stamp, record=record))

    report = verify_integrity(store, builder, "c1", symbol_ids)
    assert report.clean is True
    assert report.checked == len(symbol_ids)
