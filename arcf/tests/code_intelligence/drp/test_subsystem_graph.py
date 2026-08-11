from pathlib import Path

from code_intelligence.drp.subsystem_graph import build_subsystem_graph
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


def _write_two_cluster_fixture(tmp_path: Path) -> None:
    (tmp_path / "a1.py").write_text(
        "from .a2 import a2_func\n\ndef a1_func():\n    return a2_func()\n"
    )
    (tmp_path / "a2.py").write_text(
        "from .a3 import a3_func\n\ndef a2_func():\n    return a3_func()\n"
    )
    (tmp_path / "a3.py").write_text("def a3_func():\n    return True\n")

    (tmp_path / "b1.py").write_text(
        "from .b2 import b2_func\n\ndef b1_func():\n    return b2_func()\n"
    )
    (tmp_path / "b2.py").write_text(
        "from .b3 import b3_func\n\ndef b2_func():\n    return b3_func()\n"
    )
    (tmp_path / "b3.py").write_text("def b3_func():\n    return True\n")


def test_label_propagation_recovers_two_disconnected_clusters(tmp_path: Path) -> None:
    _write_two_cluster_fixture(tmp_path)
    index = _build_index(tmp_path)

    result = build_subsystem_graph(index)

    a_community = result.metrics["a1.py"].community_id
    b_community = result.metrics["b1.py"].community_id
    assert a_community != b_community
    assert result.metrics["a2.py"].community_id == a_community
    assert result.metrics["a3.py"].community_id == a_community
    assert result.metrics["b2.py"].community_id == b_community
    assert result.metrics["b3.py"].community_id == b_community


def test_isolated_file_becomes_its_own_singleton_community(tmp_path: Path) -> None:
    _write_two_cluster_fixture(tmp_path)
    (tmp_path / "isolated.py").write_text("def isolated():\n    return None\n")
    index = _build_index(tmp_path)

    result = build_subsystem_graph(index)

    assert result.communities[result.metrics["isolated.py"].community_id] == ["isolated.py"]
    assert result.metrics["isolated.py"].bridge_score == 0.0
    assert result.metrics["isolated.py"].centrality == 0.0


def test_within_cluster_bridge_score_is_zero_for_fully_disconnected_clusters(
    tmp_path: Path,
) -> None:
    _write_two_cluster_fixture(tmp_path)
    index = _build_index(tmp_path)

    result = build_subsystem_graph(index)

    for file_path in ["a1.py", "a2.py", "a3.py", "b1.py", "b2.py", "b3.py"]:
        assert result.metrics[file_path].bridge_score == 0.0


def test_result_is_deterministic_across_repeated_runs(tmp_path: Path) -> None:
    _write_two_cluster_fixture(tmp_path)
    index = _build_index(tmp_path)

    first = build_subsystem_graph(index)
    second = build_subsystem_graph(index)

    assert {f: m.community_id for f, m in first.metrics.items()} == {
        f: m.community_id for f, m in second.metrics.items()
    }
    assert first.communities == second.communities
    assert first.modularity == second.modularity
    assert first.iterations_run == second.iterations_run


def test_empty_index_yields_empty_result(tmp_path: Path) -> None:
    index = _build_index(tmp_path)
    result = build_subsystem_graph(index)
    assert result.metrics == {}
    assert result.communities == {}
    assert result.modularity == 0.0


def test_import_edge_to_a_file_missing_from_file_analyses_does_not_crash(
    tmp_path: Path,
) -> None:
    """Real bug, found 2026-08-11 re-running the DRP ground-truth suite
    against a fresh Traefik clone: a deeply-nested generated-code file
    exceeded Windows' MAX_PATH while resolving, so engine.py's own
    graceful "unreadable file -> skip, not a hard failure" handling
    (see engine.py's process_file) excluded it from file_analyses — but
    it was still a real, scanned import target, so ImportGraph still had
    an edge pointing to it. `_build_adjacency` didn't know that edge's
    target might not be in file_analyses, so `_run_label_propagation`
    KeyError'd on `degree[neighbor]` for a file it never expected to see.
    Reproduced here by deleting one file's entry from file_analyses
    AFTER building a real index (so import_graph still references it),
    without needing a real MAX_PATH failure to trigger it — any reason a
    scanned, import-referenced file ends up missing from file_analyses
    hits this same path."""
    _write_two_cluster_fixture(tmp_path)
    index = _build_index(tmp_path)
    assert "a2.py" in index.file_analyses
    del index.file_analyses["a2.py"]  # a1.py imports it; import_graph still has the edge

    result = build_subsystem_graph(index)  # must not raise KeyError

    assert "a2.py" not in result.metrics
    assert "a1.py" in result.metrics
    assert "a3.py" in result.metrics
