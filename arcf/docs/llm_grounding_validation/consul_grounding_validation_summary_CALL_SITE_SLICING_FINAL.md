| Task | Metric | Arm A (ARCF) | Arm B (Raw Baseline) | Arm C (Zero Context) |
| :--- | :--- | :--- | :--- | :--- |
| task1_targeted_logic | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 3788 ± 0.0 / 1.014 ± 0.341 / 10.786 ± 1.262 | 6312 ± 0.0 / 0.874 ± 0.14 / 8.215 ± 0.807 | 37 ± 0.0 / 0.789 ± 0.142 / 5.259 ± 0.737 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 3 ± 0.0 / 3.667 ± 0.471 / 3.333 ± 0.471 | 4 ± 0.816 / 4.333 ± 0.471 / 4 ± 0.0 | 5 ± 0.0 / 5 ± 0.0 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.413 ± 0.0 | 0.745 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.5 ± 0.0 | 0.75 ± 0.0 | 0.5 ± 0.0 |
| task2_dependency_tracing | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 5279 ± 0.0 / 0.74 ± 0.013 / 8.09 ± 0.59 | 8555 ± 0.0 / 0.822 ± 0.089 / 8.623 ± 0.601 | 36 ± 0.0 / 0.7 ± 0.015 / 6.225 ± 0.231 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 1.667 ± 0.471 / 2 ± 0.0 / 3 ± 0.0 | 1.667 ± 0.471 / 2 ± 0.0 / 3 ± 0.0 | 3.333 ± 0.471 / 4 ± 0.0 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.562 ± 0.0 | 0.997 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.4 ± 0.0 | 0.267 ± 0.094 | 0.4 ± 0.0 |
| task3_interface_type_contract | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 4506.667 ± 0.471 / 0.695 ± 0.021 / 7.7 ± 1.208 | 7053.667 ± 0.471 / 1.002 ± 0.095 / 7.839 ± 1.273 | 37 ± 0.0 / 0.862 ± 0.174 / 3.031 ± 0.401 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 3 ± 0.0 / 3 ± 0.0 / 4 ± 0.0 | 1.667 ± 0.471 / 1.667 ± 0.471 / 2.667 ± 0.471 | 3 ± 0.0 / 3.667 ± 0.471 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.536 ± 0.0 | 0.86 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.5 ± 0.0 | 0.5 ± 0.0 | 0.5 ± 0.0 |
| task4_refactoring_multifile | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 858 ± 0.0 / 0.623 ± 0.031 / 6.847 ± 0.695 | 7161 ± 0.0 / 0.847 ± 0.141 / 9.747 ± 1.005 | 38 ± 0.0 / 0.735 ± 0.076 / 3.828 ± 0.124 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 3 ± 0.0 / 3 ± 0.0 / 4 ± 0.0 | 2 ± 0.0 / 2 ± 0.0 / 3 ± 0.0 | 2 ± 0.0 / 3 ± 0.0 / 3.667 ± 0.471 |
|  | File Precision, mean ± stddev | 0.25 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.5 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.333 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.084 ± 0.0 | 0.877 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.2 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
| task5_ambiguous_common_name | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 3805.667 ± 1513.68 / 0.66 ± 0.059 / 5.425 ± 0.254 | 5837 ± 2950.049 / 0.958 ± 0.29 / 7.927 ± 1.065 | 39 ± 0.0 / 0.654 ± 0.029 / 2.168 ± 0.228 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 3.667 ± 1.886 / 3.667 ± 1.886 / 3.333 ± 0.943 | 3.667 ± 1.886 / 4 ± 1.414 / 3.667 ± 0.471 | 5 ± 0.0 / 5 ± 0.0 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.133 ± 0.094 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.667 ± 0.471 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.222 ± 0.157 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.436 ± 0.172 | 0.688 ± 0.35 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.889 ± 0.157 | 0.667 ± 0.0 | 0.333 ± 0.0 |
| **Overall** | **Avg. Grounding / Avg. Composite (mean ± stddev)** | **2.867 ± 1.087 / 3.156 ± 0.851** | **2.6 ± 1.405 / 2.889 ± 1.08** | **3.667 ± 1.193 / 3.911 ± 0.694** |
| **Overall** | **File Precision (mean ± stddev)** | **0.077 ± 0.109** | **0.0 ± 0.0** | **0.0 ± 0.0** |
| **Overall** | **File Recall (mean ± stddev)** | **0.233 ± 0.359** | **0.0 ± 0.0** | **0.0 ± 0.0** |
| **Overall** | **File F1 (mean ± stddev)** | **0.111 ± 0.157** | **0.0 ± 0.0** | **0.0 ± 0.0** |
| **Overall** | **Context Budget Utilization (mean ± stddev)** | **0.406 ± 0.187** | **0.833 ± 0.19** | **-** |
| **Overall** | **Key-Term Hit Rate (mean ± stddev)** | **0.498 ± 0.235** | **0.437 ± 0.277** | **0.347 ± 0.185** |
