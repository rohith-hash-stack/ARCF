"""SubsystemLocalizer — ARCF root-cause validation experiment.

Hypothesis under test (not yet validated — that's what this module
exists to test): for an entity-less conceptual query, the dominant
failure mode identified in real benchmarking (SQLAlchemy: 81% of
candidate files reached via call-graph hop expansion off a lexically-
probed symbol, landing on `_generate_cache_key`/`id_generator` instead
of the actual loading-strategy code in `orm/strategies.py`/
`orm/loading.py`) is a semantic-anchor-selection problem, not a graph-
expansion problem: `probe_symbol_names` (context/lexical_symbol_probe.py)
searches the ENTIRE symbol index for the query's wording with no notion
of which part of the repository the query is actually about, so a
generic word can anchor on a same-rooted symbol in a completely
unrelated subsystem just as easily as the right one.

This module adds one step BEFORE that search: rank the repository's own
top-level packages/directories by how much of the query's wording
concentrates there, using only signals already available in the existing
pipeline — no embeddings, no model inference, same deterministic
prefix-substring technique context/lexical_symbol_probe.py already uses
(probe_prefixes/shares_lexical_root, reused here, not reimplemented).

Signal sources actually used: directory/package names, filenames, and
names of symbols SymbolIndex already indexed under that directory.
Docstrings/comments are NOT used despite being a plausible source: no
LanguageAnalyzer captures them in the IR today (Symbol has no docstring
field) — noted honestly rather than silently faked for this experiment.

Deliberately NOT wired into code_intelligence/service.py's default
behavior — see that module's `enable_subsystem_localization` parameter
(defaults to False, byte-identical to today's pipeline). This is an
isolated, explicitly-opt-in experiment, not a production change.
"""

from collections import defaultdict
from dataclasses import dataclass

from code_intelligence.symbol_index import SymbolIndex
from context.lexical_symbol_probe import probe_prefixes
from workspace.scanner import ScannedFile

_DEFAULT_MAX_DEPTH = 3
"""How many path segments deep a "subsystem" directory can be — e.g.
depth 3 groups "lib/sqlalchemy/orm/strategies.py" under
"lib/sqlalchemy/orm", not the whole "lib/sqlalchemy" tree or the single
file. Matches typical top-level-package granularity across the
languages already supported (Python packages, Go packages, TS module
directories) without being repository-specific."""
_DEFAULT_TOP_N = 5
_EVIDENCE_CAP = 10
"""Per-candidate cap on how many "why chosen" lines are kept — a
subsystem with hundreds of matching files/symbols doesn't need hundreds
of evidence lines to explain itself, and this keeps the experiment's
output readable."""


@dataclass(frozen=True)
class SubsystemCandidate:
    directory: str
    confidence: float
    """matched query prefixes / total query prefixes — 0 to 1. A crude,
    fully deterministic score, not a probability; see module docstring
    for what "matched" means."""
    matched_terms: tuple[str, ...]
    evidence: tuple[str, ...]
    """Human-readable "why this subsystem" lines — capped at
    _EVIDENCE_CAP, not exhaustive for a large subsystem."""
    file_count: int


def localize_subsystems(
    raw_request: str,
    files: list[ScannedFile],
    symbol_index: SymbolIndex,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    top_n: int = _DEFAULT_TOP_N,
) -> list[SubsystemCandidate]:
    """Ranks repository subsystems (directories, depth-capped) by how
    much of `raw_request`'s wording concentrates there. Returns `[]` when
    the query has no probeable words at all (mirrors
    lexical_symbol_probe.py's own empty-prefix short-circuit) — same
    "nothing to anchor on" case that already exists elsewhere, not a new
    failure mode this module introduces."""
    prefixes = probe_prefixes(raw_request)
    if not prefixes:
        return []

    files_by_subsystem: dict[str, list[str]] = defaultdict(list)
    for f in files:
        parts = f.relative_path.split("/")
        if len(parts) <= 1:
            continue  # root-level file — not part of any subsystem directory
        directory_parts = parts[:-1][:max_depth]
        files_by_subsystem["/".join(directory_parts)].append(f.relative_path)

    candidates: list[SubsystemCandidate] = []
    for subsystem, file_list in files_by_subsystem.items():
        matched: set[str] = set()
        evidence: list[str] = []

        directory_name = subsystem.rsplit("/", 1)[-1].lower()
        for prefix in prefixes:
            if prefix in directory_name and prefix not in matched:
                matched.add(prefix)
                _append_evidence(evidence, f'directory name "{subsystem}" contains "{prefix}"')

        for relative_path in file_list:
            basename = relative_path.rsplit("/", 1)[-1].lower()
            for prefix in prefixes:
                if prefix in basename and prefix not in matched:
                    matched.add(prefix)
                    _append_evidence(
                        evidence, f'filename "{relative_path}" contains "{prefix}"'
                    )

        for relative_path in file_list:
            for symbol in symbol_index.by_file(relative_path):
                lowered_name = symbol.name.lower()
                for prefix in prefixes:
                    if prefix in lowered_name and prefix not in matched:
                        matched.add(prefix)
                        _append_evidence(
                            evidence,
                            f'symbol "{symbol.name}" in {relative_path} contains "{prefix}"',
                        )

        if not matched:
            continue
        candidates.append(
            SubsystemCandidate(
                directory=subsystem,
                confidence=round(len(matched) / len(prefixes), 4),
                matched_terms=tuple(sorted(matched)),
                evidence=tuple(evidence),
                file_count=len(file_list),
            )
        )

    ranked = sorted(
        candidates, key=lambda c: (-c.confidence, -c.file_count, c.directory)
    )
    return ranked[:top_n]


def restrict_names_to_subsystems(
    names: list[str],
    subsystems: list[SubsystemCandidate],
    symbol_index: SymbolIndex,
) -> list[str]:
    """Filters `names` (e.g. probe_symbol_names' own output) down to
    those with at least one real definition inside one of `subsystems`'
    directories — the actual "restrict lexical symbol search to the
    highest-confidence subsystem(s)" step. A name is kept if ANY of its
    (possibly ambiguous) real matches lives in-scope; ContextResolver's
    own disambiguation still runs normally on whatever's kept — this
    only narrows the candidate pool, it doesn't pre-select a single
    symbol the way disambiguation does."""
    if not subsystems:
        return []
    prefixes = tuple(f"{c.directory}/" for c in subsystems)
    kept: list[str] = []
    for name in names:
        matches = symbol_index.find_by_qualified_name(name) or symbol_index.find_by_name(name)
        if any(match.file_path.startswith(prefixes) for match in matches):
            kept.append(name)
    return kept


def _append_evidence(evidence: list[str], line: str) -> None:
    if len(evidence) < _EVIDENCE_CAP:
        evidence.append(line)
