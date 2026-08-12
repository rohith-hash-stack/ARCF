| Task | Metric | Arm A (ARCF) | Arm B (Raw Baseline) | Arm C (Zero Context) |
| :--- | :--- | :--- | :--- | :--- |
| task1_targeted_logic | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 4826 ± 0.0 / 0.828 ± 0.114 / 10.559 ± 2.047 | 6312 ± 0.0 / 1.014 ± 0.075 / 7.55 ± 0.677 | 37 ± 0.0 / 0.702 ± 0.034 / 6.513 ± 1.099 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 5 ± 0.0 / 5 ± 0.0 / 4 ± 0.0 | 4 ± 0.0 / 4 ± 0.0 / 3.333 ± 0.471 | 5 ± 0.0 / 5 ± 0.0 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.1 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 1.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.182 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.552 ± 0.0 | 0.745 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.833 ± 0.118 | 0.75 ± 0.0 | 0.5 ± 0.0 |
|  | Structural Grounding (G_struct), mean ± stddev | 1.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Behavioral Grounding / R_path (G_behav, N/A tasks excluded), mean ± stddev | - | - | - |
| task2_dependency_tracing | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 5102.667 ± 249.373 / 1.002 ± 0.279 / 8.762 ± 0.571 | 8477 ± 110.309 / 3.33 ± 3.135 / 16.489 ± 9.507 | 36 ± 0.0 / 0.851 ± 0.148 / 5.858 ± 0.883 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 2.333 ± 0.471 / 2.667 ± 0.471 / 3.667 ± 0.471 | 2.667 ± 0.943 / 2.667 ± 0.943 / 3.667 ± 0.943 | 3.667 ± 0.471 / 4.667 ± 0.471 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.562 ± 0.0 | 0.997 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.267 ± 0.094 | 0.2 ± 0.0 | 0.333 ± 0.094 |
|  | Structural Grounding (G_struct), mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Behavioral Grounding / R_path (G_behav, N/A tasks excluded), mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
| task3_interface_type_contract | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 4505.667 ± 0.943 / 0.707 ± 0.044 / 6.022 ± 1.119 | 7052.667 ± 0.943 / 1.528 ± 0.883 / 12.186 ± 2.952 | 37 ± 0.0 / 1.028 ± 0.503 / 3.436 ± 0.48 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 2.333 ± 0.471 / 2 ± 0.0 / 3 ± 0.0 | 2 ± 0.0 / 2 ± 0.0 / 3 ± 0.0 | 3 ± 0.0 / 4 ± 0.0 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.536 ± 0.0 | 0.86 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.5 ± 0.0 | 0.5 ± 0.0 | 0.5 ± 0.0 |
|  | Structural Grounding (G_struct), mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Behavioral Grounding / R_path (G_behav, N/A tasks excluded), mean ± stddev | - | - | - |
| task4_refactoring_multifile | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 858 ± 0.0 / 0.972 ± 0.297 / 8.073 ± 0.542 | 7161 ± 0.0 / 1.15 ± 0.166 / 4.267 ± 0.476 | 38 ± 0.0 / 0.725 ± 0.056 / 4.215 ± 0.26 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 3 ± 0.0 / 3 ± 0.0 / 4 ± 0.0 | 2.333 ± 0.471 / 2 ± 0.0 / 3.333 ± 0.471 | 2 ± 0.0 / 3 ± 0.0 / 3.667 ± 0.471 |
|  | File Precision, mean ± stddev | 0.25 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.5 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.333 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.084 ± 0.0 | 0.877 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.2 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Structural Grounding (G_struct), mean ± stddev | 1.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Behavioral Grounding / R_path (G_behav, N/A tasks excluded), mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
| task5_ambiguous_common_name | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 3723 ± 1455.226 / 0.735 ± 0.123 / 7.138 ± 0.837 | 5783 ± 2911.866 / 0.788 ± 0.224 / 9.823 ± 2.471 | 39 ± 0.0 / 0.709 ± 0.054 / 2.363 ± 0.099 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 3.667 ± 1.886 / 4 ± 1.414 / 3.667 ± 0.471 | 1 ± 0.0 / 1 ± 0.0 / 2 ± 0.0 | 5 ± 0.0 / 5 ± 0.0 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.167 ± 0.118 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.667 ± 0.471 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.267 ± 0.189 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.429 ± 0.167 | 0.69 ± 0.351 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.889 ± 0.157 | 0.444 ± 0.157 | 0.333 ± 0.0 |
|  | Structural Grounding (G_struct), mean ± stddev | 0.667 ± 0.471 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Behavioral Grounding / R_path (G_behav, N/A tasks excluded), mean ± stddev | - | - | - |
| task6_path_hint_secondary_sibling | Runs OK (of 3) | 3/3 | 3/3 | 3/3 |
|  | Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev | 4734 ± 0.0 / 0.678 ± 0.074 / 7.63 ± 0.391 | 6842 ± 0.0 / 1.455 ± 1.024 / 7.454 ± 1.547 | 56 ± 0.0 / 0.583 ± 0.036 / 4.642 ± 0.934 |
|  | Grounding / Completeness / Conciseness, mean ± stddev | 3.333 ± 0.471 / 3 ± 0.0 / 4 ± 0.0 | 4 ± 0.0 / 4.667 ± 0.471 / 4 ± 0.0 | 5 ± 0.0 / 5 ± 0.0 / 4 ± 0.0 |
|  | File Precision, mean ± stddev | 0.0 ± 0.0 | 0.25 ± 0.0 | 0.0 ± 0.0 |
|  | File Recall, mean ± stddev | 0.0 ± 0.0 | 0.5 ± 0.0 | 0.0 ± 0.0 |
|  | File F1, mean ± stddev | 0.0 ± 0.0 | 0.333 ± 0.0 | 0.0 ± 0.0 |
|  | Context Budget Utilization, mean ± stddev | 0.559 ± 0.0 | 0.82 ± 0.0 | - |
|  | Key-Term Hit Rate, mean ± stddev | 0.5 ± 0.0 | 1.0 ± 0.0 | 0.5 ± 0.0 |
|  | Structural Grounding (G_struct), mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
|  | Behavioral Grounding / R_path (G_behav, N/A tasks excluded), mean ± stddev | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
| **Overall** | **Avg. Grounding / Avg. Composite (mean ± stddev)** | **3.278 ± 1.239 / 3.426 ± 0.888** | **2.667 ± 1.155 / 2.87 ± 1.037** | **3.944 ± 1.177 / 4.111 ± 0.676** |
| **Overall** | **File Precision (mean ± stddev)** | **0.086 ± 0.108** | **0.042 ± 0.093** | **0.0 ± 0.0** |
| **Overall** | **File Recall (mean ± stddev)** | **0.361 ± 0.435** | **0.083 ± 0.186** | **0.0 ± 0.0** |
| **Overall** | **File F1 (mean ± stddev)** | **0.13 ± 0.158** | **0.056 ± 0.124** | **0.0 ± 0.0** |
| **Overall** | **Context Budget Utilization (mean ± stddev)** | **0.454 ± 0.185** | **0.831 ± 0.174** | **-** |
| **Overall** | **Key-Term Hit Rate (mean ± stddev)** | **0.531 ± 0.273** | **0.482 ± 0.336** | **0.361 ± 0.182** |
| **Overall** | **Structural Grounding (G_struct) (mean ± stddev)** | **0.444 ± 0.497** | **0.0 ± 0.0** | **0.0 ± 0.0** |
| **Overall** | **Behavioral Grounding / R_path (G_behav, N/A tasks excluded) (mean ± stddev)** | **0.0 ± 0.0** | **0.0 ± 0.0** | **0.0 ± 0.0** |
