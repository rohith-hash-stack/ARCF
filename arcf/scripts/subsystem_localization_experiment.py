"""Subsystem-localization root-cause validation experiment (2026-08-08).

Hypothesis under test (context/subsystem_localizer.py's own docstring):
the dominant failure mode found in root-cause analysis — an entity-less
conceptual query's lexical probe fanning out to a same-rooted symbol in
an unrelated repository subsystem — is a semantic-anchor-selection
problem, fixable by localizing to a query-relevant subsystem BEFORE
lexical-probe recovery runs, without redesigning ARCF, adding
embeddings, or adding a new language analyzer.

Runs the real benchmarked SQLAlchemy query through
CodeIntelligenceContractService.attach_code_intelligence() twice against
the real cloned repository — once with enable_subsystem_localization=False
(today's shipped behavior) and once with True (the experimental arm) —
using the SAME real SLM-1-extracted entities for both, so the only
variable between arms is the flag itself. Retrieval-only: no final
generation LLM call, matching the batch1/batch2 diagnostic scripts'
own "never sends a whole repository as context" cost discipline.

Usage:
    uv run python scripts/subsystem_localization_experiment.py --repo-path <path to cloned sqlalchemy>
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from contracts.intent_extraction import IntentExtractor
from domain.contract import Contract
from domain.context_resolution import ContextResolutionResult
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LiteLLMClient

QUERY = (
    "Explain how lazy loading differs from eager loading internally and "
    "what SQL each strategy generates."
)
CANONICAL_FILES = ("lib/sqlalchemy/orm/loading.py", "lib/sqlalchemy/orm/strategies.py")
RESULTS_FILE = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "session_2026-08-08_data"
    / "subsystem_localization_experiment_results.json"
)


@dataclass(frozen=True)
class ArmResult:
    label: str
    candidate_file_count: int
    input_tokens: int
    top_20_files: list[str]
    canonical_files_retrieved: dict[str, bool]
    irrelevant_subsystem_files: list[str]
    resolution_reason: str
    total_latency_seconds: float = 0.0
    """Wall-clock time for the whole attach_code_intelligence() call —
    scan + index build + resolution combined. Not broken into
    per-pipeline-stage timings: this experiment validates retrieval
    quality (does it find the right files, does it reduce fan-out), not
    latency, and CodeIntelligenceContractService has no existing
    per-stage timer to read without adding one — noted honestly rather
    than fabricating a stage breakdown."""


def _irrelevant_files(candidate_paths: list[str]) -> list[str]:
    irrelevant_markers = ("dialects/", "cache", "/testing/")
    return [
        path
        for path in candidate_paths
        if any(marker in path for marker in irrelevant_markers)
        and path not in CANONICAL_FILES
    ]


def _summarize(
    label: str, resolution: ContextResolutionResult, elapsed_seconds: float
) -> ArmResult:
    paths = sorted(ref.file_path for ref in resolution.candidate_files)
    return ArmResult(
        label=label,
        candidate_file_count=len(paths),
        input_tokens=resolution.token_estimate.selected_context_tokens,
        top_20_files=paths[:20],
        canonical_files_retrieved={f: f in paths for f in CANONICAL_FILES},
        irrelevant_subsystem_files=_irrelevant_files(paths),
        resolution_reason=resolution.resolution_reason,
        total_latency_seconds=round(elapsed_seconds, 3),
    )


async def _run_arm(
    root: Path,
    entities: list[str],
    intent: UserIntent,
    enable_localization: bool,
    enable_ranking: bool,
    label: str,
) -> ArmResult:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    start = asyncio.get_event_loop().time()
    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)),
        target_names=entities,
        workspace_root=str(root),
        enable_subsystem_localization=enable_localization,
        enable_ranked_seed_selection=enable_ranking,
    )
    elapsed = asyncio.get_event_loop().time() - start
    print(f"[{label}] resolved in {elapsed:.2f}s")
    return _summarize(label, resolution, elapsed)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    args = parser.parse_args()
    root = Path(args.repo_path)

    # Real SLM-1 call — small, cheap, run once so both arms see identical
    # extracted entities; only enable_subsystem_localization differs
    # between the two attach_code_intelligence() calls below.
    extractor = IntentExtractor(
        LiteLLMClient(max_retries=3, base_delay_seconds=0.5), model="gpt-4o-mini"
    )
    raw, _llm_response = await extractor.extract(QUERY)
    entities = list(raw.entities)
    intent = UserIntent(
        raw_request=QUERY,
        intent=raw.intent_summary,
        domain=raw.domain,
        task=raw.task,
        entities=entities,
        confidence=raw.self_reported_confidence,
    )
    print(f"SLM-1 entities extracted: {entities or '(none)'}")

    baseline = await _run_arm(root, entities, intent, False, False, "baseline (both flags off)")
    localized = await _run_arm(
        root, entities, intent, True, False, "localization only (2026-08-08 run)"
    )
    ranked = await _run_arm(
        root, entities, intent, True, True, "localization + ranked seed selection"
    )

    def _passes(arm: ArmResult) -> bool:
        return all(arm.canonical_files_retrieved.values()) and len(
            arm.irrelevant_subsystem_files
        ) < len(baseline.irrelevant_subsystem_files)

    output = {
        "query": QUERY,
        "entities_extracted": entities,
        "canonical_files": list(CANONICAL_FILES),
        "baseline": asdict(baseline),
        "localization_only": asdict(localized),
        "localization_plus_ranked_seed_selection": asdict(ranked),
        "success_criteria": (
            "Retrieves both canonical loading-strategy files AND reduces "
            "fan-out into irrelevant subsystems (dialects/, cache, testing/), "
            "relative to baseline."
        ),
        "localization_only_success": _passes(localized),
        "localization_plus_ranking_success": _passes(ranked),
    }

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(output, indent=2), encoding="utf-8")

    for arm in (baseline, localized, ranked):
        print(f"\n=== {arm.label.upper()} ===")
        print(json.dumps(asdict(arm), indent=2))
    print(f"\nlocalization_only_success: {output['localization_only_success']}")
    print(f"localization_plus_ranking_success: {output['localization_plus_ranking_success']}")
    print(f"Results written to {RESULTS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
