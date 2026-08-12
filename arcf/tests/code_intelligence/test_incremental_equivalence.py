"""Checklist item #7 (arcf/CHECKLIST.md) — real equivalence test proving
CodeIntelligenceEngine.build_index's incremental path (previous_index with
a real subset of files changed) produces a STRUCTURALLY IDENTICAL index to
a full rebuild from scratch, for the same final repository state.

This is the permanent, testable form of "100% Topological Parity" / "Zero
Orphaned References" — the current architecture never attempts partial
graph patching (every graph is always rebuilt fully and fresh from a
complete FileAnalysis dict, whether each entry was cache-reused or freshly
parsed), so this test is expected to hold by construction, not by luck —
but a real assertion beats an architectural argument alone.
"""

from pathlib import Path

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner


def _engine() -> CodeIntelligenceEngine:
    return CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())


def _index_signature(index: CodeIntelligenceIndex) -> dict:
    """Everything a "the graphs are structurally identical" claim needs to
    check, built entirely from this module's own public API (no private
    attribute access) so this test stays valid even if internal storage
    changes."""
    symbols = sorted(index.symbol_index.all(), key=lambda s: s.id)
    symbol_ids = [s.id for s in symbols]

    call_edges = set()
    caller_files: dict[str, tuple[str, ...]] = {}
    for symbol_id in symbol_ids:
        for caller in index.call_graph.caller_symbols_of(symbol_id):
            call_edges.add((caller, symbol_id))
        caller_files[symbol_id] = tuple(sorted(index.call_graph.caller_files_of(symbol_id)))

    inheritance_edges = set()
    for symbol in symbols:
        if symbol.kind.value != "class":
            continue
        for subclass_id in index.inheritance_graph.all_subclasses_of(symbol.id, max_depth=None):
            inheritance_edges.add((symbol.id, subclass_id))

    import_edges = set()
    for file_path in index.file_analyses:
        for imported in index.import_graph.imports_of(file_path):
            import_edges.add((file_path, imported))

    return {
        "symbols": [s.model_dump() for s in symbols],
        "call_edges": sorted(call_edges),
        "caller_files": caller_files,
        "inheritance_edges": sorted(inheritance_edges),
        "import_edges": sorted(import_edges),
        "content_hashes": dict(index.content_hashes),
        "token_counts": dict(index.token_counts),
        "skipped_files": sorted(index.skipped_files),
    }


def test_incremental_rebuild_matches_full_rebuild_after_editing_a_file(tmp_path: Path) -> None:
    (tmp_path / "base.py").write_text("class BasePage:\n    def render(self):\n        pass\n")
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "login.py").write_text(
        "from .auth import authenticate\nfrom .base import BasePage\n\n"
        "class LoginPage(BasePage):\n"
        "    def check(self, user):\n        return authenticate(user)\n"
    )
    engine = _engine()
    scan_v1 = RepositoryScanner().scan(tmp_path)
    index_v1 = engine.build_index(tmp_path, scan_v1.files)

    # Real diff: edit one file (adds a new symbol + a new call edge),
    # everything else on disk is untouched.
    (tmp_path / "auth.py").write_text(
        "def authenticate(user):\n    return _check(user)\n\n"
        "def _check(user):\n    return True\n"
    )
    scan_v2 = RepositoryScanner().scan(tmp_path)

    full_v2 = engine.build_index(tmp_path, scan_v2.files)  # ground truth: no previous_index
    incremental_v2 = engine.build_index(tmp_path, scan_v2.files, previous_index=index_v1)

    assert _index_signature(full_v2) == _index_signature(incremental_v2)
    # Confirm the incremental path actually reused the untouched files
    # (login.py, base.py) rather than accidentally re-parsing everything --
    # otherwise this test would trivially pass by doing a full rebuild
    # every time regardless of previous_index.
    assert incremental_v2.file_analyses["login.py"] is index_v1.file_analyses["login.py"]
    assert incremental_v2.file_analyses["base.py"] is index_v1.file_analyses["base.py"]
    assert incremental_v2.file_analyses["auth.py"] is not index_v1.file_analyses["auth.py"]


def test_incremental_rebuild_matches_full_rebuild_after_adding_a_file(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    engine = _engine()
    scan_v1 = RepositoryScanner().scan(tmp_path)
    index_v1 = engine.build_index(tmp_path, scan_v1.files)

    (tmp_path / "login.py").write_text(
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )
    scan_v2 = RepositoryScanner().scan(tmp_path)

    full_v2 = engine.build_index(tmp_path, scan_v2.files)
    incremental_v2 = engine.build_index(tmp_path, scan_v2.files, previous_index=index_v1)

    assert _index_signature(full_v2) == _index_signature(incremental_v2)
    assert incremental_v2.file_analyses["auth.py"] is index_v1.file_analyses["auth.py"]


def test_incremental_rebuild_matches_full_rebuild_after_removing_a_file(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "unrelated.py").write_text("def unrelated():\n    pass\n")
    engine = _engine()
    scan_v1 = RepositoryScanner().scan(tmp_path)
    index_v1 = engine.build_index(tmp_path, scan_v1.files)

    (tmp_path / "unrelated.py").unlink()
    scan_v2 = RepositoryScanner().scan(tmp_path)

    full_v2 = engine.build_index(tmp_path, scan_v2.files)
    incremental_v2 = engine.build_index(tmp_path, scan_v2.files, previous_index=index_v1)

    assert _index_signature(full_v2) == _index_signature(incremental_v2)
    assert "unrelated.py" not in incremental_v2.file_analyses
    assert incremental_v2.file_analyses["auth.py"] is index_v1.file_analyses["auth.py"]


def test_incremental_rebuild_matches_full_rebuild_with_no_changes_at_all(tmp_path: Path) -> None:
    """The 100% cache-hit case -- every file reused, graphs still rebuilt
    fresh (per build_index's own docstring), must still match a full
    rebuild exactly."""
    (tmp_path / "base.py").write_text("class BasePage:\n    pass\n")
    (tmp_path / "login.py").write_text(
        "from .base import BasePage\n\nclass LoginPage(BasePage):\n    pass\n"
    )
    engine = _engine()
    scan = RepositoryScanner().scan(tmp_path)
    index_v1 = engine.build_index(tmp_path, scan.files)

    full_rebuild = engine.build_index(tmp_path, scan.files)
    incremental_no_op = engine.build_index(tmp_path, scan.files, previous_index=index_v1)

    assert _index_signature(full_rebuild) == _index_signature(incremental_no_op)
    assert incremental_no_op.file_analyses["base.py"] is index_v1.file_analyses["base.py"]
    assert incremental_no_op.file_analyses["login.py"] is index_v1.file_analyses["login.py"]
