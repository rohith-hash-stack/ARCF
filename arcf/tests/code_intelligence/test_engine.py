from pathlib import Path

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner


def _engine(max_workers: int = 8) -> CodeIntelligenceEngine:
    return CodeIntelligenceEngine(
        LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator(), max_workers=max_workers
    )


def _typescript_engine() -> CodeIntelligenceEngine:
    return CodeIntelligenceEngine(LanguageRegistry([TypeScriptLanguageAnalyzer()]), CostEstimator())


def test_build_index_from_real_files(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "login.py").write_text(
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )
    scan = RepositoryScanner().scan(tmp_path)

    index = _engine().build_index(tmp_path, scan.files)

    assert len(index.symbol_index) == 2
    assert index.candidate_selector.callers_of("authenticate") == {"auth.py", "login.py"}


def test_non_source_files_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "readme.md").write_text("# hello")
    scan = RepositoryScanner().scan(tmp_path)
    index = _engine().build_index(tmp_path, scan.files)
    assert index.file_analyses == {}


def test_incremental_indexing_reuses_unchanged_file_analysis(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    pass\n")
    (tmp_path / "b.py").write_text("def b():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)
    first = _engine().build_index(tmp_path, scan.files)

    (tmp_path / "a.py").write_text("def a():\n    pass\n\ndef a2():\n    pass\n")
    scan2 = RepositoryScanner().scan(tmp_path)
    second = _engine().build_index(tmp_path, scan2.files, previous_index=first)

    assert second.file_analyses["b.py"] is first.file_analyses["b.py"]
    assert second.file_analyses["a.py"] is not first.file_analyses["a.py"]
    assert len(second.symbol_index) == 3  # a, a2, b


def test_incremental_indexing_with_no_changes_reuses_everything(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)
    first = _engine().build_index(tmp_path, scan.files)
    second = _engine().build_index(tmp_path, scan.files, previous_index=first)

    assert second.file_analyses["a.py"] is first.file_analyses["a.py"]


def test_cross_file_inheritance_and_calls_resolved(tmp_path: Path) -> None:
    (tmp_path / "base.py").write_text("class BasePage:\n    pass\n")
    (tmp_path / "login.py").write_text(
        "from .base import BasePage\n\nclass LoginPage(BasePage):\n    pass\n"
    )
    scan = RepositoryScanner().scan(tmp_path)
    index = _engine().build_index(tmp_path, scan.files)

    assert index.candidate_selector.subclasses_of("BasePage") == {"base.py", "login.py"}
    assert index.import_graph.imports_of("login.py") == {"base.py"}


def test_token_counts_populated_per_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)
    index = _engine().build_index(tmp_path, scan.files)

    assert index.token_counts["a.py"] > 0


def test_build_index_is_deterministic_regardless_of_worker_count(tmp_path: Path) -> None:
    # ARCF hardening §9: symbol/call/import order and every field must be
    # byte-for-byte identical no matter how many threads ran the per-file
    # work, since ThreadPoolExecutor.map preserves input order.
    for i in range(12):
        (tmp_path / f"m{i}.py").write_text(
            f"def f{i}():\n    return f{(i + 1) % 12}()\n"
            if i < 11
            else f"def f{i}():\n    return 0\n"
        )
    scan = RepositoryScanner().scan(tmp_path)

    sequential = _engine(max_workers=1).build_index(tmp_path, scan.files)
    parallel_small = _engine(max_workers=2).build_index(tmp_path, scan.files)
    parallel_large = _engine(max_workers=16).build_index(tmp_path, scan.files)

    sequential_symbol_ids = [s.id for s in sequential.symbol_index.all()]
    assert sequential_symbol_ids == [s.id for s in parallel_small.symbol_index.all()]
    assert sequential_symbol_ids == [s.id for s in parallel_large.symbol_index.all()]
    assert list(sequential.file_analyses.keys()) == list(parallel_small.file_analyses.keys())
    assert list(sequential.file_analyses.keys()) == list(parallel_large.file_analyses.keys())
    assert (
        sequential.content_hashes == parallel_small.content_hashes == parallel_large.content_hashes
    )
    assert sequential.token_counts == parallel_small.token_counts == parallel_large.token_counts


def test_python_src_layout_absolute_import_resolved(tmp_path: Path) -> None:
    (tmp_path / "src" / "mypackage").mkdir(parents=True)
    (tmp_path / "src" / "mypackage" / "__init__.py").write_text("")
    (tmp_path / "src" / "mypackage" / "utils.py").write_text("def helper():\n    pass\n")
    (tmp_path / "src" / "mypackage" / "app.py").write_text(
        "from mypackage.utils import helper\n\ndef run():\n    return helper()\n"
    )
    scan = RepositoryScanner().scan(tmp_path)

    index = _engine().build_index(tmp_path, scan.files)

    assert index.import_graph.imports_of("src/mypackage/app.py") == {"src/mypackage/utils.py"}


def test_typescript_path_alias_resolved_via_tsconfig(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions": {"paths": {"@app/*": ["src/app/*"]}}}'
    )
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "utils.ts").write_text("export function helper() {}\n")
    (tmp_path / "src" / "index.ts").write_text(
        "import { helper } from '@app/utils';\n\nhelper();\n"
    )
    scan = RepositoryScanner().scan(tmp_path)

    index = _typescript_engine().build_index(tmp_path, scan.files)

    assert index.import_graph.imports_of("src/index.ts") == {"src/app/utils.ts"}


def test_no_tsconfig_leaves_bare_specifier_unresolved(tmp_path: Path) -> None:
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "utils.ts").write_text("export function helper() {}\n")
    (tmp_path / "src" / "index.ts").write_text(
        "import { helper } from '@app/utils';\n\nhelper();\n"
    )
    scan = RepositoryScanner().scan(tmp_path)

    index = _typescript_engine().build_index(tmp_path, scan.files)

    assert index.import_graph.imports_of("src/index.ts") == set()


def test_empty_file_list_returns_empty_index(tmp_path: Path) -> None:
    index = _engine().build_index(tmp_path, [])
    assert index.file_analyses == {}
    assert index.skipped_files == []


def test_token_counts_reused_for_unchanged_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    pass\n")
    (tmp_path / "b.py").write_text("def b():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)
    first = _engine().build_index(tmp_path, scan.files)

    (tmp_path / "a.py").write_text("def a():\n    pass\n\ndef a2():\n    pass\n")
    scan2 = RepositoryScanner().scan(tmp_path)
    second = _engine().build_index(tmp_path, scan2.files, previous_index=first)

    assert second.token_counts["b.py"] == first.token_counts["b.py"]
    assert second.token_counts["a.py"] > first.token_counts["a.py"]
