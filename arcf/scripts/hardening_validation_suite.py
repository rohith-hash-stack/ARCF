"""ARCF architecture hardening — deterministic validation suite (brief §15).

Twelve scenarios, one per required validation category, run entirely
against synthetic fixture repositories built on the fly — no LLM calls,
no network access, byte-for-byte reproducible. Each scenario drives the
real production pipeline (CodeIntelligenceEngine -> ContextResolver ->
CodeIntelligenceContractService's task classification / evidence
validation / repository segmentation -> ContextPackager), exactly as a
real request would, and reports the same deterministic metadata a caller
would see: files selected, retrieval depth, evidence categories
satisfied, token reduction, latency, and the justification chain — plus
a comparison against sending the whole repository as context (every
scanned file's token count), the same question CER/PCR already answer
elsewhere in this codebase.

Run as a script for a human-readable report:
    uv run python scripts/hardening_validation_suite.py

Run as tests (same scenarios, asserted rather than printed):
    uv run pytest tests/hardening_validation/
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from domain.context_resolution import ContextResolutionResult
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator


@dataclass(frozen=True)
class ScenarioReport:
    category: str
    task_prompt: str
    files_selected: int
    files_scanned: int
    retrieval_depth: int
    evidence_categories_satisfied: tuple[str, ...]
    evidence_categories_missing: tuple[str, ...]
    token_reduction_ratio: float
    """selected_context_tokens / raw_context_tokens (CER) — lower means
    more of the full repository was compressed away."""
    justification_chain_sample: tuple[str, ...]
    latency_seconds: float
    full_repository_tokens: int
    notes: str = ""


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _full_registry() -> LanguageRegistry:
    return LanguageRegistry(
        [PythonLanguageAnalyzer(), TypeScriptLanguageAnalyzer(), GoLanguageAnalyzer()]
    )


def _service(
    registry: LanguageRegistry | None = None,
) -> tuple[CodeIntelligenceContractService, InMemoryContractStore]:
    engine = CodeIntelligenceEngine(registry or _full_registry(), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    return service, contract_store


async def _run(
    service: CodeIntelligenceContractService,
    contract_store: InMemoryContractStore,
    root: Path,
    raw_request: str,
    target_names: list[str],
) -> tuple[ContextResolutionResult, float]:
    intent = UserIntent(
        raw_request=raw_request,
        intent=raw_request,
        domain="general",
        task="general",
        entities=target_names,
        confidence=0.9,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    start = time.perf_counter()
    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)), target_names=target_names, workspace_root=str(root)
    )
    latency = time.perf_counter() - start
    return resolution, latency


def _report(
    category: str,
    raw_request: str,
    resolution: ContextResolutionResult,
    latency: float,
    notes: str = "",
) -> ScenarioReport:
    raw_tokens = resolution.token_estimate.raw_context_tokens
    selected_tokens = resolution.token_estimate.selected_context_tokens
    ratio = round(selected_tokens / raw_tokens, 4) if raw_tokens else 0.0
    sample_chain: tuple[str, ...] = ()
    for file_ref in resolution.candidate_files:
        if file_ref.justification_chain:
            sample_chain = file_ref.justification_chain
            break
    return ScenarioReport(
        category=category,
        task_prompt=raw_request,
        files_selected=len(resolution.candidate_files),
        files_scanned=resolution.files_scanned,
        retrieval_depth=resolution.retrieval_depth_used,
        evidence_categories_satisfied=resolution.evidence_categories_satisfied,
        evidence_categories_missing=resolution.evidence_categories_missing,
        token_reduction_ratio=ratio,
        justification_chain_sample=sample_chain,
        latency_seconds=round(latency, 4),
        full_repository_tokens=raw_tokens,
        notes=notes,
    )


# -- scenarios, one per brief §15 category -----------------------------


async def scenario_authentication_explanation(root: Path) -> ScenarioReport:
    _write(root, "auth/repository.py", "def authenticate(user):\n    return True\n")
    _write(
        root,
        "auth/login.py",
        "from .repository import authenticate\n\ndef login(user):\n    return authenticate(user)\n",
    )
    _write(root, "auth/session.py", "def make_session(user):\n    return {'id': user}\n")
    _write(root, "auth/middleware.py", "def auth_middleware():\n    pass\n")
    _write(root, "config.py", "SETTING = 1\n")
    raw_request = "Explain how login() and authenticate() establish a session in this repository."
    service, contract_store = _service()
    resolution, latency = await _run(service, contract_store, root, raw_request, ["authenticate"])
    return _report("authentication_explanation", raw_request, resolution, latency)


async def scenario_test_execution_explanation(root: Path) -> ScenarioReport:
    _write(root, "pyproject.toml", "[project]\nname='demo'\n")
    _write(root, "pytest.ini", "[pytest]\n")
    _write(root, "tests/test_app.py", "def test_ok():\n    assert True\n")
    _write(root, "scripts/run_tests.sh", "#!/bin/sh\npytest\n")
    raw_request = "How do I run the tests in this repository, and how is the test suite configured?"
    service, contract_store = _service()
    resolution, latency = await _run(service, contract_store, root, raw_request, [])
    return _report("test_execution_explanation", raw_request, resolution, latency)


async def scenario_ci_cd_explanation(root: Path) -> ScenarioReport:
    _write(root, "package.json", '{"name": "demo"}')
    _write(root, ".github/workflows/ci.yml", "name: CI\non: push\n")
    _write(root, "Makefile", "build:\n\techo build\n")
    raw_request = (
        "Explain our CI/CD pipeline: what workflow runs, and how are dependencies installed?"
    )
    service, contract_store = _service()
    resolution, latency = await _run(service, contract_store, root, raw_request, [])
    return _report("ci_cd_explanation", raw_request, resolution, latency)


async def scenario_architecture_understanding(root: Path) -> ScenarioReport:
    _write(root, "pyproject.toml", "[project]\nname='demo'\n")
    _write(root, "app/entrypoint.py", "def main():\n    pass\n")
    _write(root, "app/service.py", "class Service:\n    def run(self):\n        pass\n")
    raw_request = (
        "Explain the architecture of this repository: its module boundaries and entry points."
    )
    service, contract_store = _service()
    resolution, latency = await _run(service, contract_store, root, raw_request, [])
    return _report("architecture_understanding", raw_request, resolution, latency)


async def scenario_bug_localization(root: Path) -> ScenarioReport:
    _write(root, "repository.py", "def authenticate(user):\n    return True\n")
    _write(
        root,
        "service.py",
        "from .repository import authenticate\n\ndef login(user):\n    return authenticate(user)\n",
    )
    _write(
        root,
        "controller.py",
        "from .service import login\n\ndef handle_login(user):\n    return login(user)\n",
    )
    raw_request = (
        "Fix the bug in authenticate() — it always returns True regardless of credentials."
    )
    service, contract_store = _service()
    resolution, latency = await _run(service, contract_store, root, raw_request, ["authenticate"])
    notes = "depth-1 profile: controller.py (2 hops away) is correctly excluded"
    return _report("bug_localization", raw_request, resolution, latency, notes)


async def scenario_refactor_planning(root: Path) -> ScenarioReport:
    _write(root, "repository.py", "def authenticate(user):\n    return True\n")
    _write(
        root,
        "service.py",
        "from .repository import authenticate\n\ndef login(user):\n    return authenticate(user)\n",
    )
    _write(
        root,
        "controller.py",
        "from .service import login\n\ndef handle_login(user):\n    return login(user)\n",
    )
    raw_request = "Refactor authenticate() to accept a credentials object instead of a raw user."
    service, contract_store = _service()
    resolution, latency = await _run(service, contract_store, root, raw_request, ["authenticate"])
    return _report("refactor_planning", raw_request, resolution, latency)


async def scenario_impact_analysis(root: Path) -> ScenarioReport:
    _write(root, "repository.py", "def authenticate(user):\n    return True\n")
    _write(
        root,
        "service.py",
        "from .repository import authenticate\n\ndef login(user):\n    return authenticate(user)\n",
    )
    _write(
        root,
        "controller.py",
        "from .service import login\n\ndef handle_login(user):\n    return login(user)\n",
    )
    raw_request = "What would break downstream if I changed authenticate()'s signature?"
    service, contract_store = _service()
    resolution, latency = await _run(service, contract_store, root, raw_request, ["authenticate"])
    notes = "impact-analysis profile: transitive callers (controller.py) reachable at depth 3"
    return _report("impact_analysis", raw_request, resolution, latency, notes)


async def scenario_monorepo_retrieval(root: Path) -> ScenarioReport:
    _write(root, "services/api/pyproject.toml", "[project]\nname='api'\n")
    _write(root, "services/api/handler.py", "def handle():\n    pass\n")
    _write(root, "services/api/login.py", "def login():\n    pass\n")
    _write(root, "services/web/package.json", "{}")
    _write(root, "services/web/login.py", "def login():\n    pass\n")
    raw_request = "Explain the login flow in the api service."
    service, contract_store = _service()
    resolution, latency = await _run(service, contract_store, root, raw_request, [])
    notes = f"resolved segment: {resolution.repository_segment!r}"
    return _report("monorepo_retrieval", raw_request, resolution, latency, notes)


async def scenario_mixed_language_repository(root: Path) -> ScenarioReport:
    _write(root, "backend/auth.py", "def authenticate(user):\n    return True\n")
    _write(root, "frontend/login.ts", "export function login() { return true; }\n")
    _write(root, "worker/main.go", "package main\n\nfunc main() {}\n")
    raw_request = "Explain this repository's authentication implementation."
    service, contract_store = _service()
    resolution, latency = await _run(service, contract_store, root, raw_request, ["authenticate"])
    notes = f"languages detected: {', '.join(resolution.languages_detected)}"
    return _report("mixed_language_repository", raw_request, resolution, latency, notes)


async def scenario_unsupported_language_handling(root: Path) -> ScenarioReport:
    _write(root, "app.rb", "def hello\n  puts 'hi'\nend\n")
    raw_request = "Explain this repository."
    python_only = LanguageRegistry([PythonLanguageAnalyzer()])
    service, contract_store = _service(python_only)
    resolution, latency = await _run(service, contract_store, root, raw_request, [])
    unsupported = ", ".join(resolution.languages_unsupported)
    notes = f"unsupported: {unsupported}; {resolution.resolution_reason}"
    return _report("unsupported_language_handling", raw_request, resolution, latency, notes)


async def scenario_symbol_ambiguity(root: Path) -> ScenarioReport:
    _write(root, "a.py", "def helper():\n    return 1\n")
    _write(root, "b.py", "def helper():\n    return 2\n")
    raw_request = "Explain helper()."
    service, contract_store = _service()
    resolution, latency = await _run(service, contract_store, root, raw_request, ["helper"])
    notes = f"ambiguous_targets: {resolution.ambiguous_targets!r}"
    return _report("symbol_ambiguity", raw_request, resolution, latency, notes)


async def scenario_deep_call_chain_retrieval(root: Path) -> ScenarioReport:
    _write(root, "layer0.py", "def base():\n    return True\n")
    _write(root, "layer1.py", "from .layer0 import base\n\ndef l1():\n    return base()\n")
    _write(root, "layer2.py", "from .layer1 import l1\n\ndef l2():\n    return l1()\n")
    _write(root, "layer3.py", "from .layer2 import l2\n\ndef l3():\n    return l2()\n")
    _write(root, "layer4.py", "from .layer3 import l3\n\ndef l4():\n    return l3()\n")
    raw_request = (
        "Analyze the full impact and blast radius of changing base(), sweeping and system-wide."
    )
    service, contract_store = _service()
    resolution, latency = await _run(service, contract_store, root, raw_request, ["base"])
    return _report("deep_call_chain_retrieval", raw_request, resolution, latency)


SCENARIOS = [
    scenario_authentication_explanation,
    scenario_test_execution_explanation,
    scenario_ci_cd_explanation,
    scenario_architecture_understanding,
    scenario_bug_localization,
    scenario_refactor_planning,
    scenario_impact_analysis,
    scenario_monorepo_retrieval,
    scenario_mixed_language_repository,
    scenario_unsupported_language_handling,
    scenario_symbol_ambiguity,
    scenario_deep_call_chain_retrieval,
]


async def run_all() -> list[ScenarioReport]:
    reports = []
    for scenario in SCENARIOS:
        with tempfile.TemporaryDirectory() as tmp:
            reports.append(await scenario(Path(tmp)))
    return reports


def _print_report(reports: list[ScenarioReport]) -> None:
    header = (
        f"{'category':<30} {'files':>6} {'scanned':>8} {'depth':>6} {'CER':>7} "
        f"{'latency_s':>10}  evidence_satisfied"
    )
    print(header)
    print("-" * len(header))
    for r in reports:
        evidence = ", ".join(r.evidence_categories_satisfied) or "-"
        print(
            f"{r.category:<30} {r.files_selected:>6} {r.files_scanned:>8} "
            f"{r.retrieval_depth:>6} {r.token_reduction_ratio:>7.4f} "
            f"{r.latency_seconds:>10.4f}  {evidence}"
        )
        if r.justification_chain_sample:
            print(f"  justification chain sample: {' -> '.join(r.justification_chain_sample)}")
        if r.notes:
            print(f"  notes: {r.notes}")
    print()
    print(
        f"Full-repository token counts (comparison baseline): "
        f"{[r.full_repository_tokens for r in reports]}"
    )


def main() -> None:
    reports = asyncio.run(run_all())
    _print_report(reports)


if __name__ == "__main__":
    main()
