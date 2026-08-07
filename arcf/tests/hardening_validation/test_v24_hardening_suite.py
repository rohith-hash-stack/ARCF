"""ARCF architecture hardening — deterministic validation suite, pytest
side (brief §15). Same 12 scenarios `scripts/hardening_validation_suite.py`
runs for a human-readable report; here each is asserted so the suite is
exercised by CI, not just runnable by hand.
"""

from pathlib import Path

import hardening_validation_suite as suite


async def test_authentication_explanation(tmp_path: Path) -> None:
    report = await suite.scenario_authentication_explanation(tmp_path)
    assert report.files_selected > 0
    assert set(report.evidence_categories_satisfied) >= {
        "login implementation",
        "session persistence",
        "authentication middleware",
        "configuration",
    }


async def test_test_execution_explanation(tmp_path: Path) -> None:
    report = await suite.scenario_test_execution_explanation(tmp_path)
    assert report.files_selected > 0
    assert set(report.evidence_categories_satisfied) >= {
        "package/build manifest",
        "test framework configuration",
        "execution scripts",
    }


async def test_ci_cd_explanation(tmp_path: Path) -> None:
    report = await suite.scenario_ci_cd_explanation(tmp_path)
    assert report.files_selected > 0
    assert set(report.evidence_categories_satisfied) >= {
        "workflow definition",
        "build scripts",
        "dependency installation",
    }


async def test_architecture_understanding(tmp_path: Path) -> None:
    report = await suite.scenario_architecture_understanding(tmp_path)
    assert report.files_selected > 0
    assert report.retrieval_depth <= 2


async def test_bug_localization(tmp_path: Path) -> None:
    report = await suite.scenario_bug_localization(tmp_path)
    assert report.files_selected > 0
    assert report.retrieval_depth <= 1


async def test_refactor_planning(tmp_path: Path) -> None:
    report = await suite.scenario_refactor_planning(tmp_path)
    assert report.files_selected > 0
    assert report.retrieval_depth >= 2
    assert "called by handle_login" in " -> ".join(report.justification_chain_sample)


async def test_impact_analysis(tmp_path: Path) -> None:
    report = await suite.scenario_impact_analysis(tmp_path)
    assert report.files_selected > 0
    assert report.retrieval_depth >= 2


async def test_monorepo_retrieval(tmp_path: Path) -> None:
    report = await suite.scenario_monorepo_retrieval(tmp_path)
    assert report.files_selected > 0
    assert "services/api" in report.notes


async def test_mixed_language_repository(tmp_path: Path) -> None:
    report = await suite.scenario_mixed_language_repository(tmp_path)
    assert report.files_selected > 0
    assert "Python" in report.notes


async def test_unsupported_language_handling(tmp_path: Path) -> None:
    report = await suite.scenario_unsupported_language_handling(tmp_path)
    assert "Ruby" in report.notes


async def test_symbol_ambiguity(tmp_path: Path) -> None:
    report = await suite.scenario_symbol_ambiguity(tmp_path)
    assert "('helper',)" in report.notes


async def test_deep_call_chain_retrieval(tmp_path: Path) -> None:
    report = await suite.scenario_deep_call_chain_retrieval(tmp_path)
    assert report.files_selected == 4
    assert report.retrieval_depth >= 3


async def test_full_suite_runs_and_produces_twelve_reports() -> None:
    reports = await suite.run_all()
    assert len(reports) == 12
    assert {r.category for r in reports} == {
        "authentication_explanation",
        "test_execution_explanation",
        "ci_cd_explanation",
        "architecture_understanding",
        "bug_localization",
        "refactor_planning",
        "impact_analysis",
        "monorepo_retrieval",
        "mixed_language_repository",
        "unsupported_language_handling",
        "symbol_ambiguity",
        "deep_call_chain_retrieval",
    }
    # Every scenario reports a real, non-negative latency and a
    # full-repository token count comparable against the selected count —
    # the "comparison against full-repository context" the brief asks for.
    for report in reports:
        assert report.latency_seconds >= 0.0
        assert report.full_repository_tokens >= 0
