"""CallGraph (Phase 5 deliverable) — caller/callee edges between
symbols, resolved via ReferenceResolver.

Answers the other half of the playbook's example query: "every caller
of authenticate()" is caller_files_of(authenticate's symbol id) (files
containing a call, whether or not the call sits inside a named
function) unioned with caller_symbols_of (for symbol-level graph
queries). A call whose callee_name doesn't resolve to any known
FUNCTION/METHOD symbol is recorded rather than dropped — likely a
builtin, an external library call, or a genuinely dynamic dispatch that
static analysis can't see, which is a real limitation worth surfacing.

ARCF-DI Phase 3 (`mandatory_disambiguation`, default False — every
existing caller of CallGraph is unaffected until it opts in): the
default path above (`resolver.resolve()`) adds a real graph edge to
*every* candidate an ambiguous name resolves to, with no record the name
was ever ambiguous — this is the precise, previously-undocumented
mechanism behind the `New()` collision (one call site attributed to 460
files). `mandatory_disambiguation=True` instead: (1) uses the call
site's own file as a locality signal via ReferenceResolver's existing
`resolve_with_disambiguation`, narrowing to a single edge whenever
locality actually picks a winner (fewer edges than today, deliberately —
the whole point); (2) when it genuinely can't narrow further (no
locality signal, or a true tie), keeps fanning out to every tied
candidate exactly as today's default path does — recall is not
sacrificed where disambiguation has nothing to work with — but now
records the fact that it happened via `resolved_calls`' `candidates`/
`resolution_confidence` fields, where today's default path leaves both
`None`/empty. Ship-behind-a-flag by design: `arcf-di/PROGRESS.md`
documents a same-process ablation proving the two modes produce
identical topology on genuinely ambiguous names and narrower topology
only where a real locality signal exists, before this is ever made the
default.
"""

from collections import defaultdict
from dataclasses import dataclass

from code_intelligence.import_graph import ImportGraph
from code_intelligence.reference_resolver import ReferenceResolver
from domain.code_intelligence import CallReference, CallResolutionConfidence, Symbol, SymbolKind

_CALLABLE_KINDS = (SymbolKind.FUNCTION, SymbolKind.METHOD)


@dataclass(frozen=True)
class TraversalStep:
    """ARCF-DI Phase 7: one node's arrival during transitive_*_trace's
    BFS — the graph traversal log BLUEPRINT.md Phase 7 calls for,
    adapted to what CallGraph's traversal actually is: unscored graph
    reachability, not a ranked search (RelevanceRanker.ScoreBreakdown
    is the scored counterpart, for retrieval results). `step` is the
    trace's own 1-indexed sequential order, built from a sorted
    frontier at each hop — deterministic across runs, not a claim about
    a single true real-world visit order, which BFS doesn't have one of
    across same-hop ties anyway."""

    step: int
    node_visited: str
    hop: int
    reached_via: str
    """The predecessor symbol id this node's hop was recorded from —
    same value transitive_*_symbols_of's own (hop, parent_symbol_id)
    already carries, just also given a sequential position here."""


class CallGraph:
    def __init__(
        self,
        calls: list[CallReference],
        resolver: ReferenceResolver,
        import_graph: ImportGraph | None = None,
        mandatory_disambiguation: bool = False,
    ) -> None:
        self._caller_symbols_of: dict[str, set[str]] = defaultdict(set)
        self._callee_symbols_of: dict[str, set[str]] = defaultdict(set)
        self._caller_files_of: dict[str, set[str]] = defaultdict(set)
        self._unresolved: list[CallReference] = []
        self._resolved_calls: list[CallReference] = []

        for call in calls:
            if mandatory_disambiguation:
                resolved_call, callees = self._resolve_mandatory(call, resolver, import_graph)
            else:
                resolved_call = call
                callees = resolver.resolve(call.callee_name, kinds=_CALLABLE_KINDS)

            if not callees:
                self._unresolved.append(resolved_call)
                continue
            self._resolved_calls.append(resolved_call)
            for callee in callees:
                self._caller_files_of[callee.id].add(call.file_path)
                if call.caller_id is not None:
                    self._callee_symbols_of[call.caller_id].add(callee.id)
                    self._caller_symbols_of[callee.id].add(call.caller_id)

    @staticmethod
    def _resolve_mandatory(
        call: CallReference, resolver: ReferenceResolver, import_graph: ImportGraph | None
    ) -> tuple[CallReference, list[Symbol]]:
        """The call site's own file is the locality context — "which
        same-named symbol is this particular call site most likely
        reaching" is exactly what same-file/same-directory/import-graph
        locality (ReferenceResolver._locality_score) already answers,
        just applied per call site instead of per query."""
        tier = resolver.resolve_tiered(call.callee_name, kinds=_CALLABLE_KINDS)
        if not tier.candidates:
            return call, []

        if len(tier.candidates) == 1:
            confidence = (
                CallResolutionConfidence.SIMPLE_NAME_FALLBACK
                if tier.used_simple_name_fallback
                else CallResolutionConfidence.EXACT_QUALIFIED
            )
            resolved = call.model_copy(update={"resolution_confidence": confidence})
            return resolved, tier.candidates

        disambiguation = resolver.resolve_with_disambiguation(
            call.callee_name,
            kinds=_CALLABLE_KINDS,
            context_files=frozenset({call.file_path}),
            import_graph=import_graph,
        )
        if not disambiguation.ambiguous and disambiguation.preferred is not None:
            resolved = call.model_copy(
                update={"resolution_confidence": CallResolutionConfidence.LOCALITY_DISAMBIGUATED}
            )
            return resolved, [disambiguation.preferred]

        # Genuinely ambiguous: no locality signal narrowed it. Fan out to
        # every tied candidate, same topology the default path produces —
        # but now the ambiguity itself is recorded, deterministically
        # ordered (lexicographic by symbol id), not silently dropped.
        resolved = call.model_copy(
            update={
                "resolution_confidence": CallResolutionConfidence.AMBIGUOUS_MULTI,
                "candidates": sorted(candidate.id for candidate in disambiguation.resolved),
            }
        )
        return resolved, disambiguation.resolved

    def caller_symbols_of(self, symbol_id: str) -> set[str]:
        """Symbols known to call `symbol_id` (module-level call sites excluded —
        see caller_files_of for those)."""
        return set(self._caller_symbols_of.get(symbol_id, set()))

    def callee_symbols_of(self, symbol_id: str) -> set[str]:
        return set(self._callee_symbols_of.get(symbol_id, set()))

    def caller_files_of(self, symbol_id: str) -> set[str]:
        """Every file containing a call site targeting `symbol_id`, whether
        or not that call sits inside a named function."""
        return set(self._caller_files_of.get(symbol_id, set()))

    @property
    def unresolved_calls(self) -> list[CallReference]:
        return list(self._unresolved)

    @property
    def resolved_calls(self) -> list[CallReference]:
        """ARCF-DI Phase 3: every call that resolved to at least one
        candidate, as the CallReference actually used to build graph
        edges — with `resolution_confidence`/`candidates` populated when
        constructed with `mandatory_disambiguation=True`, and left at
        their Phase 1 defaults (None/empty) otherwise. This is the audit
        trail Phase 1's schema fields existed for: with the default
        (`mandatory_disambiguation=False`) constructor path, this list
        exists but every entry is confidence-less, same as before this
        property existed — the fan-out topology (`caller_symbols_of` etc.)
        is unaffected by reading it either way."""
        return list(self._resolved_calls)

    def transitive_caller_symbols_of(
        self, symbol_id: str, max_depth: int | None = None
    ) -> dict[str, tuple[int, str]]:
        """Symbols that transitively call `symbol_id` (its callers, their
        callers, ...), mapped to `(hop, parent_symbol_id)` — hop 1 is a
        direct caller. `max_depth=None` expands until no more callers are
        found (adaptive deterministic traversal, ARCF hardening §1)."""
        return self._layered_bfs(symbol_id, self._caller_symbols_of, max_depth)

    def transitive_callee_symbols_of(
        self, symbol_id: str, max_depth: int | None = None
    ) -> dict[str, tuple[int, str]]:
        """Symbols transitively called by `symbol_id`, mapped to
        `(hop, parent_symbol_id)` — hop 1 is a direct callee."""
        return self._layered_bfs(symbol_id, self._callee_symbols_of, max_depth)

    def transitive_caller_trace(
        self, symbol_id: str, max_depth: int | None = None
    ) -> list[TraversalStep]:
        """ARCF-DI Phase 7: same traversal as transitive_caller_symbols_of,
        plus an ordered, auditable log of every node's arrival —
        BLUEPRINT.md Phase 7's graph traversal log. Computed by the exact
        same algorithm (`_layered_bfs_traced`), not a second
        implementation that could drift from it — see `_layered_bfs`
        below, which is now this method's own thin wrapper."""
        _, trace = self._layered_bfs_traced(symbol_id, self._caller_symbols_of, max_depth)
        return trace

    def transitive_callee_trace(
        self, symbol_id: str, max_depth: int | None = None
    ) -> list[TraversalStep]:
        """ARCF-DI Phase 7: traced counterpart to
        transitive_callee_symbols_of — see transitive_caller_trace."""
        _, trace = self._layered_bfs_traced(symbol_id, self._callee_symbols_of, max_depth)
        return trace

    @staticmethod
    def _layered_bfs(
        start: str, edges: dict[str, set[str]], max_depth: int | None
    ) -> dict[str, tuple[int, str]]:
        """BFS shortest-hop traversal over `edges`, capped at `max_depth`
        hops (`None` = unbounded). Deterministic regardless of set
        iteration order: when a node is reachable from multiple same-hop
        predecessors, the lexicographically smallest predecessor id is
        recorded as its parent, so the result never depends on Python's
        hash-randomized set ordering.

        ARCF-DI Phase 7: thin wrapper over `_layered_bfs_traced` — same
        algorithm, trace discarded — so this method's return value is
        byte-for-byte identical to before Phase 7 existed; every existing
        caller (transitive_caller_symbols_of, transitive_callee_symbols_of,
        and every test asserting on their output) is unaffected."""
        result, _trace = CallGraph._layered_bfs_traced(start, edges, max_depth)
        return result

    @staticmethod
    def _layered_bfs_traced(
        start: str, edges: dict[str, set[str]], max_depth: int | None
    ) -> tuple[dict[str, tuple[int, str]], list["TraversalStep"]]:
        """The actual traversal algorithm — `_layered_bfs` and
        transitive_*_trace both call this, never duplicate it.

        Excludes `start` itself, matching the `neighbor != start` guard
        applied to every later hop below — without it, a symbol with a
        direct self-referential edge (e.g. a `super().method()` call an
        imprecise resolver links back to the same method, or genuine
        recursion) seeds the frontier with `start`, which then records
        `result[start] = (1, start)`: a hop whose parent is itself.
        `_chain_for`'s parent-pointer walk assumes the result is acyclic
        and has no other termination check, so that single self-parented
        entry made it loop forever, appending the same node until the
        process ran out of memory (real, reproduced failure: resolving a
        single real-world recursive-looking symbol in a 236-file repository).

        `trace` iterates each hop's frontier in sorted order before
        recording — `result`'s content never depended on that order (only
        on the deterministic `min(preds)` tie-break below), but a step
        log whose own sequence varied between runs would be a determinism
        bug in exactly the property Phase 7 exists to make auditable, so
        the trace is built more strictly than the minimum `result` itself
        required."""
        result: dict[str, tuple[int, str]] = {}
        trace: list[TraversalStep] = []
        step = 0
        frontier: set[str] = set(edges.get(start, set())) - {start}
        parents: dict[str, str] = dict.fromkeys(frontier, start)
        depth = 1
        while frontier and (max_depth is None or depth <= max_depth):
            for node in sorted(frontier):
                result[node] = (depth, parents[node])
                step += 1
                trace.append(
                    TraversalStep(
                        step=step, node_visited=node, hop=depth, reached_via=parents[node]
                    )
                )
            candidates: dict[str, set[str]] = defaultdict(set)
            for node in frontier:
                for neighbor in edges.get(node, set()):
                    if neighbor not in result and neighbor != start:
                        candidates[neighbor].add(node)
            frontier = set(candidates.keys())
            parents = {neighbor: min(preds) for neighbor, preds in candidates.items()}
            depth += 1
        return result, trace
