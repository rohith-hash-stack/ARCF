"""ARCF-DI Phase 10: enforces Phase 0's scope freeze — no module
ARCF-DI owns may import `execution` or `contracts`.

BLUEPRINT.md Phase 0 froze the boundary at ContextPackage/
ContextResolutionResult: ARCF-DI produces those types, `execution/` and
`contracts/` only ever consume them. BLUEPRINT.md Phase 10 calls for a
"CI import-lint" enforcing that. This repository has no CI pipeline
today (confirmed repeatedly across every ARCF-DI PR so far — zero
status checks configured), so there is no workflow file to hang an
import-lint off yet. Wiring one up is a repo-wide decision (it would
gate every future PR, not just ARCF-DI's own) outside a single phase's
scope — left to the user. What's implemented here is the enforcement
mechanism actually available today: a test in the existing suite, which
already runs on every PR by the same convention every prior ARCF-DI
phase has followed (pytest -q, before merge).

Deliberately checks each module's OWN import statements via `ast`, not
a transitive-closure dependency graph — this matches BLUEPRINT.md's own
framing ("no module ARCF-DI owns may import execution/contracts"), a
direct-import check, not a "nothing in the transitive dependency tree"
check, which would also flag arbitrary infrastructure/stdlib modules
that happen to be reachable through unrelated paths.
"""

import ast
from pathlib import Path

_ARCF_DI_OWNED_MODULES: tuple[str, ...] = (
    "domain/behavioral_record.py",
    "domain/summarization.py",
    "domain/audit.py",
    "domain/context_package.py",
    "code_intelligence/behavioral_record.py",
    "code_intelligence/library_boundary.py",
    "code_intelligence/integrity.py",
    "code_intelligence/call_graph.py",
    "code_intelligence/reference_resolver.py",
    "context/evidence_summarizer.py",
    "context/evidence_attribution.py",
    "infrastructure/behavioral_record_store.py",
    "workspace/dependency_manifest.py",
)
"""Every module an ARCF-DI phase (1-9) created or extended — see
BLUEPRINT.md Phase 10's migration table and arcf-di/PROGRESS.md's
per-phase entries for where each one came from. Deliberately a fixed
list, not a directory glob: a glob would silently start checking
whatever gets added to code_intelligence/context/domain/infrastructure/
workspace next, including modules ARCF-DI never touched and has no
opinion about."""

_FORBIDDEN_TOP_LEVEL_MODULES: frozenset[str] = frozenset({"execution", "contracts"})


def _imported_top_level_modules(file_path: Path) -> set[str]:
    tree = ast.parse(file_path.read_text(), filename=str(file_path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module.split(".")[0])
    return modules


def test_arcf_di_owned_modules_exist_at_the_expected_paths() -> None:
    """A path that stops existing (renamed, moved) should fail loudly
    here, not silently drop out of the boundary check below."""
    src_root = Path(__file__).resolve().parents[2] / "src"
    missing = [rel for rel in _ARCF_DI_OWNED_MODULES if not (src_root / rel).exists()]
    assert missing == []


def test_arcf_di_modules_never_import_execution_or_contracts() -> None:
    src_root = Path(__file__).resolve().parents[2] / "src"
    violations: list[str] = []

    for rel_path in _ARCF_DI_OWNED_MODULES:
        imported = _imported_top_level_modules(src_root / rel_path)
        forbidden = imported & _FORBIDDEN_TOP_LEVEL_MODULES
        if forbidden:
            violations.append(f"{rel_path} imports forbidden module(s): {sorted(forbidden)}")

    assert violations == []
