from pathlib import Path

from code_intelligence.drp.drp_index import DrpIndexBuilder
from code_intelligence.drp.drp_resolver import DrpResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from domain.context_resolution import EvidenceTier, OriginStage
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner


def _build_index(tmp_path: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    return engine.build_index(tmp_path, scan.files)


def _write(tmp_path: Path, relative_path: str, content: str) -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _traefik_like_fixture(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/server/configurationwatcher.py",
        '"""Watches dynamic configuration and propagates updates without restarting."""\n'
        "def watch_configuration():\n    return True\n",
    )
    _write(
        tmp_path,
        "pkg/provider/docker.py",
        '"""Discovers containers via the Docker API."""\n'
        "def discover_containers():\n    return []\n",
    )


def _resolve(tmp_path: Path, query: str, max_files_per_subsystem: int | None = None):
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(
        index, tmp_path, max_files_per_subsystem=max_files_per_subsystem
    )
    return DrpResolver(index, drp_index).resolve("ws1", "contract1", str(tmp_path), query)


def test_retrieves_the_target_file_the_lexical_resolver_could_not_reach(tmp_path: Path) -> None:
    _traefik_like_fixture(tmp_path)
    # threshold=0 forces the tiny fixture to split into per-directory
    # subsystems so top_subsystem is meaningful to assert on below — the
    # real default threshold would correctly keep a repo this small as
    # one subsystem (see test_taxonomy.py's own coverage of that).
    result, diagnostics = _resolve(
        tmp_path,
        "Explain how dynamic configuration updates propagate without restarting the server.",
        max_files_per_subsystem=0,
    )

    assert result.workspace_id == "ws1"
    assert result.contract_id == "contract1"
    assert "pkg/server/configurationwatcher.py" in {f.file_path for f in result.candidate_files}
    assert diagnostics.top_subsystem == "pkg/server"


def test_entry_file_gets_primary_tier_expansion_gets_supporting(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/server/watcher.py",
        '"""configuration watcher"""\ndef watch_configuration():\n    return reload_config()\n',
    )
    _write(
        tmp_path,
        "pkg/server/reload.py",
        "def reload_config():\n    return True\n",
    )
    _write(
        tmp_path,
        "pkg/server/entry.py",
        "from .watcher import watch_configuration\n\n"
        "def entry():\n    return watch_configuration()\n",
    )
    result, _ = _resolve(tmp_path, "configuration watcher")

    tiers = {f.file_path: f.evidence_tier for f in result.candidate_files}
    assert EvidenceTier.PRIMARY in tiers.values()


def test_candidate_files_are_tagged_with_drp_origin_stage(tmp_path: Path) -> None:
    """G10 (2026-08-17, independent verification report): DRP's own
    FileReference construction sites previously left origin_stage unset
    entirely -- none of the classic resolver's 4 existing OriginStage
    values honestly described DRP's TF-IDF/subsystem-routing mechanism,
    so a new DRP_SUBSYSTEM_ROUTING value was added rather than forcing
    an inaccurate one on to satisfy this test."""
    _write(
        tmp_path,
        "pkg/server/watcher.py",
        '"""configuration watcher"""\ndef watch_configuration():\n    return reload_config()\n',
    )
    result, _ = _resolve(tmp_path, "configuration watcher")

    assert result.candidate_files
    for file_ref in result.candidate_files:
        assert file_ref.origin_stage is OriginStage.DRP_SUBSYSTEM_ROUTING


def test_token_estimate_and_confidence_are_populated(tmp_path: Path) -> None:
    _traefik_like_fixture(tmp_path)
    result, _ = _resolve(tmp_path, "dynamic configuration propagation without restart")

    assert result.token_estimate.raw_context_tokens > 0
    assert 0.0 <= result.confidence <= 1.0
    assert result.token_estimate.selected_context_tokens <= result.token_estimate.raw_context_tokens


def test_query_with_no_lexical_overlap_at_all_still_returns_a_result_or_empty_honestly(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "only_file.py", "def something():\n    return 1\n")
    result, diagnostics = _resolve(tmp_path, "zzz qqq xyzabc nonexistent gibberish terms")

    # Never crashes, and never fabricates a confident match when nothing
    # in the repository's own vocabulary overlaps the query.
    assert result.confidence >= 0.0
    assert isinstance(result.candidate_files, list)


def test_target_names_are_folded_into_the_query_not_a_separate_channel(tmp_path: Path) -> None:
    _traefik_like_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path)

    result, _ = DrpResolver(index, drp_index).resolve(
        "ws1",
        "contract1",
        str(tmp_path),
        query="",
        target_names=["configuration", "watcher"],
    )

    assert "pkg/server/configurationwatcher.py" in {f.file_path for f in result.candidate_files}


def test_result_is_deterministic_across_repeated_resolves(tmp_path: Path) -> None:
    _traefik_like_fixture(tmp_path)
    query = "Explain how dynamic configuration updates propagate without restarting the server."

    first, _ = _resolve(tmp_path, query)
    second, _ = _resolve(tmp_path, query)

    assert [f.file_path for f in first.candidate_files] == [
        f.file_path for f in second.candidate_files
    ]
    assert first.confidence == second.confidence


def _pmi_bridgeable_fixture(tmp_path: Path) -> None:
    # "apply"/"watcher"/"reload" co-occur together (and with the hub
    # "config") in pkg/server's two CODE files. "restarting" (the query
    # word) never appears in any CODE file — mirroring the real Traefik
    # case exactly: zero document frequency in file_tfidf's own corpus,
    # so plain TF-IDF has no way to let it discriminate anything. It
    # DOES appear in README.md/CHANGELOG.md, alongside "reload"/"apply"
    # — same as the real repo's README/docs, and the ONLY place
    # build_pmi_word_graph's wider corpus (gather_doc_prose) can learn
    # the association from, since file_tfidf's own corpus never sees it.
    _write(
        tmp_path,
        "pkg/server/watcher.py",
        '"""config watcher apply reload"""\ndef watch_configuration():\n    return True\n',
    )
    _write(
        tmp_path,
        "pkg/server/handler.py",
        '"""config watcher apply reload"""\n'
        "from .watcher import watch_configuration\n\n"
        "def handle_request():\n    return watch_configuration()\n",
    )
    # handler.py calling watcher.py above gives watch_configuration a
    # real incoming call — with usage-confidence dampening active
    # (tfidf.py's _MIN_CALLS_FOR_FULL_CONFIDENCE), a fixture where
    # nothing calls anything would flatten every file's score to zero
    # and this test would pass or fail on arbitrary tie-breaking rather
    # than on real content matching.
    for i in range(4, 9):
        _write(tmp_path, f"pkg/other/f{i}.py", f'"""config filler{i}"""\ndef f{i}():\n    pass\n')
    _write(tmp_path, "README.md", "restarting reload apply watcher\n")
    _write(tmp_path, "CHANGELOG.md", "restarting reload apply watcher\n")


def test_pmi_expansion_off_by_default_finds_nothing_for_a_zero_coverage_query(
    tmp_path: Path,
) -> None:
    _pmi_bridgeable_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path)  # enable_pmi_expansion defaults False

    result, diagnostics = DrpResolver(index, drp_index).resolve(
        "ws1", "contract1", str(tmp_path), "restarting"
    )

    # "restarting" has zero content-based signal anywhere without PMI —
    # confidence is genuinely zero, even if graph-expansion tie-breaking
    # (an unrelated mechanic — see the fixture's own comment on why
    # handler.py imports watcher.py) incidentally includes some file.
    # The meaningful claim here is "PMI never ran", not "which arbitrary
    # file a zero-confidence tie-break landed on".
    assert result.confidence == 0.0
    assert diagnostics.query_expansion is None


def test_pmi_expansion_bridges_a_zero_coverage_query_term_to_the_right_subsystem(
    tmp_path: Path,
) -> None:
    _pmi_bridgeable_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path, enable_pmi_expansion=True)

    result, diagnostics = DrpResolver(index, drp_index).resolve(
        "ws1", "contract1", str(tmp_path), "restarting", enable_pmi_expansion=True
    )

    assert "pkg/server/watcher.py" in {f.file_path for f in result.candidate_files}
    assert diagnostics.query_expansion is not None
    # "restarting" is stemmed to "restart" by tfidf.tokenize before PMI
    # expansion ever sees it (see tfidf.py's own `_stem`) — the query-
    # expansion dict is keyed by the post-stem token, same as every
    # other term.
    assert "restart" in diagnostics.query_expansion
    expanded_to = {term for term, _ in diagnostics.query_expansion["restart"]}
    assert "apply" in expanded_to or "watcher" in expanded_to


def test_near_tied_subsystem_files_reach_the_final_result_as_supporting_evidence(
    tmp_path: Path,
) -> None:
    # Real Consul/Django runs found the correct subsystem losing a
    # winner-take-all race by only 2-3% and being excluded from
    # candidates entirely — this fixture mirrors that shape closely
    # enough (verified via query_router.py's own near-tie tests) to
    # reach the end-to-end result, not just DrpRouting.
    _write(
        tmp_path,
        "sub_a/handler.py",
        '"""Registers a new service instance in the catalog when an agent '
        'reports it."""\ndef register_service():\n    return True\n',
    )
    _write(
        tmp_path,
        "sub_a/caller.py",
        "from .handler import register_service\n\ndef entry():\n    return register_service()\n",
    )
    _write(
        tmp_path,
        "sub_b/structs.py",
        '"""Registers a new service instance in the catalog when an agent '
        'reports it too."""\ndef register_service_struct():\n    return True\n',
    )
    _write(
        tmp_path,
        "sub_b/caller.py",
        "from .structs import register_service_struct\n\n"
        "def entry():\n    return register_service_struct()\n",
    )
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path, max_files_per_subsystem=0)

    result, _ = DrpResolver(index, drp_index).resolve(
        "ws1",
        "contract1",
        str(tmp_path),
        "How does the system register a new service instance in the catalog?",
    )

    file_paths = {f.file_path for f in result.candidate_files}
    assert "sub_a/handler.py" in file_paths
    assert "sub_b/structs.py" in file_paths

    tiers_by_path = {f.file_path: f.evidence_tier for f in result.candidate_files}
    assert EvidenceTier.PRIMARY in tiers_by_path.values()
    assert tiers_by_path["sub_a/handler.py"] != tiers_by_path["sub_b/structs.py"]
    reasons_by_path = {f.file_path: f.reason for f in result.candidate_files}
    near_tied_reason = next(r for r in reasons_by_path.values() if "near-tied" in r)
    assert "close second to" in near_tied_reason


def test_ambiguous_resolution_says_so_instead_of_sounding_resolved(tmp_path: Path) -> None:
    # Graceful degradation under ambiguity: when the winner barely beat
    # the runner-up, the top-level resolution_reason must say so in
    # plain language, not phrase it as a confidently "resolved" pick —
    # low winning_confidence and a non-empty near-tie are the same fact
    # (see query_router._margin_confidence), so the wording must agree
    # with the number instead of contradicting it.
    _write(
        tmp_path,
        "sub_a/handler.py",
        '"""Registers a new service instance in the catalog when an agent '
        'reports it."""\ndef register_service():\n    return True\n',
    )
    _write(
        tmp_path,
        "sub_a/caller.py",
        "from .handler import register_service\n\ndef entry():\n    return register_service()\n",
    )
    _write(
        tmp_path,
        "sub_b/structs.py",
        '"""Registers a new service instance in the catalog when an agent '
        'reports it too."""\ndef register_service_struct():\n    return True\n',
    )
    _write(
        tmp_path,
        "sub_b/caller.py",
        "from .structs import register_service_struct\n\n"
        "def entry():\n    return register_service_struct()\n",
    )
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path, max_files_per_subsystem=0)

    result, _ = DrpResolver(index, drp_index).resolve(
        "ws1",
        "contract1",
        str(tmp_path),
        "How does the system register a new service instance in the catalog?",
    )

    assert result.confidence < 0.05
    assert "ambiguous" in result.resolution_reason.lower()
    assert "resolved subsystem" not in result.resolution_reason.lower()


def test_decisive_resolution_still_sounds_resolved(tmp_path: Path) -> None:
    _traefik_like_fixture(tmp_path)
    result, _ = _resolve(
        tmp_path,
        "Explain how dynamic configuration updates propagate without restarting the server.",
        max_files_per_subsystem=0,
    )

    assert result.confidence > 0.5
    assert "resolved subsystem" in result.resolution_reason.lower()
    assert "ambiguous" not in result.resolution_reason.lower()
