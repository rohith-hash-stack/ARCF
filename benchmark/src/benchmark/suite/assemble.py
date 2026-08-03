"""Assembles a SuiteTaskResult from whichever SuiteModeRunRecords have
been stored for a task so far — each `suite run --mode X` invocation
persists one record; `suite report` reads them back and combines
however many modes have actually been run, via the SAME
BenchmarkAnalyzer the live 2/3-mode benchmark already uses.
"""

from benchmark.analyzer import BenchmarkAnalyzer
from benchmark.domain.models import BenchmarkMode
from benchmark.suite.models import SuiteModeRunRecord, SuiteTask, SuiteTaskResult

_analyzer = BenchmarkAnalyzer()


def assemble_task_result(
    task: SuiteTask, records_by_mode: dict[BenchmarkMode, SuiteModeRunRecord]
) -> SuiteTaskResult:
    direct = records_by_mode.get(BenchmarkMode.DIRECT)
    arcf = records_by_mode.get(BenchmarkMode.ARCF)
    arcf_local = records_by_mode.get(BenchmarkMode.ARCF_LOCAL)

    any_record = direct or arcf or arcf_local
    model = any_record.run.model if any_record else "unknown"

    comparison = _analyzer.compare(
        task=task.task_prompt,
        repository=f"{task.repo_key}:{task.id}",
        model=model,
        direct=direct.run if direct else None,
        arcf=arcf.run if arcf else None,
        arcf_local=arcf_local.run if arcf_local else None,
    )

    return SuiteTaskResult(
        task_id=task.id,
        category=task.category,
        subcategory=task.subcategory,
        comparison=comparison,
        direct_verification=direct.verification if direct else None,
        arcf_verification=arcf.verification if arcf else None,
        arcf_local_verification=arcf_local.verification if arcf_local else None,
    )
