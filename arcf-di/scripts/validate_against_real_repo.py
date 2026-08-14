#!/usr/bin/env python3
"""ARCF-DI real-repo validation script — runs the Phase 1-9 modules
against an actual codebase (this repo's own `arcf/` tree, self-hosting)
rather than the hand-built fixtures every unit test uses. Not wired
into any production code path — see arcf-di/PROGRESS.md's Phase 10
entry for why (production wiring is a separate, larger decision).

Run from the arcf-di repo root (parent of `arcf/`):
    uv run --project arcf python arcf-di/scripts/validate_against_real_repo.py [path]

`path` defaults to `arcf/` itself (not `arcf/src`) — the manifest
(`pyproject.toml`) DependencyManifestParser needs lives at the project
root, one level above `src/`; scanning only `src/` would silently find
zero declared dependencies and misclassify every real external import
as UNRESOLVED, not EXTERNAL, purely because the scan root was wrong,
not because the classifier is. Prints a report to stdout and exits
non-zero if anything — including the core reproducibility check —
fails.

Network note: this environment blocks the tiktoken encoding download
CostEstimator normally needs, so this script uses a length-based token
estimate instead (see _OfflineCostEstimator below) — a workaround
local to this script only, not a change to CostEstimator itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Run from the repo root with arcf/src on the path, same as `uv run --project arcf`.
_ARCF_ROOT = Path(__file__).resolve().parents[2] / "arcf"
sys.path.insert(0, str(_ARCF_ROOT / "src"))

from code_intelligence.behavioral_record import BehavioralRecordBuilder  # noqa: E402
from code_intelligence.call_graph import CallGraph  # noqa: E402
from code_intelligence.engine import CodeIntelligenceEngine  # noqa: E402
from code_intelligence.integrity import verify_integrity  # noqa: E402
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer  # noqa: E402
from code_intelligence.library_boundary import LibraryBoundaryClassifier  # noqa: E402
from code_intelligence.reference_resolver import ReferenceResolver  # noqa: E402
from code_intelligence.registry import LanguageRegistry  # noqa: E402
from code_intelligence.symbol_index import SymbolIndex  # noqa: E402
from context.evidence_summarizer import render_template  # noqa: E402
from domain.audit import AuditStamp, PersistedBehavioralRecord  # noqa: E402
from domain.code_intelligence import ImportResolutionKind, SymbolKind  # noqa: E402
from infrastructure.behavioral_record_store import InMemoryBehavioralRecordStore  # noqa: E402
from infrastructure.cost import CostEstimator  # noqa: E402
from workspace.dependency_manifest import DependencyManifestParser  # noqa: E402
from workspace.permissions import PermissionManager  # noqa: E402
from workspace.scanner import RepositoryScanner  # noqa: E402


class _OfflineCostEstimator(CostEstimator):
    """Script-only workaround: tiktoken's encoding download is blocked
    in this environment. A length-based estimate is fine here since
    nothing downstream in this script does budget-critical packaging —
    do not use this in place of the real CostEstimator for anything
    that actually needs accurate token counts."""

    def count_tokens(self, text: str, model: str) -> int:  # noqa: ARG002
        return max(1, len(text) // 4)


def _run_pipeline(workspace_root: Path) -> dict:
    scan = RepositoryScanner().scan(workspace_root)
    permissions = PermissionManager(workspace_root)

    engine = CodeIntelligenceEngine(
        LanguageRegistry([PythonLanguageAnalyzer()]), _OfflineCostEstimator()
    )
    index = engine.build_index(workspace_root, scan.files)

    dependencies = DependencyManifestParser(permissions).parse(scan.files)
    classifier = LibraryBoundaryClassifier(dependencies)

    classified_file_analyses = {}
    for file_path, analysis in index.file_analyses.items():
        classified_imports = classifier.classify(analysis.imports, language=analysis.language)
        classified_file_analyses[file_path] = analysis.model_copy(
            update={"imports": classified_imports}
        )

    all_symbols = index.symbol_index.all()
    all_calls = [call for analysis in classified_file_analyses.values() for call in analysis.calls]
    symbol_index = SymbolIndex(all_symbols)
    resolver = ReferenceResolver(symbol_index)
    call_graph = CallGraph(
        all_calls, resolver, import_graph=index.import_graph, mandatory_disambiguation=True
    )
    builder = BehavioralRecordBuilder(symbol_index, call_graph, classified_file_analyses)
    records = builder.build_all()

    return {
        "scanned_files": len(scan.files),
        "skipped_files": len(index.skipped_files),
        "parse_error_files": len(index.parse_error_files),
        "symbols": len(all_symbols),
        "functions_and_methods": sum(
            1 for s in all_symbols if s.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD)
        ),
        "declared_dependencies": len(dependencies),
        "import_classification_counts": _count_import_kinds(classified_file_analyses),
        "unresolved_calls": len(call_graph.unresolved_calls),
        "ambiguous_resolved_calls": sum(
            1
            for call in call_graph.resolved_calls
            if call.resolution_confidence is not None
            and call.resolution_confidence.value == "ambiguous_multi"
        ),
        "behavioral_records": records,
        "builder": builder,
    }


def _count_import_kinds(file_analyses: dict) -> dict[str, int]:
    counts: dict[str, int] = {kind.value: 0 for kind in ImportResolutionKind}
    counts["unclassified"] = 0
    for analysis in file_analyses.values():
        for imp in analysis.imports:
            if imp.resolved_kind is None:
                counts["unclassified"] += 1
            else:
                counts[imp.resolved_kind.value] += 1
    return counts


_MAX_PRINTED_CITATIONS = 6


def _truncated(items: list[str], limit: int = _MAX_PRINTED_CITATIONS) -> str:
    shown = ", ".join(items[:limit])
    if len(items) > limit:
        shown += f", ... and {len(items) - limit} more"
    return shown


def _report(result: dict) -> None:
    print("=== ARCF-DI real-repo validation ===")
    for key in (
        "scanned_files", "skipped_files", "parse_error_files", "symbols",
        "functions_and_methods", "declared_dependencies", "unresolved_calls",
        "ambiguous_resolved_calls",
    ):
        print(f"{key}: {result[key]}")
    print(f"import_classification_counts: {result['import_classification_counts']}")

    records = result["behavioral_records"]
    print(f"\nbehavioral_records built: {len(records)}")

    ambiguous_records = [r for r in records if r.ambiguous_calls]
    print(f"records with unresolved-ambiguous calls: {len(ambiguous_records)}")
    for record in ambiguous_records[:5]:
        names = sorted({c.callee_name for c in record.ambiguous_calls})
        print(f"  - {record.symbol_id}: ambiguous call(s) to {names}")

    # Deliberately not "most direct callees" -- in a real codebase that
    # trivially surfaces __init__ (every class has one, so it's the most
    # ambiguous name in the whole repo) rather than a representative
    # sample. Split into clean vs. ambiguous so both are visible.
    print("\n--- sample summaries (template-rendered, zero LLM calls) ---")
    clean = [r for r in records if r.direct_callees and not r.ambiguous_calls]
    for record in sorted(clean, key=lambda r: r.symbol_id)[:3]:
        summary = render_template(record)
        text = summary.text or "(insufficient evidence)"
        print(f"  [clean] {record.symbol_id}\n    -> {text}")
        print(f"    citations: {_truncated(summary.citations)}")

    for record in sorted(ambiguous_records, key=lambda r: r.symbol_id)[:3]:
        summary = render_template(record)
        text = summary.text or "(insufficient evidence)"
        print(f"  [ambiguous] {record.symbol_id}\n    -> {text}")
        print(f"    citations: {_truncated(summary.citations)}")


def _check_reproducibility(workspace_root: Path) -> bool:
    print("\n=== reproducibility check: running the full pipeline twice ===")
    first = _run_pipeline(workspace_root)
    second = _run_pipeline(workspace_root)

    first_json = json.dumps(
        [r.model_dump(mode="json") for r in first["behavioral_records"]], sort_keys=True
    )
    second_json = json.dumps(
        [r.model_dump(mode="json") for r in second["behavioral_records"]], sort_keys=True
    )
    identical = first_json == second_json
    print(f"byte-identical across independent runs: {identical}")
    return identical


def _check_persistence_and_integrity(result: dict) -> bool:
    print("\n=== persistence + integrity check ===")
    store = InMemoryBehavioralRecordStore()
    stamp = AuditStamp(commit_sha="validation-run", resolver_version="v1", schema_version="v1")
    symbol_ids = [r.symbol_id for r in result["behavioral_records"]]
    for record in result["behavioral_records"]:
        store.save(PersistedBehavioralRecord(stamp=stamp, record=record))

    report = verify_integrity(store, result["builder"], "validation-run", symbol_ids)
    print(f"persisted {len(symbol_ids)} records, integrity check clean: {report.clean}")
    if not report.clean:
        for mismatch in report.mismatches[:10]:
            print(f"  MISMATCH: {mismatch.symbol_id}: {mismatch.reason}")
    return report.clean


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else _ARCF_ROOT
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return 1

    result = _run_pipeline(target)
    _report(result)

    reproducible = _check_reproducibility(target)
    integrity_clean = _check_persistence_and_integrity(result)

    print("\n=== summary ===")
    ok = reproducible and integrity_clean and result["parse_error_files"] == 0
    print(f"reproducible: {reproducible}")
    print(f"integrity clean: {integrity_clean}")
    print(f"zero parse errors: {result['parse_error_files'] == 0}")
    print("RESULT: PASS" if ok else "RESULT: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
