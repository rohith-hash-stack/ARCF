from domain.execution_ledger import ExecutionLedgerEntry
from telemetry.comparison_aggregator import ComparisonAggregator


def _entry(**overrides: object) -> ExecutionLedgerEntry:
    defaults: dict[str, object] = {
        "workspace_id": "workspace-1",
        "contract_id": "contract-1",
        "mode": "direct",
        "model": "gpt-4o-mini",
        "prompt": "fix the bug",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "latency_ms": 1000.0,
        "estimated_cost_usd": 0.02,
        "artifact_content": "some output",
    }
    defaults.update(overrides)
    return ExecutionLedgerEntry(**defaults)  # type: ignore[arg-type]


def test_compare_computes_reduction_percentages() -> None:
    direct = _entry(mode="direct", total_tokens=1000, latency_ms=2000.0, estimated_cost_usd=0.10)
    arcf = _entry(mode="arcf", total_tokens=600, latency_ms=1000.0, estimated_cost_usd=0.05)

    result = ComparisonAggregator().compare("fix the bug", "repo", direct, arcf)

    assert result.token_reduction_pct == 40.0
    assert result.latency_reduction_pct == 50.0
    assert result.cost_reduction_pct == 50.0


def test_compare_computes_prompt_compression_ratio() -> None:
    direct = _entry(mode="direct", prompt_tokens=1000)
    arcf = _entry(mode="arcf", prompt_tokens=250)

    result = ComparisonAggregator().compare("task", "repo", direct, arcf)

    assert result.prompt_compression_ratio == 4.0


def test_compare_context_efficiency_ratio_none_when_direct_has_no_selected_files() -> None:
    direct = _entry(mode="direct", selected_files=[])
    arcf = _entry(mode="arcf", selected_files=["a.py", "b.py"])

    result = ComparisonAggregator().compare("task", "repo", direct, arcf)

    assert result.context_efficiency_ratio is None


def test_compare_context_efficiency_ratio_when_both_have_selected_files() -> None:
    direct = _entry(mode="direct", selected_files=["a.py", "b.py", "c.py", "d.py"])
    arcf = _entry(mode="arcf", selected_files=["a.py"])

    result = ComparisonAggregator().compare("task", "repo", direct, arcf)

    assert result.context_efficiency_ratio == 0.25


def test_compare_reduction_pct_none_when_direct_value_is_zero() -> None:
    direct = _entry(mode="direct", estimated_cost_usd=0.0)
    arcf = _entry(mode="arcf", estimated_cost_usd=0.01)

    result = ComparisonAggregator().compare("task", "repo", direct, arcf)

    assert result.cost_reduction_pct is None


def test_compare_preserves_task_repository_and_both_entries() -> None:
    direct = _entry(mode="direct")
    arcf = _entry(mode="arcf")

    result = ComparisonAggregator().compare("fix login bug", "my/repo", direct, arcf)

    assert result.task == "fix login bug"
    assert result.repository == "my/repo"
    assert result.direct.request_id == direct.request_id
    assert result.arcf.request_id == arcf.request_id
