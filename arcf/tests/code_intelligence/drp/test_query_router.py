from pathlib import Path

from code_intelligence.drp.drp_index import DrpIndexBuilder
from code_intelligence.drp.query_router import route_query
from code_intelligence.drp.taxonomy import build_taxonomy
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
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
        "def watch_configuration():\n"
        "    return propagate_updates()\n\n"
        "def propagate_updates():\n"
        "    return True\n",
    )
    _write(
        tmp_path,
        "pkg/server/router.py",
        "from .configurationwatcher import watch_configuration\n\n"
        "def route_request():\n    return watch_configuration()\n",
    )
    _write(
        tmp_path,
        "pkg/provider/docker.py",
        '"""Discovers containers via the Docker API."""\n'
        "def discover_containers():\n    return []\n",
    )
    _write(
        tmp_path,
        "pkg/middleware/auth.py",
        '"""HTTP authentication middleware."""\ndef authenticate_request():\n    return True\n',
    )


def test_route_query_picks_the_subsystem_matching_the_query(tmp_path: Path) -> None:
    _traefik_like_fixture(tmp_path)
    index = _build_index(tmp_path)
    # threshold=2 forces this tiny fixture to split into per-directory
    # subsystems (pkg has 4 files total, over 2) so winning_subsystem is
    # meaningful to assert on, while pkg/server's own 2 files (configura
    # tionwatcher.py, router.py — no shared filename prefix) stay AT,
    # not over, the threshold, so they don't additionally trigger
    # filename-prefix splitting — a different, real mechanism (see
    # test_taxonomy.py) not what this test is about. The real default
    # threshold would correctly keep a repo this small as one subsystem.
    drp_index = DrpIndexBuilder.build(index, tmp_path, max_files_per_subsystem=2)

    routing = route_query(
        "Explain how dynamic configuration updates propagate without restarting the server.",
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )

    assert routing.winning_subsystem == "pkg/server"
    assert "pkg/server/configurationwatcher.py" in routing.entry_files


def test_route_query_expands_via_import_graph_within_subsystem(tmp_path: Path) -> None:
    _traefik_like_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path)

    routing = route_query(
        "Explain how dynamic configuration updates propagate without restarting the server.",
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
        traversal_depth=2,
    )

    # router.py imports configurationwatcher.py and lives in the same
    # subsystem — it should be reachable via expansion even if it isn't
    # itself a ranked entry file.
    assert (
        "pkg/server/router.py" in routing.entry_files
        or "pkg/server/router.py" in routing.expansion
    )


def test_route_query_never_expands_outside_the_winning_subsystem(tmp_path: Path) -> None:
    _traefik_like_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path)

    routing = route_query(
        "Explain how dynamic configuration updates propagate without restarting the server.",
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )

    assert "pkg/provider/docker.py" not in routing.expansion
    assert "pkg/middleware/auth.py" not in routing.expansion


def test_route_query_is_deterministic(tmp_path: Path) -> None:
    _traefik_like_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path)
    query = "Explain how dynamic configuration updates propagate without restarting the server."

    first = route_query(
        query,
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )
    second = route_query(
        query,
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )

    assert first.winning_subsystem == second.winning_subsystem
    assert first.entry_files == second.entry_files
    assert first.expansion == second.expansion


def _near_tie_fixture(tmp_path: Path) -> None:
    # sub_a and sub_b each define an almost-identically-worded function,
    # each called from within its own subsystem (so usage-confidence
    # dampening doesn't zero both out) — verified directly (not assumed)
    # to land within _NEAR_TIE_MARGIN of each other. sub_c is entirely
    # unrelated and should never qualify regardless.
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
    _write(
        tmp_path,
        "sub_c/unrelated.py",
        '"""Formats terminal output colors."""\ndef colorize():\n    return None\n',
    )


def test_near_tied_runner_up_gets_its_own_entry_files(tmp_path: Path) -> None:
    _near_tie_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path, max_files_per_subsystem=2)

    routing = route_query(
        "How does the system register a new service instance in the catalog?",
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )

    assert routing.winning_subsystem in ("sub_a", "sub_b")
    runner_up = "sub_b" if routing.winning_subsystem == "sub_a" else "sub_a"
    assert runner_up in routing.near_tied_subsystems
    assert routing.near_tied_entry_files[runner_up]


def test_near_tie_never_includes_a_clearly_unrelated_subsystem(tmp_path: Path) -> None:
    _near_tie_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path, max_files_per_subsystem=2)

    routing = route_query(
        "How does the system register a new service instance in the catalog?",
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )

    assert "sub_c" not in routing.near_tied_subsystems
    assert routing.winning_subsystem != "sub_c"


def test_near_tie_is_deterministic(tmp_path: Path) -> None:
    _near_tie_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path, max_files_per_subsystem=2)
    query = "How does the system register a new service instance in the catalog?"

    first = route_query(
        query,
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )
    second = route_query(
        query,
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )

    assert first.near_tied_subsystems == second.near_tied_subsystems
    assert first.near_tied_entry_files == second.near_tied_entry_files


def test_margin_confidence_is_low_for_a_genuine_near_tie(tmp_path: Path) -> None:
    # winning_confidence and near_tied_subsystems are two views of the
    # same winner/runner-up margin (see query_router._margin_confidence's
    # own docstring) — a near-tie must report LOW confidence, not the
    # old total-score-share formula's disconnected number.
    _near_tie_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path, max_files_per_subsystem=2)

    routing = route_query(
        "How does the system register a new service instance in the catalog?",
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )

    assert routing.near_tied_subsystems  # sanity: this really is a near-tie
    assert routing.winning_confidence < 0.05


def test_margin_confidence_is_high_for_a_decisive_win(tmp_path: Path) -> None:
    # pkg/server is the only subsystem with any real lexical overlap with
    # this query (pkg/provider and pkg/middleware are about unrelated
    # topics) — a clean, one-sided win should report high confidence,
    # not a number diluted by how many unrelated subsystems also exist.
    _traefik_like_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path, max_files_per_subsystem=2)

    routing = route_query(
        "Explain how dynamic configuration updates propagate without restarting the server.",
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )

    assert not routing.near_tied_subsystems
    assert routing.winning_confidence > 0.5


def test_margin_confidence_is_zero_when_every_subsystem_scores_zero(tmp_path: Path) -> None:
    _traefik_like_fixture(tmp_path)
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path, max_files_per_subsystem=2)

    routing = route_query(
        "zzz qqq xyzabc nonexistent gibberish terms",
        drp_index.taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )

    assert routing.winning_confidence == 0.0


def test_empty_taxonomy_yields_empty_routing(tmp_path: Path) -> None:
    index = _build_index(tmp_path)
    taxonomy = build_taxonomy(index)
    drp_index = DrpIndexBuilder.build(index, tmp_path)

    routing = route_query(
        "anything",
        taxonomy,
        drp_index.file_tfidf,
        drp_index.file_to_units,
        drp_index.subsystem_graph,
        index,
    )

    assert routing.entry_files == []
