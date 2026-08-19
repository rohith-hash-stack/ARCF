# Phase 3 Deterministic Retrieval Benchmark -- Traefik + Consul

Deterministic-only pass (plan Sec 7 step 1), zero LLM calls. ARCF commit a9d104d (architecture-closure, frozen).

## traefik

| task | cat | resolver | recall@1 | recall@5 | recall@10 | mrr | precision@k | evidence | confidence | case_b | latency_ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| traefik_task1_healthcheck_launch | A | classic | 1.0 | 1.0 | 1.0 | 1.0 | 0.2 | None | 1.00 | False | 11877.51 |
| traefik_task1_healthcheck_launch | A | drp | 0.0 | 1.0 | 1.0 | 0.5 | 0.3333 | None | 0.32 | False | 2766.03 |
| traefik_task2_retry_new_ambiguous | B | classic | 0.0 | 0.0 | 0.0 | 0.037 | 0.0 | None | 1.00 | False | 1174.2 |
| traefik_task2_retry_new_ambiguous | B | drp | 1.0 | 1.0 | 1.0 | 1.0 | 0.25 | None | 0.02 | False | 1038.85 |
| traefik_task3_ip_allowlist_vocabulary_mismatch | C | classic | 1.0 | 1.0 | 1.0 | 1.0 | 0.5 | None | 1.00 | False | 1011.71 |
| traefik_task3_ip_allowlist_vocabulary_mismatch | C | drp | 1.0 | 1.0 | 1.0 | 1.0 | 0.5 | None | 0.14 | False | 1443.75 |
| traefik_task4_wrr_loadbalancer_subsystem | D | classic | 0.0 | 0.0 | 0.0 | 0.0167 | 0.3333 | None | 1.00 | False | 1184.8 |
| traefik_task4_wrr_loadbalancer_subsystem | D | drp | 0.5 | 1.0 | 1.0 | 1.0 | 0.6667 | None | 0.10 | False | 921.54 |
| traefik_task5_rule_parsing_muxer_crossfile | E | classic | 0.5 | 1.0 | 1.0 | 1.0 | 0.4 | None | 1.00 | False | 952.48 |
| traefik_task5_rule_parsing_muxer_crossfile | E | drp | 0.5 | 0.5 | 0.5 | 1.0 | 0.5 | None | 0.07 | False | 933.56 |
| traefik_task6_middleware_chain_call_chain | F | classic | 0.0 | 0.0 | 0.3333333333333333 | 0.1667 | 0.3333 | None | 1.00 | False | 1612.04 |
| traefik_task6_middleware_chain_call_chain | F | drp | 0.0 | 0.0 | 0.3333333333333333 | 0.1667 | 0.1667 | None | 0.02 | False | 1030.29 |
| traefik_task7_transport_tls_config_driven | H | classic | 1.0 | 1.0 | 1.0 | 1.0 | 0.5 | None | 0.67 | False | 950.41 |
| traefik_task7_transport_tls_config_driven | H | drp | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | None | 0.13 | False | 1042.61 |
| traefik_task8_plugin_builder_dynamic_dispatch | I | classic | 0.3333333333333333 | 1.0 | 1.0 | 1.0 | 0.75 | None | 1.00 | False | 1123.97 |
| traefik_task8_plugin_builder_dynamic_dispatch | I | drp | 0.3333333333333333 | 1.0 | 1.0 | 1.0 | 0.6 | None | 0.43 | False | 1783.39 |
| traefik_task9_negative_graphql | L | classic | -- | -- | -- | -- | -- | None | 0.50 | False | 1178.3 |
| traefik_task9_negative_graphql | L | drp | -- | -- | -- | -- | -- | None | 0.11 | False | 1588.83 |

**classic aggregate** (traefik): mean recall@1=0.4792 mean confidence=0.9074 unresolved=0/9 case_b_rate=0.0 latency_ms p50=1174.2 p95=11877.51 p99=11877.51
**drp aggregate** (traefik): mean recall@1=0.4167 mean confidence=0.1486 unresolved=0/9 case_b_rate=0.0 latency_ms p50=1042.61 p95=2766.03 p99=2766.03

## consul

| task | cat | resolver | recall@1 | recall@5 | recall@10 | mrr | precision@k | evidence | confidence | case_b | latency_ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| existing_task1_targeted_logic | A | classic | 0.0 | 0.0 | 1.0 | 0.1667 | 0.0625 | None | 1.00 | False | 67539.57 |
| existing_task1_targeted_logic | A | drp | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | None | 0.03 | False | 15663.01 |
| existing_task2_dependency_tracing | E | classic | 0.0 | 0.0 | 0.5 | 0.125 | 0.0 | 1.0 | 1.00 | False | 8457.15 |
| existing_task2_dependency_tracing | E | drp | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | None | 0.00 | False | 4401.99 |
| existing_task3_interface_type_contract | A | classic | 0.0 | 1.0 | 1.0 | 0.25 | 0.0 | None | 1.00 | False | 5494.42 |
| existing_task3_interface_type_contract | A | drp | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | None | 0.02 | False | 4199.54 |
| existing_task4_refactoring_multifile | F | classic | 0.0 | 1.0 | 1.0 | 0.25 | 0.0909 | None | 0.67 | False | 5739.6 |
| existing_task4_refactoring_multifile | F | drp | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | None | 0.21 | False | 4450.19 |
| existing_task5_ambiguous_common_name | B | classic | 0.0 | 1.0 | 1.0 | 0.5 | 0.1429 | None | 1.00 | False | 5642.03 |
| existing_task5_ambiguous_common_name | B | drp | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | None | 0.15 | False | 5887.93 |
| existing_task6_path_hint_secondary_sibling | E | classic | 0.0 | 1.0 | 1.0 | 0.3333 | 0.1667 | None | 1.00 | False | 4088.78 |
| existing_task6_path_hint_secondary_sibling | E | drp | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | None | 0.11 | False | 5971.18 |
| consul_task7_ca_provider_dynamic_dispatch | I | classic | 0.0 | 0.0 | 0.5 | 0.1429 | 0.25 | 0.8 | 1.00 | True | 4725.2 |
| consul_task7_ca_provider_dynamic_dispatch | I | drp | 0.0 | 0.5 | 0.5 | 0.2 | 0.1111 | 0.8 | 0.04 | True | 6170.2 |
| consul_task8_autopilot_subsystem | D | classic | 0.5 | 0.5 | 0.5 | 1.0 | 0.25 | None | 1.00 | False | 5891.64 |
| consul_task8_autopilot_subsystem | D | drp | 0.5 | 0.5 | 0.5 | 1.0 | 0.3333 | None | 0.11 | False | 4250.31 |
| consul_task9_negative_graphql | L | classic | -- | -- | -- | -- | -- | None | 0.33 | False | 5727.11 |
| consul_task9_negative_graphql | L | drp | -- | -- | -- | -- | -- | None | 0.12 | False | 4421.49 |

**classic aggregate** (consul): mean recall@1=0.0625 mean confidence=0.8889 unresolved=0/9 case_b_rate=0.1111 latency_ms p50=5727.11 p95=67539.57 p99=67539.57
**drp aggregate** (consul): mean recall@1=0.1875 mean confidence=0.0889 unresolved=0/9 case_b_rate=0.1111 latency_ms p50=4450.19 p95=15663.01 p99=15663.01

## Determinism checks (plan Sec 7.4)

- `traefik_task1_healthcheck_launch`: byte-identical candidate_files across 2 runs = **True**
- `existing_task1_targeted_logic`: byte-identical candidate_files across 2 runs = **True**

## Known-boundary confirmation (plan Sec 0 / arcf_recall_gap_closed)

- `traefik_task2_retry_new_ambiguous`: category B, see raw results for ambiguity-related recall.
- `existing_task2_dependency_tracing`: category E, see raw results for ambiguity-related recall.
- `existing_task5_ambiguous_common_name`: category B, see raw results for ambiguity-related recall.

Case-C rate: NOT MEASURABLE in this pass -- no generation step was run (no LLM call).
