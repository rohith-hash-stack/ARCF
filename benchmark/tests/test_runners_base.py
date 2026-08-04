"""compile_prompt — ARCF v2.3 retrieval-context stabilization patch,
Change 4: an optional repository_summary section renders between the
task and the file context when ArcfRunner supplies one (built from
evidence-fallback files), and is absent for a normal DirectLLMRunner/
symbol-resolved ArcfRunner call that never supplies it.
"""

from benchmark.runners.base import FileContext, compile_prompt


def test_no_repository_summary_by_default() -> None:
    prompt = compile_prompt("do the task", [FileContext(file_path="a.py", content="x = 1")])
    assert "Repository summary:" not in prompt
    assert "a.py" in prompt


def test_empty_file_list_without_summary_reports_no_context() -> None:
    prompt = compile_prompt("do the task", [])
    assert "(no file context available)" in prompt
    assert "Repository summary:" not in prompt


def test_repository_summary_included_when_provided() -> None:
    summary = "Repository summary:\n- dependency manifest: package.json"
    prompt = compile_prompt(
        "generate documentation",
        [FileContext(file_path="package.json", content="{}")],
        repository_summary=summary,
    )
    assert summary in prompt
    assert prompt.index(summary) < prompt.index("Repository context:")
