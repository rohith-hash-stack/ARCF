"""callgraph_fanout_impact_experiment.py — falsification experiment,
resolver-only, no LLM calls. Touches no ARCF source. Runs REAL,
unmodified classic resolution (CodeIntelligenceContractService.
attach_code_intelligence, the actual production path, not a synthetic
reimplementation) with target_names set to the exact common, ambiguous
identifiers found corrupted in package_specificity_experiment.py
("New": 159 same-named symbols, "Register": 38, all showing IDENTICAL
inflated caller counts from CallGraph's documented fan-out behavior).

Question under test (not assumed): does this actually visibly corrupt
classic's real candidate_files/resolution behavior in practice, or does
resolve_with_disambiguation's existing locality-based narrowing already
absorb most of the damage before hop-expansion runs? Two SEPARATE
mechanisms are in play and this experiment is designed to tell them
apart:
  (a) Tier 1's own exact-name resolution (ReferenceResolver.
      resolve_with_disambiguation) already applies locality narrowing
      (same file > same directory > import-reachable) when a name has
      multiple candidates — this MIGHT already substantially mitigate
      ambiguity at the matching step.
  (b) EVEN IF (a) correctly narrows to ONE specific symbol,
      ContextResolver.resolve()'s subsequent hop-expansion calls
      transitive_caller_symbols_of/transitive_callee_symbols_of on
      THAT symbol's id — and CallGraph's underlying stored caller/
      callee sets were built at index-construction time from
      name-ambiguous resolution, independent of which specific symbol
      gets picked later. So a correctly-disambiguated Tier 1 match could
      still have a corrupted, fan-out-inflated hop expansion.

Success criterion for "this needs fixing" (stated up front): if
resolving on "Register"/"New" against real Consul produces a
candidate_files set that's implausibly large (order of dozens+) and/or
visibly spans clearly-unrelated subsystems (auth, ACL, gRPC services,
CLI commands all appearing together for what should be one localized
concept), that's real, visible corruption in production behavior, not
just a theoretical concern. If resolve_with_disambiguation's existing
narrowing keeps results small and locally coherent despite the
underlying CallGraph corruption, the bug's PRACTICAL impact is limited
even though the raw data is provably wrong — a materially different,
lower-urgency conclusion.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator

SCRATCH_B = Path(
    "C:/Users/VASIGA~1/AppData/Local/Temp/claude/C--Users-VasiganiRohitBabu-Desktop-Claude/"
    "9e0bfde9-a14d-4265-b142-a579ae3668d3/scratchpad/pmi_repos"
)


async def run_case(
    service: CodeIntelligenceContractService,
    contract_store: InMemoryContractStore,
    root: Path,
    target_names: list[str],
    label: str,
) -> None:
    intent = UserIntent(
        raw_request=f"(diagnostic probe for target_names={target_names})",
        intent="diagnose", domain="diagnostic", task="diagnostic",
        entities=target_names, confidence=0.5,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)),
        target_names=target_names,
        workspace_root=str(root),
        resolver_strategy="classic",
        enable_anchor_classification=True,
        enable_confidence_propagation=True,
    )

    files = sorted(f.file_path for f in resolution.candidate_files)
    subsystems = sorted({str(Path(f).parent) for f in files})
    print(f"\n=== {label} | target_names={target_names!r} ===")
    print(f"  candidate_count={len(files)}  confidence={resolution.confidence:.3f}")
    print(f"  distinct subsystems touched: {len(subsystems)}")
    print(f"  resolution_reason: {resolution.resolution_reason[:150]}")
    print(f"  subsystems: {subsystems[:15]}")
    if len(files) <= 25:
        print(f"  files: {files}")


async def main() -> None:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    root = SCRATCH_B / "consul"

    # Common, provably-ambiguous names from package_specificity_experiment.py
    await run_case(service, contract_store, root, ["Register"], "Consul, ambiguous name (38 matches)")
    await run_case(service, contract_store, root, ["New"], "Consul, ambiguous name (159 matches)")
    # Control: a name that's NOT ambiguous (or far less so), for comparison.
    await run_case(service, contract_store, root, ["Agent"], "Consul, low-ambiguity type name (5 matches, 0 callers)")


if __name__ == "__main__":
    asyncio.run(main())
