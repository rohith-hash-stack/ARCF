"""arcf-benchmark CLI.

Subcommands:
  compare       One-shot Direct/ARCF-Remote/ARCF-Local run against a
                real, already-local repository (the original ad-hoc
                comparison tool).
  suite setup   One-time network setup for a suite's target repo
                (currently: todomvc — clones it, npm install, and
                downloads a Playwright browser binary. Requires --yes:
                this is a deliberate, explicit-consent gate for an
                action that downloads real bytes).
  suite run     Runs every task in a suite through ONE mode, storing
                one SuiteModeRunRecord per task. Call once per mode
                you want covered (matching `arcf benchmark run --suite
                X --mode direct|arcf-remote|arcf-local`).
  suite report  Assembles whatever modes have been run so far into the
                management-ready validation report.

All subcommands are built on the same bootstrap.build_runtime the
FastAPI app uses — no separate wiring, no synthetic/mocked pipeline.
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from workspace.analyzer import WorkspaceAnalyzer
from workspace.git_discovery import GitRepositoryDiscovery
from workspace.language_detection import LanguageDetector
from workspace.scanner import RepositoryScanner
from workspace.structure_analyzer import ProjectStructureAnalyzer

from benchmark.bootstrap import build_runtime
from benchmark.config import BenchmarkSettings, get_settings
from benchmark.domain.models import BenchmarkMode
from benchmark.model_resolution import resolve_model
from benchmark.providers.registry import default_provider_registry
from benchmark.report import render_text_report
from benchmark.suite.assemble import assemble_task_result
from benchmark.suite.loader import load_suite
from benchmark.suite.models import SuiteModeRunRecord
from benchmark.suite.repo_pool import RepoPool
from benchmark.suite.report import render_executive_summary, render_suite_report, summarize
from benchmark.suite.runner import SuiteRunner
from benchmark.suite.store import SuiteResultStore

_ALL_MODES = [BenchmarkMode.DIRECT, BenchmarkMode.ARCF, BenchmarkMode.ARCF_LOCAL]
_MODE_CHOICES = {mode.value: mode for mode in _ALL_MODES}
_SUITE_MODE_CHOICES = {"direct": BenchmarkMode.DIRECT, "arcf-remote": BenchmarkMode.ARCF,
                        "arcf-local": BenchmarkMode.ARCF_LOCAL}
_PROVIDER_CHOICES = default_provider_registry().names()

_BENCHMARK_ROOT = Path(__file__).resolve().parent.parent.parent
_SUITES_DIR = _BENCHMARK_ROOT / "suites"
_REPORTS_DIR = _BENCHMARK_ROOT / "reports"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARCF benchmark CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare = subparsers.add_parser(
        "compare", help="One-shot Direct/ARCF-Remote/ARCF-Local comparison"
    )
    compare.add_argument("--repo", required=True, help="Path to a local repository")
    compare.add_argument("--task", required=True, help="The task/prompt to run against the repo")
    compare.add_argument("--model", default=None)
    compare.add_argument(
        "--provider", choices=_PROVIDER_CHOICES, default=None,
        help="Resolve --model as an alias through this BenchmarkProvider (e.g. "
        "--provider gemini --model gemini-flash-latest) instead of passing --model "
        "straight through to litellm.",
    )
    compare.add_argument(
        "--modes", nargs="+", choices=list(_MODE_CHOICES), default=list(_MODE_CHOICES)
    )
    compare.add_argument("--max-context-tokens", type=int, default=None)
    compare.add_argument("--max-output-tokens", type=int, default=None)

    suite = subparsers.add_parser("suite", help="Statistical validation suite")
    suite_subparsers = suite.add_subparsers(dest="suite_command", required=True)

    setup = suite_subparsers.add_parser("setup", help="One-time network setup for a repo")
    setup.add_argument("--repo", required=True, choices=["arcf", "todomvc"])
    setup.add_argument(
        "--yes", action="store_true",
        help="Required for --repo todomvc: confirms you accept the npm install + "
        "Playwright browser download",
    )

    run = suite_subparsers.add_parser("run", help="Run every task in a suite through one mode")
    run.add_argument("--suite", required=True, help="Suite name (benchmark/suites/<name>.json)")
    run.add_argument("--mode", required=True, choices=list(_SUITE_MODE_CHOICES))
    run.add_argument("--model", default=None)
    run.add_argument(
        "--provider", choices=_PROVIDER_CHOICES, default=None,
        help="Resolve --model as an alias through this BenchmarkProvider instead of "
        "passing --model straight through to litellm.",
    )
    run.add_argument("--max-context-tokens", type=int, default=None)
    run.add_argument("--max-output-tokens", type=int, default=None)
    run.add_argument(
        "--pace-seconds", type=float, default=0.0,
        help="Sleep this long between tasks — for providers with a low per-minute "
        "rate limit (e.g. a free tier) where back-to-back calls would 429.",
    )

    report = suite_subparsers.add_parser("report", help="Render the aggregated report")
    report.add_argument("--suite", required=True)

    return parser.parse_args(argv)


async def _run_compare(args: argparse.Namespace) -> int:
    settings = get_settings()
    runtime = build_runtime(settings)

    modes = [_MODE_CHOICES[name] for name in args.modes]
    if BenchmarkMode.ARCF_LOCAL in modes and runtime.local_slm_unavailable_reason is not None:
        print(f"Skipping arcf_local: {runtime.local_slm_unavailable_reason}", file=sys.stderr)
        modes = [mode for mode in modes if mode is not BenchmarkMode.ARCF_LOCAL]

    repo = runtime.repository_loader.open_local(args.repo)
    result = await runtime.controller.run(
        repo=repo,
        task=args.task,
        model=resolve_model(
            args.provider, args.model, settings.default_model, settings.local_slm_base_url
        ),
        modes=modes,
        max_context_tokens=args.max_context_tokens or settings.max_context_tokens,
        max_output_tokens=args.max_output_tokens or settings.max_output_tokens,
        provider=args.provider,
    )

    runtime.store.save(result)
    print(render_text_report(result))
    return 0


def _repo_pool(settings: BenchmarkSettings) -> RepoPool:
    arcf_root = (_BENCHMARK_ROOT / settings.arcf_source_root).resolve()
    suite_repos_root = (_BENCHMARK_ROOT / settings.suite_repos_root).resolve()
    return RepoPool(arcf_root=arcf_root, suite_repos_root=suite_repos_root)


def _suite_setup(args: argparse.Namespace) -> int:
    settings = get_settings()
    pool = _repo_pool(settings)

    if args.repo == "arcf":
        pool.ensure_arcf_base()
        print("arcf base checkout ready.")
        return 0

    if not args.yes:
        print(
            "suite setup --repo todomvc downloads a Playwright browser binary "
            "(~150-300MB) and runs npm install. Re-run with --yes to proceed.",
            file=sys.stderr,
        )
        return 1

    pool.ensure_todomvc_base()
    print("todomvc base checkout ready.")
    return 0


async def _suite_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    runtime = build_runtime(settings)
    mode = _SUITE_MODE_CHOICES[args.mode]

    if mode is BenchmarkMode.ARCF_LOCAL and runtime.local_slm_unavailable_reason is not None:
        print(f"arcf-local unavailable: {runtime.local_slm_unavailable_reason}", file=sys.stderr)
        return 1

    tasks = load_suite(_SUITES_DIR / f"{args.suite}.json")
    pool = _repo_pool(settings)
    pool.ensure_arcf_base()

    workspace_analyzer = WorkspaceAnalyzer(
        git_discovery=GitRepositoryDiscovery(),
        scanner=RepositoryScanner(max_files=settings.workspace_max_files_scanned),
        language_detector=LanguageDetector(),
        structure_analyzer=ProjectStructureAnalyzer(),
    )
    scanner = RepositoryScanner(max_files=settings.workspace_max_files_scanned)

    runner = SuiteRunner(
        repo_pool=pool,
        direct_runner=runtime.direct_runner,
        arcf_runner=runtime.arcf_runner,
        arcf_local_runner=runtime.arcf_local_runner,
        workspace_analyzer=workspace_analyzer,
        scanner=scanner,
        model=resolve_model(
            args.provider, args.model, settings.default_model, settings.local_slm_base_url
        ),
        max_context_tokens=args.max_context_tokens or settings.max_context_tokens,
        max_output_tokens=args.max_output_tokens or settings.max_output_tokens,
        ledger_recorder=runtime.ledger_recorder,
        provider=args.provider,
    )
    store = SuiteResultStore(settings.suite_store_path)

    for index, task in enumerate(tasks):
        if index > 0 and args.pace_seconds > 0:
            await asyncio.sleep(args.pace_seconds)

        try:
            run, verification = await runner.run_task_mode(task, mode)
        except Exception as exc:  # noqa: BLE001
            # One task's LLM/verify failure (rate limit, timeout, ...) must not
            # abort the rest of the suite run — report it and move on.
            print(f"[{task.id}] FAILED to run: {exc}", file=sys.stderr)
            continue

        store.save(
            args.suite,
            SuiteModeRunRecord(
                task_id=task.id, category=task.category, subcategory=task.subcategory,
                mode=mode, run=run, verification=verification,
            ),
        )
        status = "n/a" if verification.tests_passed is None else (
            "PASS" if verification.tests_passed else "FAIL"
        )
        print(f"[{task.id}] {status} — {run.latency_metrics.total_ms:.0f}ms, "
              f"{run.token_metrics.total_tokens} tokens")

    return 0


def _suite_report(args: argparse.Namespace) -> int:
    settings = get_settings()
    tasks = {t.id: t for t in load_suite(_SUITES_DIR / f"{args.suite}.json")}
    store = SuiteResultStore(settings.suite_store_path)
    records_by_task = store.records_by_task(args.suite)

    results = []
    for task_id, records in records_by_task.items():
        task = tasks.get(task_id)
        if task is None:
            continue
        results.append(assemble_task_result(task, records))

    missing = [t for t in tasks if t not in records_by_task]
    if missing:
        print(f"Note: no runs stored yet for: {', '.join(missing)}", file=sys.stderr)

    summary = summarize(args.suite, results)
    report_text = render_suite_report(args.suite, results)
    executive_text = render_executive_summary(summary)
    print(report_text)

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    out_path = _REPORTS_DIR / f"{args.suite}_{timestamp}.md"
    executive_path = _REPORTS_DIR / f"{args.suite}_{timestamp}_executive_summary.md"
    out_path.write_text(report_text, encoding="utf-8")
    executive_path.write_text(executive_text, encoding="utf-8")
    print(f"\nSaved to {out_path}", file=sys.stderr)
    print(f"Executive summary saved to {executive_path}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.command == "compare":
        return asyncio.run(_run_compare(args))
    if args.suite_command == "setup":
        return _suite_setup(args)
    if args.suite_command == "run":
        return asyncio.run(_suite_run(args))
    if args.suite_command == "report":
        return _suite_report(args)
    raise AssertionError(f"unreachable: {args}")


if __name__ == "__main__":
    raise SystemExit(main())
