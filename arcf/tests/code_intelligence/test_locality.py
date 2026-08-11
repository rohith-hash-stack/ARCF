from pathlib import Path

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.locality import (
    has_locality,
    locality_filtered_callers_of_name,
    locality_filtered_caller_files,
    locality_filtered_transitive_callers,
)
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner


def _build_index(tmp_path: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    return engine.build_index(tmp_path, scan.files)


def test_has_locality_same_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def helper():\n    pass\n")
    index = _build_index(tmp_path)
    assert has_locality(index, "a.py", "a.py") is True


def test_has_locality_same_directory(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def helper():\n    pass\n")
    (tmp_path / "b.py").write_text("def other():\n    pass\n")
    index = _build_index(tmp_path)
    assert has_locality(index, "a.py", "b.py") is True


def test_has_locality_caller_imports_definition(tmp_path: Path) -> None:
    # The exact production shape (login.go imports and calls auth.go, in
    # different directories) that the copied-from-Fix-#9 formula silently
    # dropped: it only ever checked whether the DEFINITION's file imported
    # the CALLER's file, never the reverse. `caller_file` here is the
    # unknown side being evaluated; `context_file` is the definition's own
    # file, matching how locality_filtered_caller_files/callers_of_name
    # actually call this.
    (tmp_path / "pkg_a").mkdir()
    (tmp_path / "pkg_b").mkdir()
    (tmp_path / "pkg_a" / "auth.py").write_text(
        "def authenticate(user):\n    return True\n"
    )
    (tmp_path / "pkg_b" / "login.py").write_text(
        "from pkg_a.auth import authenticate\n\n"
        "def login(user):\n    return authenticate(user)\n"
    )
    index = _build_index(tmp_path)
    assert "pkg_a/auth.py" in index.import_graph.imports_of("pkg_b/login.py")

    assert has_locality(index, "pkg_b/login.py", "pkg_a/auth.py") is True


def test_has_locality_definition_imports_caller(tmp_path: Path) -> None:
    # Reverse direction, for symmetry: has_locality must not depend on
    # which of file_a/file_b happens to be the importer.
    (tmp_path / "pkg_a").mkdir()
    (tmp_path / "pkg_b").mkdir()
    (tmp_path / "pkg_b" / "target.py").write_text("def widget():\n    pass\n")
    (tmp_path / "pkg_a" / "uses_target.py").write_text(
        "from pkg_b.target import widget\n\ndef call_it():\n    return widget()\n"
    )
    index = _build_index(tmp_path)

    assert has_locality(index, "pkg_a/uses_target.py", "pkg_b/target.py") is True
    assert has_locality(index, "pkg_b/target.py", "pkg_a/uses_target.py") is True


def test_has_locality_no_relationship_returns_false(tmp_path: Path) -> None:
    (tmp_path / "pkg_a").mkdir()
    (tmp_path / "pkg_b").mkdir()
    (tmp_path / "pkg_a" / "a.py").write_text("def helper():\n    pass\n")
    (tmp_path / "pkg_b" / "b.py").write_text("def other():\n    pass\n")
    index = _build_index(tmp_path)

    assert has_locality(index, "pkg_a/a.py", "pkg_b/b.py") is False


def test_locality_filtered_callers_of_name_excludes_unrelated_same_named_symbol(
    tmp_path: Path,
) -> None:
    # Two unrelated packages both define `helper` (the CallGraph fan-out
    # case: an ambiguous name resolves to every same-named candidate
    # repo-wide). Only pkg2's own local call should count.
    (tmp_path / "pkg1").mkdir()
    (tmp_path / "pkg2").mkdir()
    (tmp_path / "pkg1" / "a.py").write_text(
        "class Foo:\n    def helper(self):\n        pass\n"
    )
    (tmp_path / "pkg2" / "b.py").write_text(
        "class Bar:\n    def helper(self):\n        pass\n\n"
        "def use():\n    return Bar().helper()\n"
    )
    index = _build_index(tmp_path)

    files = locality_filtered_callers_of_name(index, "helper", context_file="pkg2/b.py")
    assert files == {"pkg2/b.py"}


def test_locality_filtered_callers_of_name_includes_real_cross_package_caller(
    tmp_path: Path,
) -> None:
    (tmp_path / "pkg_a").mkdir()
    (tmp_path / "pkg_b").mkdir()
    (tmp_path / "pkg_a" / "auth.py").write_text(
        "def authenticate(user):\n    return True\n"
    )
    (tmp_path / "pkg_b" / "login.py").write_text(
        "from pkg_a.auth import authenticate\n\n"
        "def login(user):\n    return authenticate(user)\n"
    )
    index = _build_index(tmp_path)

    files = locality_filtered_callers_of_name(
        index, "authenticate", context_file="pkg_a/auth.py"
    )
    assert files == {"pkg_a/auth.py", "pkg_b/login.py"}


def test_locality_filtered_caller_files_drops_unrelated_module_level_call(
    tmp_path: Path,
) -> None:
    (tmp_path / "pkg_a").mkdir()
    (tmp_path / "pkg_b").mkdir()
    (tmp_path / "pkg_a" / "auth.py").write_text(
        "def authenticate(user):\n    return True\n"
    )
    (tmp_path / "pkg_b" / "other.py").write_text("def unrelated():\n    pass\n")
    index = _build_index(tmp_path)
    authenticate = next(
        s for s in index.symbol_index.all() if s.name == "authenticate"
    )

    files = locality_filtered_caller_files(index, authenticate.id, "pkg_a/auth.py")
    assert files == set()


def test_locality_filtered_transitive_callers_follows_import_connected_chain(
    tmp_path: Path,
) -> None:
    # repository <- service <- controller, each pair connected by a real
    # import, three different directories.
    (tmp_path / "repo").mkdir()
    (tmp_path / "svc").mkdir()
    (tmp_path / "ctrl").mkdir()
    (tmp_path / "repo" / "repository.py").write_text(
        "def authenticate(user):\n    return True\n"
    )
    (tmp_path / "svc" / "service.py").write_text(
        "from repo.repository import authenticate\n\n"
        "def login(user):\n    return authenticate(user)\n"
    )
    (tmp_path / "ctrl" / "controller.py").write_text(
        "from svc.service import login\n\n"
        "def handle_login(user):\n    return login(user)\n"
    )
    index = _build_index(tmp_path)
    authenticate = next(
        s for s in index.symbol_index.all() if s.name == "authenticate"
    )
    login = next(s for s in index.symbol_index.all() if s.name == "login")
    handle_login = next(
        s for s in index.symbol_index.all() if s.name == "handle_login"
    )

    result = locality_filtered_transitive_callers(
        index, index.call_graph, authenticate.id, "repo/repository.py", max_depth=None
    )
    assert result == {
        login.id: (1, authenticate.id),
        handle_login.id: (2, login.id),
    }
