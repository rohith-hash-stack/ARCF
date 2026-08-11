| Task | Metric | Arm A (ARCF) | Arm B (Raw Baseline) | Arm C (Zero Context) |
| :--- | :--- | :--- | :--- | :--- |
| task1_targeted_logic | Prompt Tokens / TTFT(s) / Total Latency(s) | 8172 / 0.987 / 10.867 | 6312 / 1.049 / 10.043 | 37 / 0.987 / 8.342 |
|  | Grounding / Completeness / Conciseness | 5 / 5 / 4 | 4 / 4 / 4 | 5 / 5 / 4 |
| task2_dependency_tracing | Prompt Tokens / TTFT(s) / Total Latency(s) | 10296 / 2.93 / 16.491 | 8505 / 0.867 / 5.742 | 36 / 0.714 / 6.874 |
|  | Grounding / Completeness / Conciseness | 2 / 3 / 4 | 2 / 2 / 3 | 4 / 5 / 4 |
| task3_interface_type_contract | Prompt Tokens / TTFT(s) / Total Latency(s) | 10248 / 3.126 / 11.92 | 8523 / 2.533 / 11.602 | 37 / 0.933 / 5.205 |
|  | Grounding / Completeness / Conciseness | 2 / 3 / 3 | 2 / 2 / 3 | 3 / 4 / 4 |
| task4_refactoring_multifile | Prompt Tokens / TTFT(s) / Total Latency(s) | 9111 / 1.019 / 8.596 | 7400 / 0.902 / 7.904 | 38 / 0.696 / 4.532 |
|  | Grounding / Completeness / Conciseness | 4 / 4 / 4 | 1 / 1 / 2 | 2 / 3 / 4 |
| task5_ambiguous_common_name | Prompt Tokens / TTFT(s) / Total Latency(s) | 8584 / 3.603 / 13.375 | 8403 / 1.95 / 22.433 | 39 / 0.705 / 3.005 |
|  | Grounding / Completeness / Conciseness | 1 / 1 / 2 | 1 / 1 / 2 | 5 / 5 / 4 |
| **Overall** | **Avg. Grounding / Avg. Composite Score** | **2.8 / 3.13** | **2.0 / 2.27** | **3.8 / 4.07** |
