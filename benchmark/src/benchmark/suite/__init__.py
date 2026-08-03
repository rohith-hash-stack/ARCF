"""Statistical validation suite — runs a fixed set of real tasks through
Direct/ARCF-Remote/ARCF-Local and layers execution-based verification
(tests_passed, accuracy_score, unrelated_file_modifications) on top of
the existing ComparisonResult/BenchmarkAnalyzer machinery. See
benchmark/suite/models.py for the data shapes and
benchmark/suite/runner.py for the orchestration.
"""
