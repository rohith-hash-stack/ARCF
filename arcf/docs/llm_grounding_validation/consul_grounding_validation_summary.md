| Task | Metric | Arm A (ARCF) | Arm B (Raw Baseline) | Arm C (Zero Context) |
| :--- | :--- | :--- | :--- | :--- |
| task1_targeted_logic | Prompt Tokens / TTFT(s) / Total Latency(s) | 8172 / 1.376 / 11.019 | 6312 / 1.314 / 9.976 | 37 / 0.904 / 8.452 |
|  | Grounding / Completeness / Conciseness | 5 / 5 / 4 | 4 / 4 / 4 | 5 / 5 / 4 |
| task2_dependency_tracing | Prompt Tokens / TTFT(s) / Total Latency(s) | 2180 / 0.851 / 8.923 | 8507 / 0.903 / 10.021 | 36 / 0.683 / 7.157 |
|  | Grounding / Completeness / Conciseness | 3 / 2 / 4 | 2 / 3 / 4 | 4 / 5 / 4 |
| task3_interface_type_contract | Prompt Tokens / TTFT(s) / Total Latency(s) | 4406 / 1.176 / 14.076 | 7052 / 1.379 / 15.093 | 37 / 0.634 / 3.194 |
|  | Grounding / Completeness / Conciseness | 2 / 3 / 3 | 2 / 2 / 3 | 4 / 4 / 4 |
| task4_refactoring_multifile | Prompt Tokens / TTFT(s) / Total Latency(s) | 7465 / 3.206 / 10.419 | 7161 / 0.947 / 5.366 | 38 / 0.807 / 4.376 |
|  | Grounding / Completeness / Conciseness | 2 / 2 / 3 | 2 / 2 / 3 | 2 / 3 / 3 |
| task5_ambiguous_common_name | Prompt Tokens / TTFT(s) / Total Latency(s) | 3702 / 0.665 / 6.878 | 10133 / 3.267 / 24.517 | 39 / 3.771 / 5.598 |
|  | Grounding / Completeness / Conciseness | 3 / 4 / 4 | 5 / 5 / 4 | 5 / 5 / 4 |
| **Overall** | **Avg. Grounding / Avg. Composite Score** | **3.0 / 3.27** | **3.0 / 3.27** | **4.0 / 4.07** |
