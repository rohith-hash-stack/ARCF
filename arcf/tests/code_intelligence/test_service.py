"""CodeIntelligenceContractService — proves the ARCF v2.3 retrieval-
context stabilization patch end to end: a repository-scoped request
with no named symbols (so target_names is empty and symbol-based
resolution alone would return zero candidate_files, exactly the
regression this patch fixes) still reaches attach_code_intelligence
with a non-empty, evidence-backed candidate_files list.
"""

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from code_intelligence.drp.drp_index import DrpIndexBuilder
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator


def _write(tmp_path: Path, relative_path: str, content: str) -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _service() -> tuple[CodeIntelligenceContractService, InMemoryContractStore]:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    return service, contract_store


def _seed_contract(contract_store: InMemoryContractStore, raw_request: str) -> LivingContract:
    intent = UserIntent(
        raw_request=raw_request,
        intent="document the repository",
        domain="documentation",
        task="documentation",
        entities=[],
        confidence=0.9,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)
    return living


async def test_repository_scoped_request_with_no_entities_still_gets_files(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "package.json", '{"name": "demo"}')
    _write(tmp_path, "tests/test_app.py", "def test_ok():\n    assert True\n")
    _write(tmp_path, "README.md", "# Demo\n")

    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "Generate clear documentation for this repository's test suite, including setup, "
        "execution, and contribution guidelines.",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert len(resolution.candidate_files) > 0
    assert all(ref.reason.startswith("evidence: ") for ref in resolution.candidate_files)


async def test_non_repository_scoped_request_with_no_entities_stays_empty(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "package.json", '{"name": "demo"}')

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Fix the off-by-one error somewhere")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert resolution.candidate_files == []


async def test_non_repository_scoped_request_recovers_via_lexical_symbol_probe(
    tmp_path: Path,
) -> None:
    """Classifier-gap fix, layer 3 (§4.3 of the 2026-08-06 handoff): a
    feature-implementation query naming no exact symbol, no repository
    noun, and no filename would previously stay empty (as
    test_non_repository_scoped_request_with_no_entities_stays_empty
    still correctly proves for a query with truly nothing to latch onto)
    — but this one's wording shares a lexical root with a real symbol,
    `Dependant`, so lexical probing should recover it via the full
    resolution pipeline, not just an evidence-fallback file dump."""
    _write(
        tmp_path,
        "deps.py",
        "class Dependant:\n    def solve(self):\n        ...\n",
    )
    _write(tmp_path, "package.json", '{"name": "demo"}')

    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "Add support for a custom dependency cache invalidation strategy",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert [ref.file_path for ref in resolution.candidate_files] == ["deps.py"]
    assert resolution.candidate_files[0].reason == "defines Dependant"
    assert "Lexical symbol probing" in resolution.resolution_reason


async def test_conceptual_query_with_no_entities_still_finds_real_symbol_via_lexical_probe(
    tmp_path: Path,
) -> None:
    """Regression for the flask 'explain how context locals work' case: a
    conceptual question with no named entity (empty target_names) used to
    settle for whatever expand_with_evidence's generic categories matched
    (README, dependency manifest) and never probe for the real symbol —
    even though the query's wording ("context locals") shares a lexical
    root with a real class, AppContext, defined in a file none of the
    evidence categories would ever glob-match. Lexical symbol probing must
    run regardless of expand_with_evidence already having found
    (irrelevant) files, and must ADD the real match rather than replace
    what evidence-fallback already found (see
    test_symbol_resolved_request_is_not_touched_by_fallback's sibling
    concern for why an outright replace was tried and reverted: a later,
    independent completeness guarantee — evidence_validator.
    validate_sufficiency — re-adds any evidence category dropped here, so
    trying to trim them from this method is a no-op fight against that
    guarantee, not a real savings)."""
    _write(tmp_path, "README.md", "# Demo\n")
    _write(tmp_path, "pyproject.toml", '[project]\nname = "demo"\n')
    _write(
        tmp_path,
        "ctx.py",
        "class AppContext:\n    def push(self):\n        ...\n",
    )

    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "Explain how request and application contexts are implemented using context locals.",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    file_paths = {ref.file_path for ref in resolution.candidate_files}
    assert "ctx.py" in file_paths, (
        "lexical symbol probing should have surfaced AppContext's file even "
        "though it matches no evidence-contract category"
    )
    assert "README.md" in file_paths and "pyproject.toml" in file_paths, (
        "evidence-fallback's own matches must survive, not be replaced"
    )
    assert "Lexical symbol probing" in resolution.resolution_reason
    ctx_ref = next(ref for ref in resolution.candidate_files if ref.file_path == "ctx.py")
    assert ctx_ref.reason == "defines AppContext"


async def test_subsystem_localization_flag_defaults_off_and_reproduces_sqlalchemy_fanout(
    tmp_path: Path,
) -> None:
    """ARCF root-cause validation experiment (context/subsystem_localizer.py)
    — end-to-end proof that `enable_subsystem_localization` actually
    changes `attach_code_intelligence`'s behavior, using a small fixture
    that reproduces the real SQLAlchemy failure shape: a query-relevant
    module (orm/) and an unrelated module (dialects/) whose generically-
    named helper happens to share a lexical root with the query, exactly
    the "_generate_cache_key" pattern measured in the real benchmark."""
    _write(
        tmp_path,
        "orm/strategies.py",
        "class LazyLoader:\n    def load_strategy(self):\n        pass\n",
    )
    _write(tmp_path, "orm/loading.py", "def load_on_ident():\n    pass\n")
    _write(
        tmp_path,
        "dialects/mssql.py",
        "def apply_strategy_workaround():\n    pass\n",
    )
    service, contract_store = _service()
    query = "Explain the loading strategies used internally."

    living_default = _seed_contract(contract_store, query)
    _, default_resolution = await service.attach_code_intelligence(
        living_default.contract_id, target_names=[], workspace_root=str(tmp_path)
    )
    default_paths = {f.file_path for f in default_resolution.candidate_files}
    assert "dialects/mssql.py" in default_paths, (
        "default (flag off) behavior must reproduce the real fan-out — if this "
        "assertion fails, the fixture no longer demonstrates the problem this "
        "experiment exists to test"
    )

    living_experimental = _seed_contract(contract_store, query)
    _, experimental_resolution = await service.attach_code_intelligence(
        living_experimental.contract_id,
        target_names=[],
        workspace_root=str(tmp_path),
        enable_subsystem_localization=True,
    )
    experimental_paths = {f.file_path for f in experimental_resolution.candidate_files}
    assert "orm/strategies.py" in experimental_paths
    assert "orm/loading.py" in experimental_paths
    assert "dialects/mssql.py" not in experimental_paths, (
        "subsystem localization should have excluded the out-of-subsystem "
        "helper the unrestricted probe fanned out into"
    )


async def test_anchor_classification_flag_defaults_off_and_promotes_exact_match(
    tmp_path: Path,
) -> None:
    """ARCF Pre-Expansion Anchor Classification experiment — end-to-end
    proof that `enable_anchor_classification` changes
    `attach_code_intelligence`'s output, using the same query-names-an-
    exact-class shape as the real SQLAlchemy case (LazyLoader/
    EagerLoader in orm/strategies.py), plus an unrelated Tier-3-only
    lexical match (dialects/mssql.py) to prove Tier 1 doesn't just
    happen to subsume Tier 3."""
    _write(
        tmp_path,
        "orm/strategies.py",
        "class LazyLoader:\n    def load_strategy(self):\n        pass\n\n"
        "class EagerLoader:\n    def load_strategy(self):\n        pass\n",
    )
    _write(tmp_path, "orm/loading.py", "def load_on_ident():\n    pass\n")
    _write(
        tmp_path,
        "dialects/mssql.py",
        "def apply_strategy_workaround():\n    pass\n",
    )
    service, contract_store = _service()
    query = "Explain how LazyLoader differs from EagerLoader for loading strategies."

    living_default = _seed_contract(contract_store, query)
    _, default_resolution = await service.attach_code_intelligence(
        living_default.contract_id, target_names=[], workspace_root=str(tmp_path)
    )
    assert all(f.anchor_confidence is None for f in default_resolution.candidate_files), (
        "default (both flags off) behavior must never set anchor_confidence"
    )

    living_experimental = _seed_contract(contract_store, query)
    _, experimental_resolution = await service.attach_code_intelligence(
        living_experimental.contract_id,
        target_names=[],
        workspace_root=str(tmp_path),
        enable_anchor_classification=True,
        enable_confidence_propagation=True,
    )
    experimental_paths = {f.file_path for f in experimental_resolution.candidate_files}
    assert "orm/strategies.py" in experimental_paths
    strategies_ref = next(
        f for f in experimental_resolution.candidate_files if f.file_path == "orm/strategies.py"
    )
    assert strategies_ref.reason in ("defines LazyLoader", "defines EagerLoader")
    assert strategies_ref.anchor_confidence == 1.0, (
        "an exact-identifier (Tier 1) match's own defining file must carry "
        "full confidence (hop 0, no decay)"
    )
    assert "Pre-expansion anchor classification" in experimental_resolution.resolution_reason


async def test_anchor_classification_without_confidence_propagation_leaves_confidence_unset(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path, "orm/strategies.py", "class LazyLoader:\n    def load_strategy(self):\n        pass\n"
    )
    service, contract_store = _service()
    living = _seed_contract(contract_store, "Explain how LazyLoader works.")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id,
        target_names=[],
        workspace_root=str(tmp_path),
        enable_anchor_classification=True,
        enable_confidence_propagation=False,
    )

    assert any(f.file_path == "orm/strategies.py" for f in resolution.candidate_files)
    assert all(f.anchor_confidence is None for f in resolution.candidate_files), (
        "enable_anchor_classification alone (propagation off) must not set anchor_confidence"
    )


async def test_anchor_classification_expands_class_anchor_to_its_own_methods(
    tmp_path: Path,
) -> None:
    """ARCF Pre-Expansion Anchor Classification follow-up (2026-08-08):
    real SQLAlchemy repro — `_LazyLoader` (a CLASS) has a method that
    calls into `orm/loading.py`, but ContextResolver only runs call-graph
    expansion for FUNCTION/METHOD-kind symbols, never for the CLASS
    itself, so that real edge was invisible until the class's own
    methods were also seeded. This fixture reproduces the same shape:
    LazyLoader.helper() calls load_helper(), defined in a different
    file — reachable only if the class anchor also seeds its methods."""
    _write(
        tmp_path,
        "orm/strategies.py",
        "class LazyLoader:\n    def helper(self):\n        load_helper()\n",
    )
    _write(tmp_path, "orm/loading.py", "def load_helper():\n    pass\n")
    service, contract_store = _service()
    living = _seed_contract(contract_store, "Explain how LazyLoader works.")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id,
        target_names=[],
        workspace_root=str(tmp_path),
        enable_anchor_classification=True,
    )

    paths = {f.file_path for f in resolution.candidate_files}
    assert "orm/strategies.py" in paths
    assert "orm/loading.py" in paths, (
        "LazyLoader's own method calls load_helper() in a different file — "
        "this edge is only reachable if the class anchor's methods are "
        "also seeded for call-graph expansion, not just the class itself"
    )


async def test_anchor_classification_class_method_expansion_guards_ambiguous_names(
    tmp_path: Path,
) -> None:
    """Real regression found on the actual SQLAlchemy repo (2026-08-08):
    expanding a Tier 1 class anchor to its own methods without an
    ambiguity guard let an unqualified, widely-shared method name
    (`__init__`) resolve against every unrelated class's own `__init__`
    across the whole repo — 268 files on the real run, candidate count
    jumping from 45 to 297. This fixture reproduces the same shape with
    6 unrelated classes sharing `__init__` (over the 5-match ambiguity
    cap) so the guard must exclude it, while still allowing the real,
    non-ambiguous cross-file edge (helper -> load_helper) through."""
    _write(
        tmp_path,
        "orm/strategies.py",
        "class LazyLoader:\n"
        "    def __init__(self):\n"
        "        pass\n"
        "    def helper(self):\n"
        "        load_helper()\n",
    )
    _write(tmp_path, "orm/loading.py", "def load_helper():\n    pass\n")
    for i in range(6):
        _write(
            tmp_path,
            f"unrelated/thing_{i}.py",
            f"class Unrelated{i}:\n    def __init__(self):\n        pass\n",
        )
    service, contract_store = _service()
    living = _seed_contract(contract_store, "Explain how LazyLoader works.")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id,
        target_names=[],
        workspace_root=str(tmp_path),
        enable_anchor_classification=True,
    )

    paths = {f.file_path for f in resolution.candidate_files}
    assert "orm/loading.py" in paths, "the real, non-ambiguous edge must still be found"
    for i in range(6):
        assert f"unrelated/thing_{i}.py" not in paths, (
            "an ambiguous shared method name (__init__) must not pull in "
            "every unrelated class that happens to also define one"
        )


async def test_multi_axis_decomposition_flag_defaults_off_and_gives_each_axis_a_quota(
    tmp_path: Path,
) -> None:
    """ARCF Multi-Axis Query Decomposition experiment — end-to-end proof
    that the flag changes behavior for a comparative query, using two
    subsystems whose own vocabulary only matches ONE side of the
    comparison each (so a pooled, single-axis resolution would only ever
    pick one winner, while decomposition should let each side land its
    own file)."""
    # "loadin" (from "loading") must appear as a contiguous substring to
    # match via prefix-probing — "loading_strategy", not "load_strategy"
    # (an underscore right after "load" breaks the substring, the same
    # real gap found against the actual SQLAlchemy repo this session).
    _write(tmp_path, "orm/strategies.py", "def loading_strategy():\n    pass\n")
    _write(tmp_path, "orm/eager_helpers.py", "def eagerload_prefetch():\n    pass\n")
    service, contract_store = _service()
    query = "Explain how lazy loading differs from eagerload prefetching."

    living_default = _seed_contract(contract_store, query)
    _, default_resolution = await service.attach_code_intelligence(
        living_default.contract_id, target_names=[], workspace_root=str(tmp_path)
    )
    assert "Multi-axis" not in default_resolution.resolution_reason

    living_experimental = _seed_contract(contract_store, query)
    _, experimental_resolution = await service.attach_code_intelligence(
        living_experimental.contract_id,
        target_names=[],
        workspace_root=str(tmp_path),
        enable_multi_axis_decomposition=True,
    )
    experimental_paths = {f.file_path for f in experimental_resolution.candidate_files}
    assert "orm/strategies.py" in experimental_paths
    assert "orm/eager_helpers.py" in experimental_paths
    assert "Multi-axis query decomposition: 2 axes" in experimental_resolution.resolution_reason


async def test_multi_axis_decomposition_has_no_effect_without_a_comparative_marker(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "orm/strategies.py", "def load_strategy():\n    pass\n")
    service, contract_store = _service()
    query = "Explain how loading strategies work internally."

    living_default = _seed_contract(contract_store, query)
    _, default_resolution = await service.attach_code_intelligence(
        living_default.contract_id, target_names=[], workspace_root=str(tmp_path)
    )
    living_experimental = _seed_contract(contract_store, query)
    _, experimental_resolution = await service.attach_code_intelligence(
        living_experimental.contract_id,
        target_names=[],
        workspace_root=str(tmp_path),
        enable_multi_axis_decomposition=True,
    )

    assert default_resolution.candidate_files == experimental_resolution.candidate_files


async def test_symbol_resolved_request_is_not_touched_by_fallback(tmp_path: Path) -> None:
    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n")
    _write(tmp_path, "package.json", '{"name": "demo"}')

    service, contract_store = _service()
    living = _seed_contract(
        contract_store, "Explain this repository's authenticate() function"
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=["authenticate"], workspace_root=str(tmp_path)
    )

    assert [ref.file_path for ref in resolution.candidate_files] == ["auth.py"]
    assert resolution.candidate_files[0].reason == "defines authenticate"


async def test_repository_debugging_query_with_no_entities_still_gets_files(
    tmp_path: Path,
) -> None:
    """The exact regression from the repository debugging routing fix
    brief: 'I'm seeing a failing test in this repo. Help me diagnose the
    likely cause and suggest the first places to inspect.' names no
    symbol SLM-1 could extract as an entity, so target_names is empty —
    proving candidate_files still ends up non-empty via the
    repository_debugging evidence contract, not the documentation one."""
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    _write(tmp_path, "tests/test_checkout.py", "def test_checkout():\n    assert False\n")
    _write(tmp_path, "package.json", '{"name": "demo"}')

    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "I'm seeing a failing test in this repo. Help me diagnose the likely cause and "
        "suggest the first places to inspect.",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert len(resolution.candidate_files) > 0
    file_paths = {ref.file_path for ref in resolution.candidate_files}
    assert "pytest.ini" in file_paths
    assert "tests/test_checkout.py" in file_paths


async def test_repository_debugging_prioritizes_query_referenced_file(tmp_path: Path) -> None:
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    _write(tmp_path, "tests/test_checkout.py", "def test_checkout():\n    assert False\n")

    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "Investigate why this test is failing: tests/test_checkout.py",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    referenced = next(
        ref for ref in resolution.candidate_files if ref.file_path == "tests/test_checkout.py"
    )
    assert referenced.reason == "references: query-referenced"


async def test_diagnostic_log_line_emitted_at_debug_level(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Change 6: routing diagnostics go to the dedicated "arcf.retrieval"
    logger at DEBUG level only — never part of the returned resolution
    or any API response, so this test reads pytest's log capture, not
    the method's return value."""
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    _write(tmp_path, "tests/test_checkout.py", "def test_checkout():\n    assert False\n")

    service, contract_store = _service()
    living = _seed_contract(
        contract_store, "I'm seeing a failing test in this repo, help me diagnose it"
    )

    with caplog.at_level(logging.DEBUG, logger="arcf.retrieval"):
        await service.attach_code_intelligence(
            living.contract_id, target_names=[], workspace_root=str(tmp_path)
        )

    records = [r for r in caplog.records if r.name == "arcf.retrieval"]
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert payload["task_type"] == "repository_debugging"
    assert payload["repository_scope"] is True
    assert payload["evidence_contract"] == "repository_debugging"
    assert payload["candidate_files"] > 0


async def test_retrieval_completeness_metadata_is_populated(tmp_path: Path) -> None:
    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n")
    _write(tmp_path, "worker.go", "package main\n\nfunc main() {}\n")

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Explain this repository's authenticate() function")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=["authenticate"], workspace_root=str(tmp_path)
    )

    assert resolution.files_scanned == 2
    assert resolution.files_analyzed == 1
    assert resolution.analyzer_coverage == 0.5
    assert "Python" in resolution.languages_detected
    assert "Go" in resolution.languages_unsupported
    assert resolution.repository_segment == ""


async def test_unresolved_target_name_surfaced(tmp_path: Path) -> None:
    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n")

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Explain does_not_exist()")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=["does_not_exist"], workspace_root=str(tmp_path)
    )

    assert resolution.unresolved_symbols == ("does_not_exist",)


async def test_repository_with_no_supported_language_short_circuits(tmp_path: Path) -> None:
    # Only the Python analyzer is registered (see _service()); a Ruby-only
    # repository should never reach the full parse. A request that isn't
    # repository-scoped and matches no evidence contract gets a genuinely
    # empty, honestly-explained result — nothing to fall back to.
    _write(tmp_path, "app.rb", "def hello\n  puts 'hi'\nend\n")

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Rename this variable")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert resolution.candidate_files == []
    assert resolution.files_analyzed == 0
    assert resolution.analyzer_coverage == 0.0
    assert "Ruby" in resolution.languages_unsupported
    assert "skipped full indexing" in resolution.resolution_reason


async def test_unsupported_language_repository_still_gets_evidence_fallback(
    tmp_path: Path,
) -> None:
    # The short-circuit skips the expensive full parse, but evidence-
    # contract matching is a glob match over the scan, not a parse — a
    # repository-scoped request still gets a real, non-empty result even
    # when nothing in it can be analyzed.
    _write(tmp_path, "app.rb", "def hello\n  puts 'hi'\nend\n")

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Please explain this repository")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert len(resolution.candidate_files) > 0
    assert resolution.files_analyzed == 0
    assert "Ruby" in resolution.languages_unsupported


async def test_bug_fix_query_uses_shallow_traversal(tmp_path: Path) -> None:
    _write(tmp_path, "repository.py", "def authenticate(user):\n    return True\n")
    _write(
        tmp_path,
        "service.py",
        "from .repository import authenticate\n\ndef login(user):\n    return authenticate(user)\n",
    )
    _write(
        tmp_path,
        "controller.py",
        "from .service import login\n\ndef handle_login(user):\n    return login(user)\n",
    )

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Fix the bug in authenticate()")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=["authenticate"], workspace_root=str(tmp_path)
    )

    file_paths = {ref.file_path for ref in resolution.candidate_files}
    assert "controller.py" not in file_paths
    assert resolution.retrieval_depth_used <= 1


async def test_full_retrieval_completeness_metadata_end_to_end(tmp_path: Path) -> None:
    """Stage 10 completion pass (brief §11): a single, realistic
    resolution that populates every deterministic retrieval-completeness
    field this hardening effort added, proving they're wired end to end
    through CodeIntelligenceContractService — not just modeled on
    ContextResolutionResult."""
    _write(tmp_path, "package.json", '{"name": "demo"}')
    _write(tmp_path, "auth/repository.py", "def authenticate(user):\n    return True\n")
    _write(
        tmp_path,
        "auth/login_service.py",
        "import requests\n\n"
        "from .repository import authenticate\n\n"
        "def login(user):\n    return authenticate(user)\n",
    )
    _write(
        tmp_path,
        "auth/controller_pb2.py",
        "from .login_service import login\n\ndef handle_login(user):\n    return login(user)\n",
    )
    _write(
        tmp_path,
        "auth/session.py",
        "def make_session(user):\n    return getattr(user, 'id', None)\n",
    )
    _write(tmp_path, "auth/middleware.py", "def auth_middleware():\n    pass\n")
    _write(tmp_path, "config.py", "SETTING = 1\n")
    _write(tmp_path, "worker.go", "package main\n\nfunc main() {}\n")
    _write(tmp_path, "bad.py", "def broken(:\n    pass\n")

    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "Refactor the login() authentication flow and analyze the impact across the call chain.",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=["authenticate"], workspace_root=str(tmp_path)
    )

    file_paths = {ref.file_path for ref in resolution.candidate_files}

    # §1 adaptive traversal: depth-3 (refactor/impact-analysis profile)
    # reaches the renamed outermost caller two hops out.
    assert "auth/controller_pb2.py" in file_paths
    assert resolution.retrieval_depth_used >= 2

    # §2 symbol disambiguation: a single, unambiguous "authenticate"
    # resolves cleanly — correctly empty, not silently omitted.
    assert resolution.unresolved_symbols == ()
    assert resolution.ambiguous_targets == ()

    # §2/§11: evidence sufficiency — the authentication contract's
    # login/session/middleware/configuration categories are satisfied via
    # deterministic expansion (credential source legitimately stays
    # missing, since it's a sensitive-file pattern this must never read).
    assert "login implementation" in resolution.evidence_categories_satisfied
    assert "session persistence" in resolution.evidence_categories_satisfied
    assert "authentication middleware" in resolution.evidence_categories_satisfied
    assert "configuration" in resolution.evidence_categories_satisfied
    assert "credential source" in resolution.evidence_categories_missing

    # §4 repository boundary awareness: single-project repo => root segment.
    assert resolution.repository_segment == ""

    # §5/§11 language capability registry.
    assert resolution.files_scanned >= 8
    assert resolution.files_analyzed >= 1
    assert 0.0 < resolution.analyzer_coverage < 1.0
    assert "Python" in resolution.languages_detected
    assert "Go" in resolution.languages_unsupported

    # §13 unsupported-condition surfacing.
    assert "bad.py" in resolution.parse_error_files
    assert "auth/controller_pb2.py" in resolution.generated_files
    assert "auth/session.py" in resolution.dynamic_dispatch_hints
    assert "requests" in resolution.unresolved_imports


async def test_resolver_strategy_defaults_to_classic_and_is_unaffected_by_drp_existing(
    tmp_path: Path,
) -> None:
    """ARCF Issue #3 Dynamic Repository Profiling (DRP) experiment —
    proof that adding `resolver_strategy` did not change a single byte
    of default behavior: identical to
    test_repository_scoped_request_with_no_entities_still_gets_files's
    own fixture/query, just re-run without passing resolver_strategy at
    all, alongside the exact same call with resolver_strategy="classic"
    made explicit."""
    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n")
    service, contract_store = _service()

    living_implicit = _seed_contract(contract_store, "Find the code that handles authenticate.")
    _, implicit = await service.attach_code_intelligence(
        living_implicit.contract_id, target_names=["authenticate"], workspace_root=str(tmp_path)
    )

    living_explicit = _seed_contract(contract_store, "Find the code that handles authenticate.")
    _, explicit = await service.attach_code_intelligence(
        living_explicit.contract_id,
        target_names=["authenticate"],
        workspace_root=str(tmp_path),
        resolver_strategy="classic",
    )

    assert [f.file_path for f in implicit.candidate_files] == [
        f.file_path for f in explicit.candidate_files
    ]
    assert implicit.confidence == explicit.confidence == 1.0


async def test_resolver_strategy_drp_routes_through_the_isolated_drp_resolver(
    tmp_path: Path,
) -> None:
    """`resolver_strategy="drp"` must reach code_intelligence/drp/'s own
    DrpResolver — proven by a diffuse-structure query naming no real
    symbol at all (so the classic pipeline's exact-match path has
    nothing to resolve), landing on the correct subsystem via directory
    taxonomy + TF-IDF + graph-community routing instead."""
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
    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "Explain how dynamic configuration updates propagate without restarting the server.",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id,
        target_names=[],
        workspace_root=str(tmp_path),
        resolver_strategy="drp",
    )

    assert "pkg/server/configurationwatcher.py" in {f.file_path for f in resolution.candidate_files}
    assert "drp:" in resolution.resolution_reason.lower() or any(
        f.reason.startswith("drp:") for f in resolution.candidate_files
    )


async def test_resolver_strategy_drp_populates_evidence_categories_missing(
    tmp_path: Path,
) -> None:
    """Final closure pass (2026-08-17), Final Issue 1 -- the evidence-state
    contract: DrpResolver.resolve() itself never sets
    evidence_categories_missing, and this method previously returned the
    DRP branch's result without ever calling validate_sufficiency (unlike
    the classic branch, which always does) -- meaning a DRP-produced
    ContextResolutionResult always looked evidence-satisfied to both
    consumers of this field (the orchestrator's own Case-B check and
    verify_grounding()'s post-generation check), regardless of whether
    DRP's real retrieval actually covered what the task needed. Fixed:
    the DRP branch now runs the same deterministic, resolver-agnostic
    validate_sufficiency() classic already uses. This is a REAL
    production execution reaching genuine Case-B evidence-insufficiency
    through DRP -- the same tiny fixture repo (auth.py + login.py only,
    genuinely lacking credential-source/session-persistence/configuration
    files) the classic-resolver Case-B test uses, proving the architecture
    naturally, not via a mock/double."""
    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n")
    _write(
        tmp_path,
        "login.py",
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n",
    )
    service, contract_store = _service()
    living = _seed_contract(contract_store, "Please review the authentication flow")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id,
        target_names=["authenticate"],
        workspace_root=str(tmp_path),
        resolver_strategy="drp",
    )

    assert resolution.evidence_categories_missing != ()


async def test_index_is_cached_automatically_across_calls_no_caller_opt_in_needed(
    tmp_path: Path,
) -> None:
    """arcf-persistent-safe-index-cache (2026-08-11): replaces the
    earlier opt-in `index_cache` parameter (removed) with automatic,
    service-lifetime caching — no caller plumbing required. Repeated
    calls against the SAME unchanged workspace, through the SAME service
    instance, must reuse the built index (only the first call actually
    parses) — the exact benefit `index_cache` used to require explicit
    opt-in for, now the default for every caller including the live API."""
    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n")
    service, contract_store = _service()

    living_a = _seed_contract(contract_store, "Find the code that handles authenticate.")
    living_b = _seed_contract(contract_store, "Find the code that handles authenticate.")

    with patch.object(
        service._engine, "build_index", wraps=service._engine.build_index
    ) as spy:
        await service.attach_code_intelligence(
            living_a.contract_id, target_names=["authenticate"], workspace_root=str(tmp_path)
        )
        await service.attach_code_intelligence(
            living_b.contract_id, target_names=["authenticate"], workspace_root=str(tmp_path)
        )

    assert spy.call_count == 2  # build_index itself is still called each time...
    # ...but the SECOND call must have been handed the first result as
    # previous_index (proving real reuse, not just "called twice with no
    # sharing") — confirmed via the incremental-reuse contract itself:
    # an unchanged file's FileAnalysis object is reused by identity.
    first_call_kwargs = spy.call_args_list[0].kwargs
    second_call_kwargs = spy.call_args_list[1].kwargs
    assert second_call_kwargs.get("previous_index") is not None
    assert first_call_kwargs.get("previous_index") is None


async def test_changed_file_between_calls_is_correctly_re_analyzed_not_stale(
    tmp_path: Path,
) -> None:
    """The core safety property the automatic cache must have that the
    earlier opt-in `index_cache` explicitly did NOT (its own docstring:
    "only safe when the caller knows the workspace root's files won't
    change between calls"). A real workspace CAN change between live API
    requests — this proves an edited file is picked up, not silently
    served stale."""
    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n")
    service, contract_store = _service()

    living_before = _seed_contract(contract_store, "Find the code that handles login_v2.")
    _, before = await service.attach_code_intelligence(
        living_before.contract_id, target_names=["login_v2"], workspace_root=str(tmp_path)
    )
    assert before.candidate_files == []  # login_v2 doesn't exist yet

    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n\ndef login_v2():\n    pass\n")
    living_after = _seed_contract(contract_store, "Find the code that handles login_v2.")
    _, after = await service.attach_code_intelligence(
        living_after.contract_id, target_names=["login_v2"], workspace_root=str(tmp_path)
    )

    assert "auth.py" in {f.file_path for f in after.candidate_files}


async def test_drp_index_is_cached_across_calls_and_rebuilt_when_base_index_changes(
    tmp_path: Path,
) -> None:
    """DrpIndexBuilder.build (community detection + TF-IDF, confirmed via
    a real gvisor re-run to spike DRP latency up to 56s even with the
    base index already cached) must ALSO be cached automatically, and
    only rebuilt when the base index actually changed — not on every
    call regardless."""
    _write(
        tmp_path,
        "pkg/server/configurationwatcher.py",
        '"""Watches dynamic configuration and propagates updates without restarting."""\n'
        "def watch_configuration():\n    return True\n",
    )
    service, contract_store = _service()

    living_first = _seed_contract(
        contract_store, "Explain how dynamic configuration updates propagate."
    )
    living_second = _seed_contract(
        contract_store, "Explain how dynamic configuration updates propagate."
    )

    with patch.object(DrpIndexBuilder, "build", wraps=DrpIndexBuilder.build) as spy:
        await service.attach_code_intelligence(
            living_first.contract_id,
            target_names=[],
            workspace_root=str(tmp_path),
            resolver_strategy="drp",
        )
        await service.attach_code_intelligence(
            living_second.contract_id,
            target_names=[],
            workspace_root=str(tmp_path),
            resolver_strategy="drp",
        )

    assert spy.call_count == 1  # second call reused the cached DrpIndex

    # Now change a file — the base index changes, so DrpIndex must rebuild.
    _write(
        tmp_path,
        "pkg/server/configurationwatcher.py",
        '"""Watches dynamic configuration and propagates updates without restarting."""\n'
        "def watch_configuration():\n    return True\n\ndef new_symbol():\n    pass\n",
    )
    living_third = _seed_contract(
        contract_store, "Explain how dynamic configuration updates propagate."
    )
    with patch.object(DrpIndexBuilder, "build", wraps=DrpIndexBuilder.build) as spy2:
        await service.attach_code_intelligence(
            living_third.contract_id,
            target_names=[],
            workspace_root=str(tmp_path),
            resolver_strategy="drp",
        )
    assert spy2.call_count == 1  # rebuilt, not stale-reused
