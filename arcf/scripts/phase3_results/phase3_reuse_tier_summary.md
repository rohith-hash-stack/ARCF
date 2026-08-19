# Phase 3 Deterministic Pass -- Reuse Tier (Flask / spring-petclinic / vLLM)

## Regression check (fresh clones vs. 2026-08-12 checkpoint)

| Repo | Prior fallback ratio | Fresh fallback ratio | Drift | Reproduced (<2pp)? |
|---|---|---|---|---|
| flask | 0.857 | 0.8571 | 0.0001 | True |
| spring-petclinic | 0.5 | 0.5 | 0.0 | True |
| vllm | 0.667 | 0.3333 | -0.3337 | False |

## New tasks (per-task results, n=1 each)

| id | repo | category | recall@1 | recall@5 | recall@10 | MRR | precision@K | evidence_completeness | case_b | unresolved |
|---|---|---|---|---|---|---|---|---|---|---|
| flask_route_registration | flask | E | 0.5 | 1.0 | 1.0 | 1.0 | 0.5 (K=2) | None | False | False |
| flask_graphql_negative | flask | L (negative) | -- | -- | -- | -- | -- | None | False | True (false_positive=False) |
| petclinic_visit_booking_chain | spring-petclinic | F | 0.3333 | 1.0 | 1.0 | 1.0 | 0.75 (K=4) | None | False | False |
| petclinic_database_config | spring-petclinic | H | 0.0 | 0.0 | 0.0 | 0.0 | None (K=0) | None | False | True |
| vllm_generate_ambiguous | vllm | B | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 (K=5) | None | False | False |
| vllm_federated_learning_negative | vllm | L (negative) | -- | -- | -- | -- | -- | None | False | True (false_positive=False) |

## Aggregate (n=1 per task -- single-run, not statistically tested)

- **n_new_tasks**: 6
- **n_positive_tasks**: 4
- **n_negative_tasks**: 2
- **mean_recall_at_1**: 0.2083
- **mean_recall_at_5**: 0.5
- **mean_recall_at_10**: 0.5
- **mean_mrr**: 0.5
- **unresolved_query_rate**: 0.5
- **false_positive_rate_negative_tasks**: 0.0
- **case_b_trigger_rate**: 0.0
- **latency_ms**: {'p50': 1.822, 'p95': 362.753, 'p99': 362.753, 'n': 6}
- **n_run_label**: n=1 per task (single-run) -- NOT a multi-run statistical result; see plan §11.

## Determinism check (plan §7.4)

| Repo | run1 candidates | run2 candidates | byte-identical |
|---|---|---|---|
| flask | 3 | 3 | True |
| spring-petclinic | 4 | 4 | True |
| vllm | 15 | 15 | True |
