from benchmark.quality import build_quality_metrics, count_changed_lines, extract_modified_files


def test_extracts_paths_from_markdown_headers() -> None:
    text = "### src/auth.py\n```\ncode\n```\n\n### src/login.py\n```\nmore\n```"
    assert extract_modified_files(text) == ["src/auth.py", "src/login.py"]


def test_extracts_paths_from_unified_diff_headers() -> None:
    text = "--- a/src/auth.py\n+++ b/src/auth.py\n@@ -1 +1 @@\n-old\n+new\n"
    assert extract_modified_files(text) == ["src/auth.py"]


def test_extracts_paths_from_git_diff_header() -> None:
    text = "diff --git a/src/auth.py b/src/auth.py\nindex abc..def 100644\n"
    assert extract_modified_files(text) == ["src/auth.py"]


def test_ignores_dev_null_in_diff_headers() -> None:
    text = "--- /dev/null\n+++ b/src/new_file.py\n@@ -0,0 +1 @@\n+content\n"
    assert extract_modified_files(text) == ["src/new_file.py"]


def test_deduplicates_paths_preserving_first_appearance_order() -> None:
    text = "### src/a.py\n" * 2 + "### src/b.py\n"
    assert extract_modified_files(text) == ["src/a.py", "src/b.py"]


def test_no_paths_found_returns_empty_list() -> None:
    assert extract_modified_files("just a plain text answer, no diffs here") == []


def test_build_quality_metrics_reports_length_and_files() -> None:
    text = "### src/auth.py\n```\nfix\n```"
    metrics = build_quality_metrics(text)
    assert metrics.answer_length == len(text)
    assert metrics.modified_files == ["src/auth.py"]
    assert metrics.compilation_success is None
    assert metrics.test_success is None


def test_count_changed_lines_counts_plus_and_minus_hunk_lines() -> None:
    text = (
        "--- a/src/auth.py\n+++ b/src/auth.py\n@@ -1,2 +1,2 @@\n"
        "-old line\n-old line 2\n+new line\n"
    )
    assert count_changed_lines(text) == 3


def test_count_changed_lines_excludes_file_header_lines() -> None:
    text = "--- a/src/auth.py\n+++ b/src/auth.py\n@@ -1 +1 @@\n-old\n+new\n"
    assert count_changed_lines(text) == 2


def test_count_changed_lines_zero_for_full_file_block_format() -> None:
    text = "### src/auth.py\n```\ndef authenticate():\n    return True\n```"
    assert count_changed_lines(text) == 0


def test_count_changed_lines_zero_for_plain_prose() -> None:
    assert count_changed_lines("just a plain text answer, no diffs here") == 0


def test_count_changed_lines_handles_multi_file_diff() -> None:
    text = (
        "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
        "--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-p\n+q\n"
    )
    assert count_changed_lines(text) == 4


def test_build_quality_metrics_includes_lines_changed() -> None:
    text = "--- a/src/auth.py\n+++ b/src/auth.py\n@@ -1 +1 @@\n-old\n+new\n"
    metrics = build_quality_metrics(text)
    assert metrics.lines_changed == 2
