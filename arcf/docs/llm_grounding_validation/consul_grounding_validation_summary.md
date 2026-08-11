| Task | Metric | Arm A (ARCF) | Arm B (Raw Baseline) | Arm C (Zero Context) |
| :--- | :--- | :--- | :--- | :--- |
| task1_targeted_logic | Prompt Tokens / TTFT(s) / Total Latency(s) | 3788 / 2.332 / 16.755 | 6312 / 1.039 / 7.555 | 37 / 0.96 / 5.594 |
|  | Grounding / Completeness / Conciseness | 3 / 3 / 4 | 4 / 4 / 4 | 5 / 5 / 4 |
| task2_dependency_tracing | Prompt Tokens / TTFT(s) / Total Latency(s) | 5275 / 1.502 / 10.927 | 8555 / 1.28 / 10.077 | 36 / 0.833 / 6.125 |
|  | Grounding / Completeness / Conciseness | 2 / 2 / 3 | 2 / 2 / 3 | 4 / 4 / 4 |
| task3_interface_type_contract | Prompt Tokens / TTFT(s) / Total Latency(s) | 4407 / 0.679 / 7.008 | 7053 / 0.964 / 8.095 | 37 / 0.593 / 3.292 |
|  | Grounding / Completeness / Conciseness | 3 / 2 / 4 | 1 / 1 / 2 | 3 / 4 / 4 |
| task4_refactoring_multifile | Prompt Tokens / TTFT(s) / Total Latency(s) | 858 / 0.661 / 6.449 | 7161 / 1.943 / 9.325 | 38 / 0.676 / 4.15 |
|  | Grounding / Completeness / Conciseness | 3 / 3 / 4 | 2 / 2 / 3 | 2 / 3 / 4 |
| task5_ambiguous_common_name | Prompt Tokens / TTFT(s) / Total Latency(s) | 1665 / 0.774 / 7.608 | 1665 / 0.578 / 7.717 | 39 / 0.702 / 2.547 |
|  | Grounding / Completeness / Conciseness | 1 / 1 / 2 | 2 / 2 / 3 | 5 / 5 / 4 |
| **Overall** | **Avg. Grounding / Avg. Composite Score** | **2.4 / 2.67** | **2.2 / 2.47** | **3.8 / 4.0** |
