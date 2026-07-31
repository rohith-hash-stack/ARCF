"""Testing requirement #3 from the Context Resolution Contract
refinement: Phase 6 can operate entirely from ContextResolutionResult
without importing any Phase 5 implementation classes.

Verified two ways:
1. Statically — parsing phase6_stub_consumer.py's own import statements
   (via ast, not a string search) and asserting none of them touch
   code_intelligence internals.
2. Functionally — building a real ContextResolutionResult via
   ContextResolver (Phase 5) and handing it to the stub consumer, which
   never imports ContextResolver, CodeIntelligenceIndex, SymbolIndex,
   CallGraph, or anything else from code_intelligence/.
"""

import ast
from pathlib import Path

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner

from . import phase6_stub_consumer


def test_stub_consumer_does_not_import_code_intelligence_internals() -> None:
    source_path = Path(phase6_stub_consumer.__file__)
    tree = ast.parse(source_path.read_text())

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert imported_modules, "expected the stub to import something"
    assert all(not module.startswith("code_intelligence") for module in imported_modules)
    assert any(module.startswith("domain.context_resolution") for module in imported_modules)


def test_stub_consumer_operates_on_a_real_resolution_result(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "login.py").write_text(
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    index = engine.build_index(tmp_path, RepositoryScanner().scan(tmp_path).files)
    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), ["authenticate"])

    ranked = phase6_stub_consumer.rank_candidate_files(result)
    assert set(ranked) == {"auth.py", "login.py"}
    assert ranked[0] == "auth.py"  # "defines" sorts before "calls"

    summary = phase6_stub_consumer.summarize(result)
    assert "2 candidate file(s)" in summary
