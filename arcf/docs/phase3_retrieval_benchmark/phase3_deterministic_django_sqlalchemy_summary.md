# Phase 3 Deterministic Retrieval Benchmark -- Django + SQLAlchemy

Zero LLM calls. ContextResolver (classic) only -- see plan Sec 7 step 1. n=1 per task (single-run, per plan Sec 11 labeling requirement).

## django

- files_scanned=7012 files_analyzed=2928 symbols_indexed=43666 index_seconds=22.53 scanner_truncated=False (DEFAULT_MAX_FILES=20000, approaching_cap=False)
- determinism_check (django_task1_modelbase_metaclass_inheritance): byte_identical=True

| task_id | category | R@1 | R@5 | R@10 | MRR | Precision@K | Evidence Compl. | Case-B | Unresolved | Confidence (classic) |
|---|---|---|---|---|---|---|---|---|---|---|
| django_task1_modelbase_metaclass_inheritance | J | 0.3333 | 0.6667 | 0.6667 | 1.0000 | 0.1429 | N/A | False | False | 1.000 |
| django_task2_modelform_metaclass_hierarchy | J | 0.3333 | 1.0000 | 1.0000 | 1.0000 | 0.7500 | N/A | False | False | 1.000 |
| django_task3_manager_from_queryset_dynamic_class | I | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.3333 | N/A | False | False | 1.000 |
| django_task4_model_save_exact | A | 0.0000 | 0.0000 | 0.0000 | 0.0667 | 0.0000 | N/A | False | False | 1.000 |
| django_task5_ambiguous_save | B | 0.0000 | 0.0000 | 0.0000 | 0.0145 | 0.0000 | N/A | False | False | 1.000 |
| django_task6_signal_dispatch_subsystem | D | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.5000 | N/A | False | False | 1.000 |
| django_task7_request_response_call_chain | F | 0.0000 | 0.5000 | 0.5000 | 0.2500 | 0.1667 | N/A | False | False | 1.000 |
| django_task8_middleware_config_driven | H | 0.0000 | 0.0000 | 0.0000 | 0.0769 | 0.0000 | N/A | False | False | 1.000 |
| django_task9_admin_uses_forms_metaclass | E | 0.5000 | 1.0000 | 1.0000 | 1.0000 | 0.1667 | N/A | False | False | 1.000 |
| django_task10_negative_graphql_websocket | L (negative) | -- | -- | -- | -- | -- | N/A | False | True | 0.000 (false_positive=False) |

**Aggregate (10/10 tasks completed, 1 negative):** mean R@1=0.3519 R@5=0.5741 R@10=0.5741 MRR=0.6009 Precision@K=0.2288 evidence_completeness=N/A unresolved_query_rate=0.1000 case_b_trigger_rate=0.0000 FPR(negative)=0.0000 mean_confidence(classic)=0.9000

resolve_latency_ms p50/p95/p99 = {'p50': 1.17, 'p95': 299.31, 'p99': 299.31}  
package_latency_ms p50/p95/p99 = {'p50': 16.76, 'p95': 94.87, 'p99': 94.87}

## sqlalchemy

- files_scanned=702 files_analyzed=667 symbols_indexed=40104 index_seconds=25.74 scanner_truncated=False (DEFAULT_MAX_FILES=20000, approaching_cap=False)
- determinism_check (sqla_task1_engine_connect): byte_identical=True

| task_id | category | R@1 | R@5 | R@10 | MRR | Precision@K | Evidence Compl. | Case-B | Unresolved | Confidence (classic) |
|---|---|---|---|---|---|---|---|---|---|---|
| sqla_task1_engine_connect | A | 0.0000 | 0.0000 | 1.0000 | 0.1000 | 0.0000 | N/A | False | False | 1.000 |
| sqla_task2_declarative_metaclass | I | 0.5000 | 0.5000 | 0.5000 | 1.0000 | 1.0000 | N/A | False | False | 1.000 |
| sqla_task3_instrumented_attribute_descriptor | I | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | N/A | False | False | 1.000 |
| sqla_task4_table_new_dynamic_dispatch | I | 0.0000 | 0.0000 | 0.0000 | 0.0769 | 0.0000 | N/A | False | False | 1.000 |
| sqla_task5_dialect_plugin_loading | H | 0.5000 | 0.5000 | 0.5000 | 1.0000 | 0.1667 | N/A | False | False | 1.000 |
| sqla_task6_unit_of_work_subsystem | D | 0.5000 | 0.5000 | 0.5000 | 1.0000 | 1.0000 | N/A | False | False | 1.000 |
| sqla_task7_session_commit_call_chain | F | 0.3333 | 0.3333 | 0.3333 | 1.0000 | 0.3333 | 0.4000 | True | False | 1.000 |
| sqla_task8_ambiguous_process | B | 0.0000 | 0.0000 | 0.0000 | 0.0357 | 0.0000 | N/A | False | False | 1.000 |
| sqla_task9_mapped_column_wraps_column | E | 0.5000 | 1.0000 | 1.0000 | 1.0000 | 0.2000 | N/A | False | False | 1.000 |
| sqla_task10_negative_graphql | L (negative) | -- | -- | -- | -- | -- | N/A | False | True | 0.000 (false_positive=False) |

**Aggregate (10/10 tasks completed, 1 negative):** mean R@1=0.3704 R@5=0.4259 R@10=0.5370 MRR=0.6903 Precision@K=0.4111 evidence_completeness=0.4000 unresolved_query_rate=0.1000 case_b_trigger_rate=0.1000 FPR(negative)=0.0000 mean_confidence(classic)=0.9000

resolve_latency_ms p50/p95/p99 = {'p50': 0.73, 'p95': 564.34, 'p99': 564.34}  
package_latency_ms p50/p95/p99 = {'p50': 10.78, 'p95': 63.44, 'p99': 63.44}

## Cross-repository aggregate

n_tasks=20 across 2 repos: mean R@1=0.3611 R@5=0.5000 R@10=0.5556 MRR=0.6456

## Per-category aggregate (across both repos)

| category | n | mean R@1 | mean R@5 | mean MRR |
|---|---|---|---|---|
| A | 2 | 0.0 | 0.0 | 0.0833 |
| B | 2 | 0.0 | 0.0 | 0.0251 |
| D | 2 | 0.75 | 0.75 | 1.0 |
| E | 2 | 0.5 | 1.0 | 1.0 |
| F | 2 | 0.1667 | 0.4167 | 0.625 |
| H | 2 | 0.25 | 0.25 | 0.5385 |
| I | 4 | 0.625 | 0.625 | 0.7692 |
| J | 2 | 0.3333 | 0.8333 | 1.0 |
| L | 2 | -- | -- | -- |
