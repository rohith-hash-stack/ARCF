"""grounding_structural_behavioral_precheck.py -- free deterministic
pre-check for checklist item #4 (arcf/CHECKLIST.md, Grounding Quality:
Structural vs. Behavioral Split), real Consul, no LLM calls, no source
changes yet. Same discipline as symbol_identity_audit_trail_verification.py
and negative_query_fpr_real_consul_check.py: check real data BEFORE writing
any metric code or success criteria.

Real, load-bearing finding already confirmed by directly running
classify_retrieval_task() against every BENCHMARK_TASKS query text
(scripts/validate_llm_grounding.py): ALL SIX classify to
RetrievalTaskType with TRAVERSAL_DEPTH == 1 in real production (task2
classifies to BUG_FIX via RepositoryScopeClassifier's "trace"+"service"
debugging trigger, not the REFACTOR_IMPACT_ANALYSIS its "downstream"
wording might suggest -- repository_scope is checked before impact
words in classify_retrieval_task's own branch order). This is the same
finding the (falsified, unmerged) UPS-suppression experiment made for
this exact benchmark suite -- confirmed independently here, not assumed
from that memory.

This script answers the real open question before designing the metric:
at the depth=1 every real query actually gets, do the real behavioral
ground-truth collaborator files (watch.go/binder.go/tls.go -- see
CHECKLIST.md item #4's own grounding notes) actually show up in
candidate_files at all, and via which OriginStage?

target_names are hand-specified from each task's own ground_truth_terms
(BENCHMARK_TASKS), not extracted via real SLM-1 -- same
determinism/cost/speed rationale as item #9's negative-query harness:
this is a structural pre-check of the resolver/locality mechanism, not
a test of SLM-1 entity extraction (a separate, already-documented axis
of noise -- see PROGRESS.md's "Benchmark noise floor").
"""

from __future__ import annotations

from pathlib import Path

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner

REPO_ROOT = Path("C:/Users/VasiganiRohitBabu/Desktop/Claude/.benchmark_repos/consul")

# (task_id, target_names, structural_files, behavioral_files) -- structural
# = entry-point/type definition file(s); behavioral = collaborator file(s)
# reached only via a real cross-file relationship (grepped directly against
# real Consul, see CHECKLIST.md item #4's own notes for the exact evidence
# per task before this script existed).
CASES = [
    (
        "task1_targeted_logic", ["Catalog", "Register"],
        ["agent/consul/catalog_endpoint.go"], [],
    ),
    (
        "task2_dependency_tracing", ["Cache", "UpdateEvent", "Notify"],
        ["agent/cache/cache.go"], ["agent/cache/watch.go"],
    ),
    (
        "task3_interface_type_contract", ["Config"],
        ["agent/config/config.go"], [],
    ),
    (
        "task4_refactoring_multifile", ["ACLBindingRuleList", "BindingRuleList", "Binder"],
        ["agent/consul/acl_endpoint.go"], ["agent/consul/auth/binder.go"],
    ),
    (
        "task5_ambiguous_common_name", ["New"],
        ["agent/cache/cache.go"], [],
    ),
    (
        "task6_path_hint_secondary_sibling", ["Prepopulate"],
        ["agent/cache/cache.go"], ["agent/auto-config/tls.go"],
    ),
]


def main() -> None:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(REPO_ROOT)
    index = engine.build_index(REPO_ROOT, scan.files)
    resolver = ContextResolver(index)

    for task_id, target_names, structural_files, behavioral_files in CASES:
        # depth=1 -- the real, confirmed production depth for every one of
        # these queries via classify_retrieval_task (see module docstring).
        result = resolver.resolve("ws1", "c1", str(REPO_ROOT), target_names, traversal_depth=1)
        by_path = {f.file_path: f for f in result.candidate_files}

        print(f"\n=== {task_id}  target_names={target_names!r}  candidates={len(by_path)} ===")
        for label, files in (("structural", structural_files), ("behavioral", behavioral_files)):
            for path in files:
                ref = by_path.get(path)
                if ref is None:
                    print(f"  [{label}] {path}: MISSING from candidate_files")
                else:
                    print(
                        f"  [{label}] {path}: present, origin_stage={ref.origin_stage}, "
                        f"evidence_tier={ref.evidence_tier}, reason={ref.reason!r}"
                    )


if __name__ == "__main__":
    main()
