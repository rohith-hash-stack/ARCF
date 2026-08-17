"""Testing requirement #3 from the Context Resolution Contract
refinement: Phase 6 can operate entirely from ContextResolutionResult
without importing any Phase 5 implementation classes.

Verified three ways:
1. Statically — parsing phase6_stub_consumer.py's own import statements
   (via ast, not a string search) and asserting none of them touch
   code_intelligence internals.
2. Functionally — building a real ContextResolutionResult via
   ContextResolver (Phase 5) and handing it to the stub consumer, which
   never imports ContextResolver, CodeIntelligenceIndex, SymbolIndex,
   CallGraph, or anything else from code_intelligence/.
3. Architecture closure (2026-08-16, dependency-direction investigation,
   ARCF_ARCHITECTURE_CLOSURE_CHECKLIST_2026-08-16.md Sec. 20): (1) and
   (2) only ever verified a synthetic stub file, never the REAL
   production Ranking/Context Construction modules -- exactly the gap
   the closure's own instructions warned about ("a test passing is not
   sufficient if it doesn't inspect the real dependency path"). This
   adds that real check: relevance_ranker.py/packager.py/
   budget_manager.py/compressor.py are the files whose contracts
   actually matter for this boundary, and none of them may import
   code_intelligence. (Three other context/ modules -- anchor_
   classifier.py, lexical_symbol_probe.py, subsystem_localizer.py -- DO
   import code_intelligence.symbol_index; investigated and determined
   NOT a boundary violation, since SymbolIndex is code_intelligence's
   own intentional public read interface and all three modules are
   experimental, flag-gated-off retrieval-time fallback helpers, not
   part of Ranking/Context Construction. Deliberately excluded from this
   test, not overlooked -- see the checklist entry for the full
   reasoning.)
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

_REAL_RANKING_CONTEXT_MODULES = (
    "context/relevance_ranker.py",
    "context/packager.py",
    "context/budget_manager.py",
    "context/compressor.py",
)


def _imported_module_names(source_path: Path) -> list[str]:
    tree = ast.parse(source_path.read_text())
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
    return imported_modules


def test_stub_consumer_does_not_import_code_intelligence_internals() -> None:
    imported_modules = _imported_module_names(Path(phase6_stub_consumer.__file__))

    assert imported_modules, "expected the stub to import something"
    assert all(not module.startswith("code_intelligence") for module in imported_modules)
    assert any(module.startswith("domain.context_resolution") for module in imported_modules)


def test_real_ranking_and_context_construction_modules_do_not_import_code_intelligence() -> None:
    """The real boundary FA-06 (valid dependency direction) cares about:
    Ranking must consume only the ContextResolutionResult contract, never
    reach into Code Intelligence's own graph/index classes."""
    src_root = Path(__file__).resolve().parents[2] / "src"

    for relative_path in _REAL_RANKING_CONTEXT_MODULES:
        source_path = src_root / relative_path
        assert source_path.is_file(), f"expected {source_path} to exist"
        imported_modules = _imported_module_names(source_path)
        offending = [m for m in imported_modules if m.startswith("code_intelligence")]
        assert not offending, f"{relative_path} imports code_intelligence: {offending}"


# The one code_intelligence import application/ may ever make -- everything
# else under code_intelligence/ is "internals" by definition (an allowlist,
# not a blocklist: a future new code_intelligence internal module is
# automatically forbidden here without needing to be added to a growing
# list of known-bad names).
_ALLOWED_CODE_INTELLIGENCE_IMPORT = "code_intelligence.service"


def test_application_orchestrator_does_not_import_code_intelligence_internals() -> None:
    """DI-04/DI-FA-10 (architecture closure, 2026-08-16): the orchestrator
    must re-enter retrieval only through CodeIntelligenceContractService's
    public method (attach_code_intelligence), never by importing
    ContextResolver/CallGraph/SymbolIndex/locality.py directly -- that's
    what "Recovery must not manipulate internals" means at the import
    level, not just as a design intention. Previously only verified via a
    one-off manual grep during development; this locks it in as a real
    regression test, per the closure's own instruction not to leave a
    dependency-direction claim unverified by an actual test.

    G7 hardening (2026-08-17, independent verification report): the
    original version of this test only scanned ONE hardcoded file
    (execute_use_case.py) against a hardcoded blocklist of "known
    internals" -- a genuinely different, weaker guarantee than the
    reverse-direction test just below, which generically scans an entire
    package. Neither weakness is hypothetical: application/ could grow a
    second module tomorrow that this test would silently never check, and
    code_intelligence/ could grow a new internal module tomorrow that the
    blocklist would silently never know to forbid. Now scans every .py
    file under application/ (there are two today: __init__.py and
    execute_use_case.py, but the test no longer depends on that staying
    true) against an ALLOWLIST of the one legitimate code_intelligence
    import -- fails safe in both directions the old version didn't."""
    src_root = Path(__file__).resolve().parents[2] / "src"
    application_root = src_root / "application"
    assert application_root.is_dir()

    offenders: list[str] = []
    saw_allowed_import = False
    for source_path in application_root.rglob("*.py"):
        imported_modules = _imported_module_names(source_path)
        for module in imported_modules:
            if not module.startswith("code_intelligence"):
                continue
            if module == _ALLOWED_CODE_INTELLIGENCE_IMPORT:
                saw_allowed_import = True
            else:
                offenders.append(f"{source_path.relative_to(src_root)} imports {module}")

    assert not offenders, f"application/ imports code_intelligence internals: {offenders}"
    assert saw_allowed_import, (
        f"expected at least one application/ file to import {_ALLOWED_CODE_INTELLIGENCE_IMPORT}"
    )


def test_no_reverse_dependency_from_code_intelligence_or_context_onto_application() -> None:
    """The other half of "no prohibited circular dependency": nothing
    application/ depends on may depend back on application/ -- confirmed
    by scanning every .py file under code_intelligence/ and context/."""
    src_root = Path(__file__).resolve().parents[2] / "src"
    offenders: list[str] = []
    for package in ("code_intelligence", "context"):
        for source_path in (src_root / package).rglob("*.py"):
            imported_modules = _imported_module_names(source_path)
            if any(m.startswith("application") for m in imported_modules):
                offenders.append(str(source_path.relative_to(src_root)))
    assert not offenders, f"circular dependency: {offenders} import application/"


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
