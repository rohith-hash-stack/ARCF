| Task | Metric | Arm A (ARCF) | Arm B (Raw Baseline) | Arm C (Zero Context) |
| :--- | :--- | :--- | :--- | :--- |
| task1_targeted_logic | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 5140 ± 0.0 / 0.692 ± 0.122 / 8.475 ± 0.934 | 8155 ± 0.0 / 0.929 ± 0.213 / 6.77 ± 1.12 | 37 ± 0.0 / 0.728 ± 0.112 / 4.726 ± 0.54 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 3 ± 0.0 / 4 ± 0.0 / 4 ± 0.0 | 3.333 ± 0.471 / 4 ± 0.0 / 4 ± 0.0 | 5 ± 0.0 / 5 ± 0.0 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.559 ± 0.0 | 0.952 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.5 ± 0.0 | 0.5 ± 0.0 | 0.5 ± 0.0 |
| task2_dependency_tracing | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 4535 ± 1325.118 / 0.837 ± 0.107 / 6.872 ± 0.658 | 8672 ± 113.137 / 2.634 ± 2.282 / 9.463 ± 1.913 | 36 ± 0.0 / 0.709 ± 0.059 / 5.423 ± 0.345 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 1.667 ± 0.471 / 2 ± 0.816 / 3 ± 0.816 | 1.667 ± 0.471 / 2 ± 0.0 / 3 ± 0.0 | 4 ± 0.0 / 4.667 ± 0.471 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.466 ± 0.135 | 0.997 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.267 ± 0.094 | 0.267 ± 0.094 | 0.333 ± 0.094 |
| task3_interface_type_contract | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 3422.667 ± 0.943 / 0.944 ± 0.293 / 6.098 ± 1.145 | 8373.667 ± 0.943 / 0.869 ± 0.146 / 5.778 ± 0.534 | 37 ± 0.0 / 0.727 ± 0.049 / 3.281 ± 0.101 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 1.333 ± 0.471 / 1.333 ± 0.471 / 2.333 ± 0.471 | 1 ± 0.0 / 1 ± 0.0 / 2 ± 0.0 | 3 ± 0.0 / 4 ± 0.0 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.37 ± 0.0 | 0.994 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.167 ± 0.236 | 0.167 ± 0.236 | 0.5 ± 0.0 |
| task4_refactoring_multifile | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 4905 ± 0.0 / 0.727 ± 0.095 / 6.522 ± 0.296 | 8354 ± 0.0 / 0.961 ± 0.249 / 5.255 ± 0.45 | 38 ± 0.0 / 0.683 ± 0.092 / 3.719 ± 0.285 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 3.333 ± 0.471 / 4 ± 0.0 / 4 ± 0.0 | 1.667 ± 0.471 / 2 ± 0.0 / 3 ± 0.0 | 2 ± 0.0 / 3 ± 0.0 / 3.667 ± 0.471 |
|  | File Precision, mean ± stddev | 0.0 ± 0.0 | 0.5 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.0 ± 0.0 | 0.5 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.0 ± 0.0 | 0.5 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.548 ± 0.0 | 0.991 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.4 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
| task5_ambiguous_common_name | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 4899 ± 0.0 / 0.722 ± 0.061 / 6.53 ± 0.848 | 7638 ± 0.0 / 0.645 ± 0.068 / 7.918 ± 0.502 | 39 ± 0.0 / 0.708 ± 0.052 / 2.24 ± 0.119 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 2.333 ± 0.471 / 2.667 ± 0.471 / 3 ± 0.0 | 1 ± 0.0 / 1 ± 0.0 / 2 ± 0.0 | 5 ± 0.0 / 5 ± 0.0 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.333 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 1.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.5 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.548 ± 0.0 | 0.887 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.889 ± 0.157 | 0.333 ± 0.0 | 0.333 ± 0.0 |
| **Overall** | **Avg. Grounding / Avg. Composite (mean ± stddev)** | **2.333 ± 0.869 / 2.8 ± 0.901** | **1.733 ± 0.929 / 2.178 ± 0.902** | **3.8 ± 1.166 / 4.022 ± 0.683** |
| **Overall** | **File Precision (mean ± stddev)** | **0.067 ± 0.133** | **0.1 ± 0.2** | **0.0 ± 0.0** |
| **Overall** | **File Recall (mean ± stddev)** | **0.2 ± 0.4** | **0.1 ± 0.2** | **0.0 ± 0.0** |
| **Overall** | **File F1 (mean ± stddev)** | **0.1 ± 0.2** | **0.1 ± 0.2** | **0.0 ± 0.0** |
| **Overall** | **Context Budget Utilization (mean ± stddev)** | **0.498 ± 0.094** | **0.964 ± 0.042** | **-** |
| **Overall** | **Key-Term Hit Rate (mean ± stddev)** | **0.444 ± 0.283** | **0.253 ± 0.202** | **0.333 ± 0.187** |
