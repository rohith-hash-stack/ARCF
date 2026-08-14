"""ARCF-DI explainability benchmark — "every retrieved artifact
explainable by graph traversal," measured against real repos and real
queries, not asserted.

Directly reuses the existing, already-established benchmark: the same
5-repo x 8-query ground-truth set arcf/scripts/run_multi_query_diagnosis.py
built for DRP Issue #3 (see arcf/docs/drp_benchmark_data/
multi_query_pipeline_diagnosis.json for the prior, already-computed
recall numbers this script does NOT recompute), narrowed here to the
three repos the user specifically called out as the project's own
documented "vocabulary mismatch" failure cases -- Traefik, Consul, vLLM
(entropy_confidence_experiment.py's own docstring already labels these
"confirmed-wrong", vs. sqlalchemy/django "confirmed right"). Query text
and target files are copied verbatim from run_multi_query_diagnosis.py's
_CASES so this isn't a second, drifted ground truth.

What this script does NOT do, on purpose: it does not re-measure recall
(whether the target file is in the retrieved candidate set) as a new
result -- that number already exists, is DRP's own, and is unaffected
by anything ARCF-DI does. BLUEPRINT.md Phase 6 explicitly forbids
ARCF-DI from adding a second ranking signal ("don't add a second
ranking signal without re-running the same ablation discipline that
falsified the semantic-reranker experiment") -- so ARCF-DI structurally
cannot change which files route_query returns, and this script doesn't
pretend otherwise. What it DOES measure, freshly, is the one thing
ARCF-DI actually added: for whatever route_query already decided to
retrieve, is every one of those files now backed by a real,
citation-verified evidence trail (attribute_citations, Phase 6) rather
than being an opaque "trust me" file? That's the actual, literal test
of "every retrieved artifact explainable by graph traversal" --
recomputed here, not assumed from the wiring merged in PR #16.

Usage: uv run --project ../../arcf python measure_retrieval_explainability.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

_ARCF_ROOT = Path(__file__).resolve().parents[2] / "arcf"
sys.path.insert(0, str(_ARCF_ROOT / "src"))
sys.path.insert(0, str(_ARCF_ROOT / "scripts"))

from code_intelligence.behavioral_record import BehavioralRecordBuilder  # noqa: E402
from code_intelligence.drp.query_router import route_query  # noqa: E402
from context.evidence_attribution import attribute_citations  # noqa: E402
from context.evidence_summarizer import render_template  # noqa: E402
from domain.code_intelligence import SymbolKind  # noqa: E402
from domain.context_package import PackagedFile  # noqa: E402
from pipeline_stage_diagnosis import RepoContext, build_repo_context  # noqa: E402

# Verbatim from arcf/scripts/run_multi_query_diagnosis.py's _CASES --
# the three repos flagged there as vocabulary-mismatch failures.
_CASES: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "traefik": (
        "go",
        [
            (
                "Explain how dynamic configuration updates propagate without restarting the server.",
                "pkg/server/configurationwatcher.go",
                "original",
            ),
            (
                "When a request comes in, how does Traefik pick which router's handler should "
                "serve it, based on the Host/Path rules?",
                "pkg/muxer/http/mux.go",
                "api/routing",
            ),
            (
                "Where does Traefik look for its static configuration file (toml/yaml) on "
                "startup if I don't pass one explicitly?",
                "pkg/cli/loader_file.go",
                "configuration",
            ),
            (
                "What actually happens when Traefik receives a shutdown signal — how does it "
                "stop the entry points and clean up gracefully?",
                "pkg/server/server.go",
                "lifecycle",
            ),
            (
                "If a backend handler panics mid-request, what stops that from crashing the "
                "whole Traefik process?",
                "pkg/middlewares/recovery/recovery.go",
                "error handling",
            ),
            (
                "How does Traefik decide when to mark a backend server as unhealthy and stop "
                "sending it traffic?",
                "pkg/healthcheck/healthcheck.go",
                "health checking",
            ),
            (
                "During the TLS handshake, how does Traefik choose which certificate to present "
                "for a given SNI hostname?",
                "pkg/tls/certificate_store.go",
                "TLS/certificates",
            ),
            (
                "How does Traefik actually invoke a third-party Yaegi plugin as an HTTP "
                "middleware at request time?",
                "pkg/plugins/middlewareyaegi.go",
                "middleware/plugins",
            ),
        ],
    ),
    "consul": (
        "go",
        [
            (
                "How does Consul add a new service instance to the catalog when an agent "
                "registers it?",
                "agent/consul/catalog_endpoint.go",
                "original",
            ),
            (
                "When a client calls the KV API to set a key, how does the request get "
                "validated and written to the cluster's state?",
                "agent/consul/kvs_endpoint.go",
                "KV store",
            ),
            (
                "How does Consul actually run a script-based health check on an agent and "
                "report the result back?",
                "agent/checks/check.go",
                "health checking",
            ),
            (
                "When a node joins the LAN gossip pool, what code on the server handles that "
                "join event?",
                "agent/consul/server_serf.go",
                "gossip/membership",
            ),
            (
                "How does a Consul server pick which remote server to send a cross-datacenter "
                "RPC to?",
                "agent/router/router.go",
                "RPC/routing",
            ),
            (
                "How does Consul turn a DNS query like myservice.service.consul into actual "
                "A/SRV records for healthy instances?",
                "agent/dns.go",
                "service discovery/DNS",
            ),
            (
                "What does a Consul server do right after it wins a Raft leadership election?",
                "agent/consul/leader.go",
                "leader election/raft",
            ),
            (
                "How does Consul's ACL system decide whether a token's policy grants write "
                "access to a specific KV key?",
                "acl/policy_authorizer.go",
                "ACL/authorization",
            ),
        ],
    ),
    "vllm": (
        "python",
        [
            (
                "How does vLLM decide which request to pause when it runs out of memory for "
                "the KV cache during batching?",
                "vllm/v1/core/sched/scheduler.py",
                "original",
            ),
            (
                "When vLLM loads a model, where does it actually pull down the checkpoint "
                "files and read the safetensors/pt weights into the module?",
                "vllm/model_executor/model_loader/default_loader.py",
                "model loading",
            ),
            (
                "How does vLLM pick which tokenizer implementation to instantiate for a given "
                "model?",
                "vllm/tokenizers/registry.py",
                "tokenization",
            ),
            (
                "Once the model produces logits, what's the actual code path that turns them "
                "into a chosen token — applying temperature, top-k/top-p, and penalties?",
                "vllm/v1/sample/sampler.py",
                "sampling/decoding",
            ),
            (
                "How does vLLM set up the tensor-parallel and pipeline-parallel process groups "
                "across GPUs at startup?",
                "vllm/distributed/parallel_state.py",
                "distributed execution",
            ),
            (
                "How does vLLM decide which attention backend/kernel implementation to "
                "actually run for a given model configuration?",
                "vllm/v1/attention/selector.py",
                "attention kernel dispatch",
            ),
            (
                "Where does vLLM's OpenAI-compatible HTTP server actually start up and begin "
                "serving requests?",
                "vllm/entrypoints/openai/api_server.py",
                "API server entry point",
            ),
            (
                "When a request specifies a LoRA adapter, what code on the worker side is "
                "responsible for loading it and swapping it into the active set?",
                "vllm/lora/worker_manager.py",
                "LoRA adapters",
            ),
        ],
    ),
}


@dataclass
class QueryExplainability:
    repo: str
    query: str
    target: str
    category: str
    target_retrieved: bool
    """DRP's own recall result -- unchanged by, and not attributable to,
    ARCF-DI. Reproduced here only so a reader can see recall and
    explainability side by side without cross-referencing a second file."""
    candidate_files: list[str]
    files_with_citations: int
    files_with_zero_citations: list[str]
    """The actual falsification target for "every retrieved artifact
    explainable by graph traversal": non-empty means the claim is false
    for this query, and the file is named so it can be inspected."""
    target_has_citations: bool | None
    """None when the target wasn't retrieved at all (recall failure --
    a distinct, pre-existing problem this script doesn't touch)."""
    ambiguous_citation_count: int
    behavioral_summaries_built: int
    behavioral_summaries_insufficient: int


def _candidate_files(ctx: RepoContext, query: str) -> list[str]:
    routing = route_query(
        query,
        ctx.drp_index.taxonomy,
        ctx.drp_index.file_tfidf,
        ctx.drp_index.file_to_units,
        ctx.drp_index.subsystem_graph,
        ctx.index,
    )
    files = (
        list(routing.entry_files)
        + list(routing.expansion.keys())
        + [f for group in routing.near_tied_entry_files.values() for f in group]
    )
    # de-dup, preserve first-seen order -- same population diagnose_query
    # calls in_final_candidates against, just materialized as a list here.
    seen: set[str] = set()
    ordered: list[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    return ordered


def _measure_query(ctx: RepoContext, query: str, target: str, category: str) -> QueryExplainability:
    candidates = _candidate_files(ctx, query)
    target_retrieved = target in candidates

    packaged = [
        PackagedFile(
            file_path=path, content="", relevance_score=1.0, reason="retrieved", token_count=0,
            truncated=False,
        )
        for path in candidates
    ]
    enriched = attribute_citations(
        packaged, ctx.index.symbol_index, ctx.index.call_graph, ctx.index.file_analyses
    )
    by_path = {f.file_path: f for f in enriched}

    files_with_citations = sum(1 for f in enriched if f.citations)
    zero_citation_files = [f.file_path for f in enriched if not f.citations]
    ambiguous_count = sum(len(f.ambiguous_evidence_ids) for f in enriched)

    target_has_citations: bool | None = None
    if target_retrieved:
        target_has_citations = bool(by_path[target].citations)

    builder = BehavioralRecordBuilder(ctx.index.symbol_index, ctx.index.call_graph, ctx.index.file_analyses)
    summaries_built = 0
    summaries_insufficient = 0
    for path in candidates:
        for symbol in ctx.index.symbol_index.by_file(path):
            if symbol.kind not in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                continue
            record = builder.build(symbol.id)
            if record is None:
                continue
            summary = render_template(record)
            summaries_built += 1
            if summary.insufficient_evidence:
                summaries_insufficient += 1

    return QueryExplainability(
        repo=ctx.repo,
        query=query,
        target=target,
        category=category,
        target_retrieved=target_retrieved,
        candidate_files=candidates,
        files_with_citations=files_with_citations,
        files_with_zero_citations=zero_citation_files,
        target_has_citations=target_has_citations,
        ambiguous_citation_count=ambiguous_count,
        behavioral_summaries_built=summaries_built,
        behavioral_summaries_insufficient=summaries_insufficient,
    )


def main() -> None:
    repos_root = Path(__file__).resolve().parents[2] / ".benchmark_repos"
    all_results: list[QueryExplainability] = []

    for repo, (language, cases) in _CASES.items():
        print(f"\n{'=' * 78}\nBuilding index: {repo}\n{'=' * 78}")
        ctx = build_repo_context(repo, language, repos_root)
        for query, target, category in cases:
            result = _measure_query(ctx, query, target, category)
            all_results.append(result)
            coverage = (
                f"{result.files_with_citations}/{len(result.candidate_files)}"
                if result.candidate_files
                else "0/0"
            )
            print(
                f"[{repo}] ({category}) retrieved={result.target_retrieved} "
                f"target_has_citations={result.target_has_citations} "
                f"citation_coverage={coverage} ambiguous={result.ambiguous_citation_count}"
            )
            if result.files_with_zero_citations:
                print(f"    zero-citation files: {result.files_with_zero_citations}")

    print(f"\n\n{'#' * 100}\nAGGREGATE\n{'#' * 100}")
    by_repo: dict[str, list[QueryExplainability]] = defaultdict(list)
    for r in all_results:
        by_repo[r.repo].append(r)

    for repo, results in by_repo.items():
        retrieved = [r for r in results if r.target_retrieved]
        total_candidates = sum(len(r.candidate_files) for r in results)
        total_cited = sum(r.files_with_citations for r in results)
        target_explainable = sum(1 for r in retrieved if r.target_has_citations)
        print(f"\n{repo} ({len(results)} queries):")
        print(f"  recall (target retrieved, DRP's own number, unaffected by ARCF-DI): "
              f"{len(retrieved)}/{len(results)}")
        print(f"  file-level citation coverage across all candidates: "
              f"{total_cited}/{total_candidates}"
              f" ({100 * total_cited / total_candidates:.1f}%)" if total_candidates else "  (no candidates)")
        print(f"  of retrieved targets, target itself carries citations: "
              f"{target_explainable}/{len(retrieved)}" if retrieved else "  (none retrieved)")

    out_dir = Path(__file__).resolve().parents[1] / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "explainability_benchmark.json"
    out_path.write_text(
        json.dumps(
            [
                {
                    "repo": r.repo,
                    "query": r.query,
                    "target": r.target,
                    "category": r.category,
                    "target_retrieved": r.target_retrieved,
                    "candidate_file_count": len(r.candidate_files),
                    "files_with_citations": r.files_with_citations,
                    "files_with_zero_citations": r.files_with_zero_citations,
                    "target_has_citations": r.target_has_citations,
                    "ambiguous_citation_count": r.ambiguous_citation_count,
                    "behavioral_summaries_built": r.behavioral_summaries_built,
                    "behavioral_summaries_insufficient": r.behavioral_summaries_insufficient,
                }
                for r in all_results
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
