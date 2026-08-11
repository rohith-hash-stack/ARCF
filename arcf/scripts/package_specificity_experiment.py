"""package_specificity_experiment.py — falsification experiment, read-only,
touches no ARCF source. Tests the specific empirical claim behind the
proposed "Package Specificity Score" pruning layer (2026-08-11, following
ppr_symbol_recall_experiment.py's falsification): that a generic helper
like `func New()` scores LOW specificity (called from many DIFFERENT
packages) while a domain entity like `type Agent` scores HIGH (calls stay
within its own package) — i.e. S(v) is claimed to cleanly separate the
159 "New"-named symbols that flooded the PPR seed set from the 5
"Agent"-named ones that were the real target.

Hypothesis under scrutiny (not assumed, being tested): Go's own
constructor idiom is `func New() *Foo` per package, called from OUTSIDE
via the qualified name `pkg.New()` — meaning each individual bare `New`
symbol is plausibly ALREADY package-local by construction (most of its
real callers sit inside or very near its own package), the same shape the
proposal claims only holds for genuine domain entities like `Agent`. If
that's true, per-symbol package-specificity would NOT separate the 159
"New" matches from "Agent" the way the proposal's worked example claims —
it would score most of them as "specific" too, since they're each
individually narrow, and the pruning threshold would fail to reduce the
seed set meaningfully.

Success criterion for the PROPOSAL (stated up front, not adjusted after
seeing results): the 159 "new" seeds must show a clearly bimodal or
right-skewed distribution — a substantial majority scoring LOW
specificity (genuinely broad, multi-package usage) — with the "Agent"
seeds cleanly scoring HIGH, and a real (not empty) gap between them a
threshold could sit in. If most "new" seeds ALSO score high
specificity (indistinguishable from Agent's own score), the proposed
pruning mechanism does not solve the seed-flooding problem it was
designed for, regardless of what threshold is chosen.
"""

from __future__ import annotations

from pathlib import Path

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from domain.code_intelligence import Symbol
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner

SCRATCH_B = Path(
    "C:/Users/VASIGA~1/AppData/Local/Temp/claude/C--Users-VasiganiRohitBabu-Desktop-Claude/"
    "9e0bfde9-a14d-4265-b142-a579ae3668d3/scratchpad/pmi_repos"
)


def _build_index(root: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(root)
    return engine.build_index(root, scan.files)


def _package_of(file_path: str) -> str:
    """Go convention: package == directory. Simple, matches this
    project's own DRP taxonomy's directory-based subsystem grouping."""
    parent = str(Path(file_path).parent)
    return parent if parent != "." else "(root)"


def _distinct_caller_packages(symbol: Symbol, index: CodeIntelligenceIndex) -> tuple[int, int, str]:
    """Returns (distinct_caller_package_count, total_caller_count,
    own_package) — both numbers, not just a single derived score, so the
    raw distribution is visible rather than hidden behind one formula
    choice this script would otherwise be guessing at (the proposal
    gives illustrative examples, not an exact formula)."""
    symbol_by_id = {s.id: s for s in index.symbol_index.all()}
    caller_ids = index.call_graph.caller_symbols_of(symbol.id)
    caller_packages = set()
    for cid in caller_ids:
        caller = symbol_by_id.get(cid)
        if caller is not None:
            caller_packages.add(_package_of(caller.file_path))
    own_package = _package_of(symbol.file_path)
    return len(caller_packages), len(caller_ids), own_package


def run(repo_name: str, target_name: str) -> None:
    root = SCRATCH_B / repo_name
    if not root.is_dir():
        print(f"SKIP {repo_name}: not cloned")
        return
    index = _build_index(root)
    matches = [s for s in index.symbol_index.all() if s.name.lower() == target_name.lower()]

    print(f"\n=== {repo_name} | symbols named {target_name!r}: {len(matches)} matches ===")
    if not matches:
        return

    rows = []
    for sym in matches:
        distinct_pkgs, total_callers, own_pkg = _distinct_caller_packages(sym, index)
        # "within own package" caller check specifically, since that's
        # the proposal's own framing ("interacts primarily within
        # pkg/agent") -- computed directly, not inferred from the count.
        symbol_by_id = {s.id: s for s in index.symbol_index.all()}
        caller_ids = index.call_graph.caller_symbols_of(sym.id)
        within_own_pkg = sum(
            1 for cid in caller_ids
            if (c := symbol_by_id.get(cid)) is not None and _package_of(c.file_path) == own_pkg
        )
        rows.append((sym, distinct_pkgs, total_callers, within_own_pkg, own_pkg))

    rows.sort(key=lambda r: -r[1])  # most distinct-caller-packages first (most "generic" by the claim)

    zero_caller = sum(1 for r in rows if r[2] == 0)
    one_or_zero_distinct = sum(1 for r in rows if r[1] <= 1)
    many_distinct = sum(1 for r in rows if r[1] >= 5)

    print(f"  zero real callers found at all: {zero_caller}/{len(rows)}")
    print(f"  distinct_caller_packages <= 1 (would score 'specific' under the proposal): "
          f"{one_or_zero_distinct}/{len(rows)}")
    print(f"  distinct_caller_packages >= 5 (would score 'generic'): {many_distinct}/{len(rows)}")
    print(f"  showing up to 20 (sorted by most distinct caller packages first):")
    for sym, distinct_pkgs, total_callers, within_own, own_pkg in rows[:20]:
        print(
            f"      {sym.qualified_name[:55]:55s} own_pkg={own_pkg[:30]:30s} "
            f"distinct_caller_pkgs={distinct_pkgs:3d}  total_callers={total_callers:3d}  "
            f"within_own_pkg={within_own:3d}"
        )


def main() -> None:
    run("consul", "New")
    run("consul", "Agent")
    run("consul", "Request")
    run("consul", "Register")


if __name__ == "__main__":
    main()
