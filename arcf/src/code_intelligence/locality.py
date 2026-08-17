"""Shared locality filtering — read-side, opt-in wrappers over CallGraph's
existing edges, never a change to CallGraph/ReferenceResolver themselves.

CallGraph deliberately over-includes: when an ambiguous name can't be
resolved to one specific symbol, EVERY same-named candidate repo-wide gets
credited as the caller/callee (see call_graph.py's own docstring — "for
reachability/impact analysis", where over-inclusion is the correct, safe
default). That design was already caught and deliberately preserved once
before in this project's history (ARCF Issue #3's Fix #9 handoff notes:
"Initially proposed editing call_graph.py itself, then caught and reversed
that — it would violate the module's own documented, tested design intent
and affects the classic production resolver too"). Fix #9 landed the
correction as a read-side filter inside DRP's own text_corpus.py instead —
this module generalizes that same idea (same file / same directory /
import-reachable) to a shared location so classic's resolution path and
subsystem_graph.py's community detection can use it too, instead of each
reimplementing it or staying unprotected. NOT byte-identical to Fix #9's
own `_has_locality`, though: this module's `has_locality` fixes a
one-directional import check that Fix #9's copy (and
`ReferenceResolver.resolve_with_disambiguation`'s own version) both share
— see `has_locality`'s docstring for why that's a real bug here even
though it's harmless in both of those call sites.

Real, measured production impact (2026-08-11,
scripts/callgraph_fanout_impact_experiment.py, real Consul,
attach_code_intelligence — not a synthetic reimplementation):
target_names=["New"] (159 same-named symbols repo-wide) produced 156
candidate files across 156 distinct subsystems — effectively the entire
repository — at confidence=1.000. target_names=["Register"] (38 same-named
symbols) produced 30 files across 25 unrelated subsystems, also at
confidence=1.000. Both confirmed to collapse to plausible, locally-coherent
results once filtered through this module (see
tests/code_intelligence/test_locality.py).
"""

from __future__ import annotations

from collections import defaultdict

from code_intelligence.call_graph import CallGraph
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import SymbolKind


def has_locality(index: CodeIntelligenceIndex, file_a: str, file_b: str) -> bool:
    """Same file, same directory, or import-reachable in EITHER direction.

    NOT byte-identical to `ReferenceResolver.resolve_with_disambiguation`'s
    or Fix #9's `_has_locality` import-tier check, despite both looking
    bidirectional at a glance — both of those check
    `X in imports_of(Y) or Y in importers_of(X)`, which is the SAME
    condition ("Y imports X") tested twice through two different APIs,
    not two different directions. That's harmless where they're used:
    resolve_with_disambiguation always calls it with the anchor/context
    file as the fixed side, so "context imports candidate" is the only
    direction that's ever actually needed; Fix #9's usage inside
    text_corpus.py only ever degrades a count, never hard-excludes.
    This function has no such fixed convention — call sites here pass
    (caller_file, context_file) where context_file is the SYMBOL'S OWN
    file, so the relationship that actually needs to hold is "caller
    imports the definition" — the opposite direction from what the other
    two checks cover. A synthetic Go case (`login.go` imports and calls
    into `auth.go`) caught this: the copied formula silently dropped
    login.go, the single most common real caller shape, because it only
    ever tested whether auth.go imported login.go. Checking both
    directions explicitly here avoids depending on which side of the
    pair happens to be the "known" one at each call site."""
    if file_a == file_b:
        return True
    if SymbolIndex.same_package(file_a, file_b):
        return True
    return (
        file_a in index.import_graph.imports_of(file_b)
        or file_a in index.import_graph.importers_of(file_b)
    )


# Final closure pass (2026-08-17), Final Issue 2 / NEW-2: ARCF's
# established architectural promise (context_resolver.py's own
# _MAX_IMPACTED_SYMBOLS/_MAX_CALL_EDGES, query_router.py's
# _MAX_EXPANSION_FILES, drp_resolver.py's own _MAX_IMPACTED_SYMBOLS) is
# BOUNDED FINAL OUTPUT -- what gets added to candidate_files/
# impacted_symbols/call_edges -- not bounded intermediate computation.
# That's a legitimate, deliberate architectural boundary (many systems
# separate "what is scanned" from "what is kept"), EXCEPT where the
# intermediate structure itself is the thing that can exhaust memory
# before any caller-side cap gets a chance to apply -- which is exactly
# this function's own risk: max_depth=None is a real, reachable input
# (RetrievalTaskType.LARGE_STRUCTURAL_CHANGE), and this same class of
# unbounded BFS materialization is what caused a real, measured
# MemoryError in this codebase's own history (see
# context_resolver.py's _MAX_CANDIDATES_TO_EXPAND docstring: "a
# hyper-common identifier recurring 79 times... caused a MemoryError").
# Capped here, once, in the shared primitive every locality_filtered_*
# caller depends on -- not left to each caller to separately remember to
# bound consumption of an already-unbounded result.
_MAX_BFS_NODES = 500


def _locality_filtered_bfs(
    index: CodeIntelligenceIndex,
    start_symbol_id: str,
    context_file: str,
    edges_of: "callable[[str], set[str]]",
    max_depth: int | None,
) -> dict[str, tuple[int, str]]:
    """Same shape as CallGraph._layered_bfs (deterministic tie-breaking,
    self-loop exclusion, depth capping) but querying CallGraph's raw
    per-node edges live at each hop and dropping any candidate with no
    locality to the node it was reached FROM (hop-by-hop, not just a
    fixed check against the original seed's file) — a genuine multi-hop
    call chain through real, related packages (A imports B, B imports C)
    stays intact even though C might not be directly import-reachable
    from A; what gets dropped is a hop landing on a file with no real
    relationship to ANY step in the chain, which is what fan-out noise
    looks like. Hop 1 is checked against `context_file` (the seed
    symbol's own file, the only node that exists before any hop has
    happened) exactly as Fix #9's own single-hop `_has_locality` usage
    already does; hop 2+ is checked against its own immediate parent.
    Deliberately reimplemented here rather than parameterizing
    CallGraph._layered_bfs itself — keeps this filter fully external,
    matching Fix #9's own precedent of never touching call_graph.py's
    tested core traversal."""
    symbol_index_by_id = {s.id: s for s in index.symbol_index.all()}

    def file_of(symbol_id: str) -> str | None:
        symbol = symbol_index_by_id.get(symbol_id)
        return symbol.file_path if symbol is not None else None

    result: dict[str, tuple[int, str]] = {}
    raw_frontier = edges_of(start_symbol_id) - {start_symbol_id}
    frontier = {
        sid for sid in raw_frontier
        if (f := file_of(sid)) is not None and has_locality(index, f, context_file)
    }
    parents: dict[str, str] = dict.fromkeys(frontier, start_symbol_id)
    depth = 1
    while (
        frontier
        and (max_depth is None or depth <= max_depth)
        and len(result) < _MAX_BFS_NODES
    ):
        for node in frontier:
            if len(result) >= _MAX_BFS_NODES:
                break
            result[node] = (depth, parents[node])
        candidates: dict[str, set[str]] = defaultdict(set)
        for node in frontier:
            node_file = file_of(node)
            for neighbor in edges_of(node):
                if neighbor in result or neighbor == start_symbol_id:
                    continue
                neighbor_file = file_of(neighbor)
                if neighbor_file is None or node_file is None:
                    continue
                if not has_locality(index, neighbor_file, node_file):
                    continue
                candidates[neighbor].add(node)
        if not candidates:
            break
        next_frontier: set[str] = set()
        for neighbor, parent_candidates in candidates.items():
            parents[neighbor] = min(parent_candidates)
            next_frontier.add(neighbor)
        frontier = next_frontier
        depth += 1
    return result


def locality_filtered_transitive_callers(
    index: CodeIntelligenceIndex,
    call_graph: CallGraph,
    symbol_id: str,
    context_file: str,
    max_depth: int | None,
) -> dict[str, tuple[int, str]]:
    """Drop-in, locality-filtered alternative to
    CallGraph.transitive_caller_symbols_of — same (hop, parent_id)
    result shape, but only follows edges whose file has real locality
    to `context_file` at EVERY hop, not just the seed. `context_file`
    is normally the seed symbol's own file (the thing the query actually
    resolved to)."""
    return _locality_filtered_bfs(
        index, symbol_id, context_file, call_graph.caller_symbols_of, max_depth
    )


def locality_filtered_transitive_callees(
    index: CodeIntelligenceIndex,
    call_graph: CallGraph,
    symbol_id: str,
    context_file: str,
    max_depth: int | None,
) -> dict[str, tuple[int, str]]:
    return _locality_filtered_bfs(
        index, symbol_id, context_file, call_graph.callee_symbols_of, max_depth
    )


def locality_filtered_caller_files(
    index: CodeIntelligenceIndex, symbol_id: str, context_file: str
) -> set[str]:
    """Drop-in, locality-filtered alternative to
    CallGraph.caller_files_of — same file-set result shape, dropping any
    caller file with no locality to `context_file`."""
    return {
        f for f in index.call_graph.caller_files_of(symbol_id)
        if has_locality(index, f, context_file)
    }


def locality_filtered_callers_of_name(
    index: CodeIntelligenceIndex, name: str, context_file: str
) -> set[str]:
    """Drop-in, locality-filtered alternative to CandidateFileSelector.
    callers_of / SymbolIndex.find_by_name(name)-based lookups: a name
    like "New"/"Register" matches every same-named declaration repo-wide
    (SymbolIndex.find_by_name has no disambiguation of its own — that's
    ReferenceResolver's job, which this call site bypasses entirely by
    going straight from the raw name string). Filters at BOTH layers a
    naive name-based lookup skips: only symbols whose OWN file has
    locality to `context_file` are considered at all (not just any of
    the N same-named declarations repo-wide), and each one's caller
    files are further locality-filtered the same way. `context_file` is
    normally the seed symbol resolve_with_disambiguation already picked
    for this name — the one already-trusted anchor at this call site."""
    files: set[str] = set()
    for symbol in index.symbol_index.find_by_name(name):
        if symbol.kind not in (SymbolKind.FUNCTION, SymbolKind.METHOD):
            continue
        if not has_locality(index, symbol.file_path, context_file):
            continue
        files.add(symbol.file_path)
        files |= locality_filtered_caller_files(index, symbol.id, context_file)
    return files
