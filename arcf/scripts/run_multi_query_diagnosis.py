"""ARCF Issue #3 — multi-query pipeline stage diagnosis driver.

Runs `pipeline_stage_diagnosis.diagnose_query` across many queries per
repo (5 repos x 8 queries = 40 total: the 5 original benchmark queries
plus 7 newly researched, verified queries per repo spanning diverse
categories), builds each repo's index ONCE, and aggregates results into
the tables requested for the multi-query validation study.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_stage_diagnosis import build_repo_context, diagnose_query, print_diagnosis

RESULTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "drp_benchmark_data"

# (repo, language, [(query, target, category), ...])
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
    "sqlalchemy": (
        "python",
        [
            (
                "How does SQLAlchemy decide whether to load a relationship immediately or wait "
                "until it's accessed?",
                "lib/sqlalchemy/orm/strategies.py",
                "original",
            ),
            (
                "When my app's connection pool is exhausted, how many extra connections will "
                "SQLAlchemy actually let me open beyond the configured pool size?",
                "lib/sqlalchemy/pool/impl.py",
                "connection pooling",
            ),
            (
                "If I call session.commit() without ever explicitly starting a transaction, "
                "what does SQLAlchemy do under the hood?",
                "lib/sqlalchemy/orm/session.py",
                "transaction/session",
            ),
            (
                "Which class in SQLAlchemy actually turns a Select() construct into a SQL "
                "string, and how does it escape special characters in bind parameter names?",
                "lib/sqlalchemy/sql/compiler.py",
                "SQL compilation",
            ),
            (
                "Where does SQLAlchemy build the actual CREATE TABLE statement, including "
                "things like IF NOT EXISTS and inline foreign key constraints?",
                "lib/sqlalchemy/sql/ddl.py",
                "schema/DDL",
            ),
            (
                "I want a custom column type that transforms a Python value before it's sent "
                "to the database and after it comes back — what's the base class for that?",
                "lib/sqlalchemy/sql/type_api.py",
                "type coercion",
            ),
            (
                "How do I register a callback that fires when a particular SQLAlchemy object "
                "event happens, like after_parent_attach?",
                "lib/sqlalchemy/event/api.py",
                "event system/hooks",
            ),
            (
                "What SQLAlchemy component does Alembic rely on to read the existing database "
                "schema back out for autogeneration?",
                "lib/sqlalchemy/engine/reflection.py",
                "schema reflection",
            ),
        ],
    ),
    "django": (
        "python",
        [
            (
                "How does Django avoid hitting the database again when the same queryset is "
                "evaluated more than once?",
                "django/db/models/query.py",
                "original",
            ),
            (
                "When a request comes in, how does Django walk through nested URLconfs to find "
                "the view that matches the path?",
                "django/urls/resolvers.py",
                "URL routing",
            ),
            (
                "Where does Django run a form's per-field cleaning, the form-level clean() "
                "method, and post-clean hooks when I call is_valid()?",
                "django/forms/forms.py",
                "forms validation",
            ),
            (
                "How does a compiled Django template actually turn into an HTML string when I "
                "call .render() on it?",
                "django/template/base.py",
                "template rendering",
            ),
            (
                "How does Django turn the MIDDLEWARE setting list into the chain of wrapped "
                "handlers that process each request?",
                "django/core/handlers/base.py",
                "middleware",
            ),
            (
                "Which piece of code actually checks a username and password against the "
                "database when a user logs in with the default auth backend?",
                "django/contrib/auth/backends.py",
                "authentication",
            ),
            (
                "What code path actually applies a single migration to the database and "
                "records it as applied?",
                "django/db/migrations/executor.py",
                "migrations",
            ),
            (
                "How does calling admin.site.register(MyModel) actually wire a model into the "
                "Django admin?",
                "django/contrib/admin/sites.py",
                "admin site",
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


def main() -> None:
    repos_root = Path(__file__).resolve().parent.parent.parent / ".benchmark_repos"
    all_diagnoses = []

    for repo, (language, cases) in _CASES.items():
        print(f"\n{'=' * 78}\nBuilding index: {repo}\n{'=' * 78}")
        ctx = build_repo_context(repo, language, repos_root)
        for query, target, category in cases:
            d = diagnose_query(ctx, query, target, category)
            all_diagnoses.append(d)
            print_diagnosis(d)

    # ---- Aggregate table ----
    print(f"\n\n{'#' * 100}\nAGGREGATE TABLE\n{'#' * 100}")
    print(
        f"{'Repo':12s} {'Category':22s} {'First losing stage':32s} {'Conf':8s} {'Target'}"
    )
    for d in all_diagnoses:
        print(
            f"{d.repo:12s} {d.category:22s} {d.first_losing_stage:32s} {d.confidence:8s} {d.target}"
        )

    # ---- Per-repo distribution ----
    print(f"\n{'#' * 100}\nPER-REPO DISTRIBUTION\n{'#' * 100}")
    by_repo: dict[str, list] = defaultdict(list)
    for d in all_diagnoses:
        by_repo[d.repo].append(d)
    for repo, diagnoses in by_repo.items():
        counts = Counter(d.first_losing_stage for d in diagnoses)
        print(f"\n{repo} ({len(diagnoses)} queries):")
        for stage, count in counts.most_common():
            print(f"  {stage:35s} {count}")
        dominant = counts.most_common(1)[0]
        homogeneous = dominant[1] >= len(diagnoses) * 0.6
        print(f"  -> dominant stage: {dominant[0]} ({dominant[1]}/{len(diagnoses)})")
        print(f"  -> {'CONSISTENT' if homogeneous else 'HETEROGENEOUS'} (>=60% threshold)")

    # ---- Save raw data ----
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "multi_query_pipeline_diagnosis.json"
    out_path.write_text(
        json.dumps(
            [
                {
                    "repo": d.repo,
                    "query": d.query,
                    "target": d.target,
                    "category": d.category,
                    "overlap_ratio": d.overlap_ratio,
                    "missing_terms": d.missing_terms,
                    "raw_rank": d.raw_rank,
                    "raw_total": d.raw_total,
                    "is_split": d.is_split,
                    "num_units": d.num_units,
                    "retained_fraction": d.retained_fraction,
                    "unit_token_count": d.unit_token_count,
                    "unit_usage_count": d.unit_usage_count,
                    "target_subsystem": d.target_subsystem,
                    "winner_subsystem": d.winner_subsystem,
                    "subsystem_rank": d.subsystem_rank,
                    "subsystem_total": d.subsystem_total,
                    "near_tie_gap_pct": d.near_tie_gap_pct,
                    "target_entry_rank": d.target_entry_rank,
                    "in_final_candidates": d.in_final_candidates,
                    "first_losing_stage": d.first_losing_stage,
                    "confidence": d.confidence,
                    "evidence": d.evidence,
                }
                for d in all_diagnoses
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
