"""slm1_bypass_experiment.py — falsification experiment, resolver-only, no
new LLM calls (reuses already-stored entities_extracted from the sweep as
the "real SLM-1 output" side of the comparison). Touches no ARCF source.

Hypothesis: SLM-1 intent extraction is a whole extra LLM round-trip every
classic/DRP query pays for, that direct doesn't. Before trying to replace
it with something cheaper, check whether it's even doing meaningful work
in the FIRST place — target_names feeds ContextResolver's Tier 1 exact-
match path (SymbolIndex.find_by_name/find_by_qualified_name — confirmed
by reading symbol_index.py: plain dict lookup, EXACT string equality, no
fuzzy/substring matching), while Tier 3 (lexical_symbol_probe, anchor
classification's fallback) already runs off the RAW QUERY TEXT directly,
independent of target_names entirely. SLM-1's own entities are natural-
language noun phrases ("custom matcher", "validation logic") which mostly
CAN'T exactly match a real identifier (identifiers don't contain spaces).
If true, target_names is already contributing little beyond what Tier 3
finds on its own for most queries — meaning the round-trip might already
be mostly wasted, independent of whether a cheaper replacement exists.

Success criterion (stated up front): compare classic resolution WITH the
real stored SLM-1 entities as target_names (today's production behavior)
against WITHOUT (target_names=[], forcing Tier 3 to do all the work) for
all 12 sweep queries. If candidate_files/confidence/resolution_reason are
IDENTICAL for the queries where SLM-1 found entities (not just the 8/12
where it already found nothing), that confirms target_names is currently
a no-op for those cases — SLM-1's round-trip could be skipped with zero
resolution-quality change, at least for classic. If removing target_names
measurably changes/degrades results, that falsifies the "already wasted"
hypothesis and the round-trip is doing real work worth keeping.

Extended (2026-08-11, same session): the classic pass alone found 11/12
cases unaffected (9 byte-identical candidate sets, 2 more identical in
candidates+confidence with only resolution_reason text differing) and one
real difference (gvisor "syscall") where removing SLM-1 arguably improved
the candidate pool, not degraded it. This second pass runs the SAME
WITH/WITHOUT comparison through resolver_strategy="drp" — DRP folds
target_names into its own query text (drp_resolver.py's own docstring:
"target_names... are folded into the query text rather than driving a
separate lookup path") rather than exact-matching them, a DIFFERENT
mechanism from classic's Tier 1, so classic's result doesn't automatically
generalize to DRP and needs its own direct measurement.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.cpp_analyzer import CppLanguageAnalyzer
from code_intelligence.languages.csharp_analyzer import CSharpLanguageAnalyzer
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.java_analyzer import JavaLanguageAnalyzer
from code_intelligence.languages.kotlin_analyzer import KotlinLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.rust_analyzer import RustLanguageAnalyzer
from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator

SWEEP_DIR = Path(__file__).resolve().parent.parent / "docs" / "repo_query_answers"
SCRATCH_A = Path(
    "C:/Users/VASIGA~1/AppData/Local/Temp/claude/C--Users-VasiganiRohitBabu-Desktop-Claude/"
    "9e0bfde9-a14d-4265-b142-a579ae3668d3/scratchpad/repos"
)
REPO_ROOTS = {
    "googletest": SCRATCH_A / "googletest",
    "flatbuffers": SCRATCH_A / "flatbuffers",
    "gvisor": SCRATCH_A / "gvisor",
}


def _full_registry() -> LanguageRegistry:
    return LanguageRegistry(
        [
            PythonLanguageAnalyzer(),
            TypeScriptLanguageAnalyzer(),
            GoLanguageAnalyzer(),
            JavaLanguageAnalyzer(),
            CSharpLanguageAnalyzer(),
            KotlinLanguageAnalyzer(),
            CppLanguageAnalyzer(),
            RustLanguageAnalyzer(),
        ]
    )


async def _resolve(
    service: CodeIntelligenceContractService,
    contract_store: InMemoryContractStore,
    root: Path,
    query: str,
    target_names: list[str],
    resolver_strategy: str,
) -> dict:
    intent = UserIntent(
        raw_request=query, intent="diagnose", domain="diagnostic",
        task="diagnostic", entities=target_names, confidence=0.5,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)
    classic_flags = (
        {"enable_anchor_classification": True, "enable_confidence_propagation": True}
        if resolver_strategy == "classic"
        else {}
    )
    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)),
        target_names=target_names,
        workspace_root=str(root),
        resolver_strategy=resolver_strategy,
        **classic_flags,
    )
    return {
        "candidate_files": sorted(f.file_path for f in resolution.candidate_files),
        "confidence": resolution.confidence,
        "resolution_reason": resolution.resolution_reason,
    }


async def _run_strategy(
    service: CodeIntelligenceContractService,
    contract_store: InMemoryContractStore,
    resolver_strategy: str,
) -> None:
    identical_candidates = 0
    identical_everything = 0
    different = 0
    total = 0
    for f in sorted(SWEEP_DIR.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        repo_name = d["repo"]
        root = REPO_ROOTS.get(repo_name)
        if root is None or not root.is_dir():
            print(f"SKIP {repo_name}: not cloned")
            continue
        query = d["query"]
        entities = d["entities_extracted"]
        total += 1

        with_slm1 = await _resolve(service, contract_store, root, query, entities, resolver_strategy)
        without_slm1 = await _resolve(service, contract_store, root, query, [], resolver_strategy)

        same_candidates = with_slm1["candidate_files"] == without_slm1["candidate_files"] and (
            with_slm1["confidence"] == without_slm1["confidence"]
        )
        same_everything = with_slm1 == without_slm1
        identical_candidates += same_candidates
        identical_everything += same_everything
        different += not same_candidates

        tag = "SAME" if same_candidates else "DIFFERENT"
        print(f"\n=== [{resolver_strategy}] {repo_name} | entities={entities!r} | {tag} ===")
        print(f"  query: {query[:70]}")
        if not same_candidates:
            print(f"  WITH SLM-1    candidates={with_slm1['candidate_files']}")
            print(f"                confidence={with_slm1['confidence']:.3f}")
            print(f"                reason={with_slm1['resolution_reason'][:100]}")
            print(f"  WITHOUT SLM-1 candidates={without_slm1['candidate_files']}")
            print(f"                confidence={without_slm1['confidence']:.3f}")
            print(f"                reason={without_slm1['resolution_reason'][:100]}")
        elif not same_everything:
            print(f"  (candidates+confidence identical, resolution_reason text only differs)")

    print(
        f"\n=== [{resolver_strategy}] Summary: {identical_candidates}/{total} identical "
        f"candidates+confidence ({identical_everything}/{total} byte-identical incl. reason text), "
        f"{different}/{total} substantively different ==="
    )


async def main() -> None:
    engine = CodeIntelligenceEngine(_full_registry(), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )

    await _run_strategy(service, contract_store, "classic")
    await _run_strategy(service, contract_store, "drp")


if __name__ == "__main__":
    asyncio.run(main())
