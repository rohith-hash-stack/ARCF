"""ContextResolver — the only file besides CodeIntelligenceEngine itself
allowed to touch SymbolIndex/CallGraph/InheritanceGraph/DependencyGraph
internals. Everything it produces crosses into domain.context_resolution
types before leaving this module.

A thin translation layer, deliberately: it reuses CandidateFileSelector's
existing queries (callers_of, subclasses_of) rather than re-deriving
graph traversal, and ReferenceResolver/SymbolIndex for lookups. Its own
job is bookkeeping — turning "which files/symbols matter and why" into
the flat ContextResolutionResult shape, plus the deterministic
confidence score, resolution_reason, and token estimate that make the
result auditable and token-aware before any SLM is ever called.

ARCF architecture hardening, §1 (adaptive deterministic traversal):
candidate_files/dependency_chain/call_chain are no longer fixed at one
hop out from the resolved entry points. `traversal_depth` controls how
many call/inheritance hops are followed (default 1 preserves the exact
pre-hardening behavior); `None` expands until CallGraph/InheritanceGraph
have nothing more to offer, optionally bounded by `max_expansion_tokens`.
Every file gets a `justification_chain` recording the hop-by-hop path
that pulled it in, so widening the traversal never turns into a black
box — narrowing an ever-larger candidate set further (ranking,
compression) remains Phase 6's job, not this one's.
"""

import math
from collections import Counter
from uuid import uuid4

from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.locality import (
    locality_filtered_callers_of_name,
    locality_filtered_transitive_callees,
    locality_filtered_transitive_callers,
)
from code_intelligence.reference_resolver import ReferenceResolver
from domain.code_intelligence import Symbol, SymbolKind
from domain.context_resolution import (
    CallEdge,
    ContextResolutionResult,
    DependencyEdge,
    EvidenceTier,
    FileReference,
    SymbolReference,
    TokenEstimate,
)

# ARCF hardening §8 (semantic-completeness-preserving compression):
# per-language constructor method names, so a selected METHOD symbol's
# enclosing class's constructor rides along into impacted_symbols and
# therefore into whatever SymbolRangeCompressor extracts for that file —
# without ever pulling in the whole class body. Go has no constructor
# concept (receiver-based free functions, factory-function convention is
# too heuristic to name reliably) and is deliberately not covered.
_CONSTRUCTOR_NAMES_BY_LANGUAGE: dict[str, frozenset[str]] = {
    "python": frozenset({"__init__", "__new__"}),
    "typescript": frozenset({"constructor"}),
    "kotlin": frozenset({"init"}),
}
# Java and C# constructors share the declaring class's own name rather
# than a fixed keyword.
_CONSTRUCTOR_MATCHES_CLASS_NAME_LANGUAGES = frozenset({"java", "csharp"})

# A target name tied across this many or fewer candidates is still worth
# fully expanding (a handful of same-named overloads/re-exports is a
# common, benign pattern). Beyond it, a name is matching too many
# unrelated symbols to be a precise signal — real, measured cost: a
# hyper-common identifier recurring 79 times across unrelated files in a
# large monorepo caused a MemoryError, since each match independently
# triggers its own full call-graph traversal (_expand_calls/
# _expand_subclasses). Every matching file is still recorded as a
# candidate either way — this only skips the expensive per-symbol
# expansion once ambiguity crosses this threshold, never drops a real
# match.
_MAX_CANDIDATES_TO_EXPAND = 5


class ContextResolver:
    def __init__(self, index: CodeIntelligenceIndex) -> None:
        self._index = index

    def resolve(
        self,
        workspace_id: str,
        contract_id: str,
        repository_root: str,
        target_names: list[str],
        traversal_depth: int | None = 1,
        max_expansion_tokens: int | None = None,
        entry_point_tier: EvidenceTier = EvidenceTier.PRIMARY,
    ) -> ContextResolutionResult:
        """`entry_point_tier` tags only the direct "defines {name}" match
        for each resolved target name — evidence-preserving context
        packaging's PRIMARY/SUPPORTING distinction (domain.
        context_resolution.EvidenceTier). Defaults to PRIMARY: a caller
        resolving confident, exact target names (e.g. SLM-1-extracted
        entities) gets today's behavior unchanged. A caller recovering
        from a lexical/prefix-substring symbol-name guess (context/
        lexical_symbol_probe.py) should pass SUPPORTING instead — even
        the file that directly defines a merely-probed name is a weaker
        signal than an exact match. Every file reached via call-graph or
        inheritance expansion below (_expand_calls/_expand_subclasses) is
        unconditionally SUPPORTING regardless of this parameter: fan-out
        is fan-out, however confident the entry point that produced it
        was."""
        entry_point_symbols: list[Symbol] = []
        impacted_symbols: dict[str, Symbol] = {}
        candidate_files: set[str] = set()
        file_reasons: dict[str, str] = {}
        file_chains: dict[str, tuple[str, ...]] = {}
        file_tiers: dict[str, EvidenceTier] = {}
        call_edges: list[CallEdge] = []
        max_hop_reached = 0
        ambiguous_targets: list[str] = []
        unresolved_symbols: list[str] = []
        file_ambiguity_confidence: dict[str, float] = {}
        reference_resolver = ReferenceResolver(self._index.symbol_index)

        resolved_count = 0
        for name in target_names:
            # Locality context is whatever's already been established as
            # relevant by earlier target names in this same call — the
            # "detected execution path" (ARCF hardening §3). The first
            # target name in a request has no such context yet.
            disambiguation = reference_resolver.resolve_with_disambiguation(
                name,
                context_files=frozenset(candidate_files),
                import_graph=self._index.import_graph,
            )
            matches = disambiguation.resolved
            if matches:
                resolved_count += 1
            else:
                unresolved_symbols.append(name)
            if disambiguation.ambiguous:
                ambiguous_targets.append(name)
            expand_matches = len(matches) <= _MAX_CANDIDATES_TO_EXPAND
            # Feature A (Tier-1 structural ambiguity decay): N is the raw
            # match count for THIS name, before any graph expansion runs —
            # a name matching many unrelated symbols (Go's bare `New`: 156
            # real matches in Consul) is a weaker per-candidate signal than
            # one matching a handful, however confident each individual
            # match's role_score looks in isolation. N=1 keeps the
            # multiplier at exactly 1.0 (no penalty for an unambiguous
            # name), matching this field's None-is-neutral contract.
            ambiguity_confidence = (
                1.0 if len(matches) <= 1 else 1.0 / math.log2(len(matches) + 1)
            )
            for symbol in matches:
                entry_point_symbols.append(symbol)
                self._add_file(
                    candidate_files,
                    file_reasons,
                    file_chains,
                    file_tiers,
                    symbol.file_path,
                    f"defines {name}",
                    (f"defines {name}",),
                    entry_point_tier,
                    file_ambiguity_confidence,
                    ambiguity_confidence,
                )
                if not expand_matches:
                    continue

                if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                    max_hop_reached = max(
                        max_hop_reached,
                        self._expand_calls(
                            symbol,
                            name,
                            traversal_depth,
                            max_expansion_tokens,
                            candidate_files,
                            file_reasons,
                            file_chains,
                            file_tiers,
                            impacted_symbols,
                            call_edges,
                        ),
                    )
                elif symbol.kind is SymbolKind.CLASS:
                    max_hop_reached = max(
                        max_hop_reached,
                        self._expand_subclasses(
                            symbol,
                            name,
                            traversal_depth,
                            candidate_files,
                            file_reasons,
                            file_chains,
                            file_tiers,
                            impacted_symbols,
                        ),
                    )

        self._enrich_with_constructors(impacted_symbols, entry_point_symbols)

        dependency_edges = [
            DependencyEdge(from_file=file_path, to_file=imported)
            for file_path in candidate_files
            for imported in self._index.import_graph.imports_of(file_path)
            if imported in candidate_files
        ]

        unresolved_import_modules: set[str] = set()
        for file_path in candidate_files:
            analysis = self._index.file_analyses.get(file_path)
            if analysis is None:
                continue
            for imp in analysis.imports:
                if imp.resolved_file_path is None:
                    unresolved_import_modules.add(imp.raw_module)
        unresolved_imports = sorted(unresolved_import_modules)

        raw_context_tokens = sum(self._index.token_counts.values())
        selected_context_tokens = sum(
            self._index.token_counts.get(file_path, 0) for file_path in candidate_files
        )
        compression_ratio = (
            round(selected_context_tokens / raw_context_tokens, 4) if raw_context_tokens else 0.0
        )

        total_targets = len(target_names)
        confidence = round(resolved_count / total_targets, 4) if total_targets else 0.0

        return ContextResolutionResult(
            id=uuid4(),
            workspace_id=workspace_id,
            contract_id=contract_id,
            repository_root=repository_root,
            language=self._dominant_language(candidate_files),
            candidate_files=[
                FileReference(
                    file_path=file_path,
                    reason=file_reasons.get(file_path, "related"),
                    language=self._language_of(file_path),
                    token_count=self._index.token_counts.get(file_path, 0),
                    justification_chain=file_chains.get(file_path, ()),
                    evidence_tier=file_tiers.get(file_path, EvidenceTier.SUPPORTING),
                    ambiguity_confidence=file_ambiguity_confidence.get(file_path),
                )
                for file_path in sorted(candidate_files)
            ],
            impacted_symbols=[
                self._to_symbol_reference(symbol)
                for symbol in sorted(impacted_symbols.values(), key=lambda s: s.id)
            ],
            dependency_chain=dependency_edges,
            call_chain=call_edges,
            entry_points=[self._to_symbol_reference(symbol) for symbol in entry_point_symbols],
            confidence=confidence,
            token_estimate=TokenEstimate(
                raw_context_tokens=raw_context_tokens,
                selected_context_tokens=selected_context_tokens,
                compression_ratio=compression_ratio,
            ),
            resolution_reason=self._build_reason(total_targets, resolved_count, candidate_files),
            retrieval_depth_used=max_hop_reached,
            ambiguous_targets=tuple(ambiguous_targets),
            unresolved_symbols=tuple(unresolved_symbols),
            unresolved_imports=tuple(unresolved_imports),
        )

    def _expand_calls(
        self,
        symbol: Symbol,
        name: str,
        traversal_depth: int | None,
        max_expansion_tokens: int | None,
        candidate_files: set[str],
        file_reasons: dict[str, str],
        file_chains: dict[str, tuple[str, ...]],
        file_tiers: dict[str, EvidenceTier],
        impacted_symbols: dict[str, Symbol],
        call_edges: list[CallEdge],
    ) -> int:
        max_hop = 0
        budget = _TokenBudget(self._index, candidate_files, max_expansion_tokens)

        # Hop-1 module-level call sites (no owning symbol) — preserves the
        # pre-hardening callers_of() file coverage exactly. Module-level
        # call sites reached at hop 2+ (a symbol-owning caller itself
        # called only from top-level script code, not another symbol) are
        # a known, documented gap: CallGraph.caller_files_of() can't
        # distinguish "already covered by the symbol-level BFS" from
        # "genuinely module-level", so attempting to fold it in here
        # produced conflicting justification chains for the same file.
        # caller_hops/callee_hops below already cover every symbol-owning
        # hop correctly.
        #
        # locality_filtered_callers_of_name, not candidate_selector.
        # callers_of(name) directly: `name` is a raw string, and
        # SymbolIndex.find_by_name has no disambiguation of its own — for
        # a common identifier (confirmed real, 2026-08-11: "New" matched
        # 159 same-named declarations in a real Consul clone, "Register"
        # 38), the unfiltered version unions caller files across EVERY
        # same-named symbol repo-wide regardless of which one `symbol`
        # (already disambiguated below) actually is, corrupting
        # candidate_files with files from dozens of unrelated subsystems
        # at reported confidence=1.0. Filtered relative to `symbol`'s own
        # file, the seed this whole expansion is actually anchored to.
        for caller_file in locality_filtered_callers_of_name(
            self._index, name, symbol.file_path
        ):
            if budget.allow(caller_file):
                self._add_file(
                    candidate_files,
                    file_reasons,
                    file_chains,
                    file_tiers,
                    caller_file,
                    f"calls {name}",
                    (f"defines {name}", f"calls {name}"),
                    EvidenceTier.SUPPORTING,
                )
                max_hop = max(max_hop, 1)
                self._attach_call_site_symbols(caller_file, name, impacted_symbols)

        # locality_filtered_transitive_callers, not CallGraph.
        # transitive_caller_symbols_of directly: CallGraph's own stored
        # caller/callee edges were built from name-ambiguous resolution
        # at index-construction time (see call_graph.py's own docstring
        # — deliberate, for impact-analysis use, where over-inclusion is
        # the correct default), so even a CORRECTLY disambiguated
        # `symbol` here can have a caller/callee set inflated by every
        # OTHER same-named symbol's real callers. Same technique as Fix
        # #9 (arcf-drp-issue3-experiment), generalized to classic's own
        # resolution path instead of staying DRP-internal.
        caller_hops = locality_filtered_transitive_callers(
            self._index, self._index.call_graph, symbol.id, symbol.file_path, traversal_depth
        )
        for caller_id, (hop, parent_id) in sorted(
            caller_hops.items(), key=lambda item: (item[1][0], item[0])
        ):
            caller_symbol = self._index.symbol_index.get(caller_id)
            caller_file_path = (
                caller_symbol.file_path if caller_symbol is not None else symbol.file_path
            )
            call_edges.append(
                CallEdge(
                    caller_symbol_id=caller_id,
                    callee_symbol_id=parent_id,
                    file_path=caller_file_path,
                )
            )
            if caller_symbol is None:
                continue
            impacted_symbols[caller_id] = caller_symbol
            if not budget.allow(caller_symbol.file_path):
                continue
            chain = self._chain_for(name, caller_hops, caller_id, verb="called by")
            self._add_file(
                candidate_files,
                file_reasons,
                file_chains,
                file_tiers,
                caller_symbol.file_path,
                f"calls {name} (hop {hop})",
                chain,
                EvidenceTier.SUPPORTING,
            )
            max_hop = max(max_hop, hop)

        callee_hops = locality_filtered_transitive_callees(
            self._index, self._index.call_graph, symbol.id, symbol.file_path, traversal_depth
        )
        for callee_id, (hop, parent_id) in sorted(
            callee_hops.items(), key=lambda item: (item[1][0], item[0])
        ):
            callee_symbol = self._index.symbol_index.get(callee_id)
            parent_symbol = self._index.symbol_index.get(parent_id)
            caller_file_path = (
                parent_symbol.file_path if parent_symbol is not None else symbol.file_path
            )
            call_edges.append(
                CallEdge(
                    caller_symbol_id=parent_id,
                    callee_symbol_id=callee_id,
                    file_path=caller_file_path,
                )
            )
            if callee_symbol is None:
                continue
            impacted_symbols[callee_id] = callee_symbol
            if not budget.allow(callee_symbol.file_path):
                continue
            chain = self._chain_for(name, callee_hops, callee_id, verb="calls")
            self._add_file(
                candidate_files,
                file_reasons,
                file_chains,
                file_tiers,
                callee_symbol.file_path,
                f"called by {name} (hop {hop})",
                chain,
                EvidenceTier.SUPPORTING,
            )
            max_hop = max(max_hop, hop)

        return max_hop

    def _expand_subclasses(
        self,
        symbol: Symbol,
        name: str,
        traversal_depth: int | None,
        candidate_files: set[str],
        file_reasons: dict[str, str],
        file_chains: dict[str, tuple[str, ...]],
        file_tiers: dict[str, EvidenceTier],
        impacted_symbols: dict[str, Symbol],
    ) -> int:
        for subclass_file in self._index.candidate_selector.subclasses_of(name, traversal_depth):
            self._add_file(
                candidate_files,
                file_reasons,
                file_chains,
                file_tiers,
                subclass_file,
                f"extends {name}",
                (),
                EvidenceTier.SUPPORTING,
            )
        max_hop = 0
        for subclass_id in self._index.inheritance_graph.all_subclasses_of(
            symbol.id, traversal_depth
        ):
            subclass_symbol = self._index.symbol_index.get(subclass_id)
            if subclass_symbol is not None:
                impacted_symbols[subclass_id] = subclass_symbol
                max_hop = max(max_hop, 1)
        return max_hop

    def _attach_call_site_symbols(
        self, file_path: str, callee_name: str, impacted_symbols: dict[str, Symbol]
    ) -> None:
        """Hop-1 module-level call sites (the loop above this method's
        only call site) add a FILE via `_add_file`, but have no Symbol to
        record in `impacted_symbols`. Without one, ContextBudgetManager's
        `_symbols_by_file` has nothing to compress *around* for that
        file, so it falls back to full-content-if-it-fits regardless of
        EvidenceTier — a real, measured bug (a 34K-token file,
        fastapi/applications.py, escaped compression this way testing
        ARCF Phase 7's LSE spike, unrelated to LSE itself).

        Two distinct real cases, both handled here — verified against the
        actual repro before assuming either: candidate_selector.py's
        `callers_of()` returns a file for TWO different reasons that
        collapse into the same generic "calls {name}" reason string:

        1. The file DEFINES a symbol also named `callee_name` (its own
           "plus the file(s) defining it" clause, matched via
           `find_by_name` independent of whichever specific same-named
           symbol the entry point actually disambiguated to elsewhere in
           `resolve()` — this is what fastapi/applications.py hit: it
           defines its own `middleware` METHOD, unrelated to the
           `middleware` symbol resolved as the actual entry point). A
           real Symbol already exists here — reuse it directly, no need
           to synthesize anything.
        2. The file contains an actual module-level CALL to
           `callee_name` (real recursion case for the module-level-call-
           sites path this loop was originally written for). No declared
           Symbol owns that call site, so one is synthesized at the
           call's own real location — never a guess. `id` is prefixed
           distinctly (`<call-site:...>`) so it can never be confused
           with a real declared symbol if ever inspected; `kind=FUNCTION`
           is the closest existing vocabulary fits (only affects
           `_enrich_with_constructors`' METHOD-specific check elsewhere,
           which a synthetic FUNCTION-kind entry never trips).
        """
        for symbol in self._index.symbol_index.by_file(file_path):
            if symbol.name == callee_name:
                impacted_symbols.setdefault(symbol.id, symbol)

        analysis = self._index.file_analyses.get(file_path)
        if analysis is None:
            return
        for call in analysis.calls:
            if call.callee_name != callee_name:
                continue
            synthetic_id = f"{file_path}::<call-site:{callee_name}>#{call.location.start_line}"
            impacted_symbols.setdefault(
                synthetic_id,
                Symbol(
                    id=synthetic_id,
                    name=callee_name,
                    qualified_name=callee_name,
                    kind=SymbolKind.FUNCTION,
                    file_path=file_path,
                    location=call.location,
                ),
            )

    def _enrich_with_constructors(
        self, impacted_symbols: dict[str, Symbol], entry_point_symbols: list[Symbol]
    ) -> None:
        """ARCF hardening §8: every selected METHOD symbol's enclosing
        class's constructor rides along, so downstream compression
        (context/compressor.py) never extracts a method's excerpt without
        the initialization context that gives it meaning. The
        constructor's file is always already a candidate (it's the same
        file as the method that triggered this), so only impacted_symbols
        needs enriching — no new file/reason bookkeeping required.

        Feature C (AST Enclosing Scope Slicing, 2026-08-11): the parent
        CLASS symbol itself now rides along too, not just its
        constructor — SymbolRangeCompressor.extract_with_ast_scope needs
        the class's own declaration line to slice a method's excerpt
        with its enclosing type/struct/class header attached. Reuses
        parent_id, already computed once by each LanguageAnalyzer's
        tree-sitter parse at index-build time — no new parsing here,
        consistent with this class's existing "bookkeeping, not
        traversal" role (see module docstring)."""
        method_symbols = [
            symbol
            for symbol in (*impacted_symbols.values(), *entry_point_symbols)
            if symbol.kind is SymbolKind.METHOD and symbol.parent_id is not None
        ]
        for method in method_symbols:
            assert method.parent_id is not None
            parent = self._index.symbol_index.get(method.parent_id)
            if parent is None or parent.kind is not SymbolKind.CLASS:
                continue
            impacted_symbols.setdefault(parent.id, parent)
            constructor = self._find_constructor(parent)
            if (
                constructor is not None
                and constructor.id != method.id
                and constructor.id not in impacted_symbols
            ):
                impacted_symbols[constructor.id] = constructor

    def _find_constructor(self, parent: Symbol) -> Symbol | None:
        language = self._language_of(parent.file_path)
        if language in _CONSTRUCTOR_MATCHES_CLASS_NAME_LANGUAGES:
            constructor_names: frozenset[str] = frozenset({parent.name})
        else:
            constructor_names = _CONSTRUCTOR_NAMES_BY_LANGUAGE.get(language, frozenset())
        if not constructor_names:
            return None
        for sibling in self._index.symbol_index.by_file(parent.file_path):
            if (
                sibling.kind is SymbolKind.METHOD
                and sibling.parent_id == parent.id
                and sibling.name in constructor_names
            ):
                return sibling
        return None

    def _chain_for(
        self,
        entry_name: str,
        hops: dict[str, tuple[int, str]],
        target_id: str,
        verb: str,
    ) -> tuple[str, ...]:
        """Walks parent pointers from `target_id` back to the entry point,
        returning labels ordered from the entry point outward — e.g. for a
        caller-direction chain, ("defines authenticate", "called by
        Service.login", "called by Controller.handle_login")."""
        path: list[str] = []
        seen: set[str] = set()
        current = target_id
        # `seen` guard is defense in depth, not the primary fix (that's
        # CallGraph._layered_bfs excluding `start` from its own frontier —
        # see its docstring): a hops dict built correctly is already
        # acyclic, but this walk has no other bound, so a future
        # self- or mutually-referential edge slipping through upstream
        # would otherwise still grow `path` without limit.
        while current in hops and current not in seen:
            seen.add(current)
            path.append(current)
            current = hops[current][1]
        path.reverse()
        return (
            f"defines {entry_name}",
            *(f"{verb} {self._display_name(node_id)}" for node_id in path),
        )

    def _display_name(self, symbol_id: str) -> str:
        symbol = self._index.symbol_index.get(symbol_id)
        return symbol.name if symbol is not None else symbol_id.rsplit("::", 1)[-1]

    @staticmethod
    def _add_file(
        candidate_files: set[str],
        file_reasons: dict[str, str],
        file_chains: dict[str, tuple[str, ...]],
        file_tiers: dict[str, EvidenceTier],
        file_path: str,
        reason: str,
        chain: tuple[str, ...],
        tier: EvidenceTier,
        file_ambiguity_confidence: dict[str, float] | None = None,
        ambiguity_confidence: float | None = None,
    ) -> None:
        candidate_files.add(file_path)
        file_reasons.setdefault(file_path, reason)
        file_chains.setdefault(file_path, chain)
        # PRIMARY always wins over SUPPORTING, regardless of which one this
        # file was FIRST reached through — target_names iteration order is
        # not a confidence ranking, so (unlike reason/chain above) this is
        # a merge, not a first-write-wins default: a file some other,
        # lower-confidence path also happened to reach via fan-out is
        # still primary evidence if any confident match resolves to it.
        if tier is EvidenceTier.PRIMARY or file_path not in file_tiers:
            file_tiers[file_path] = tier
        # Feature A (ambiguity decay): only ever passed by the direct
        # "defines {name}" entry-point call site below — every other
        # caller leaves this None, matching file_reasons/file_chains'
        # own first-write-wins discipline rather than letting a later,
        # unrelated hop-expansion visit to the same file clobber it.
        if (
            ambiguity_confidence is not None
            and file_ambiguity_confidence is not None
            and file_path not in file_ambiguity_confidence
        ):
            file_ambiguity_confidence[file_path] = ambiguity_confidence

    def _to_symbol_reference(self, symbol: Symbol) -> SymbolReference:
        return SymbolReference(
            symbol_id=symbol.id,
            name=symbol.name,
            qualified_name=symbol.qualified_name,
            kind=symbol.kind,
            file_path=symbol.file_path,
            start_line=symbol.location.start_line,
            end_line=symbol.location.end_line,
            parent_symbol_id=symbol.parent_id,
        )

    def _language_of(self, file_path: str) -> str:
        analysis = self._index.file_analyses.get(file_path)
        return analysis.language if analysis is not None else "unknown"

    def _dominant_language(self, candidate_files: set[str]) -> str:
        languages = [self._language_of(file_path) for file_path in candidate_files]
        if not languages:
            return "unknown"
        return Counter(languages).most_common(1)[0][0]

    @staticmethod
    def _build_reason(total_targets: int, resolved_count: int, candidate_files: set[str]) -> str:
        if total_targets == 0:
            return "No target names provided; nothing to resolve."
        parts = [f"Resolved {resolved_count}/{total_targets} target name(s) to known symbols."]
        if candidate_files:
            parts.append(
                f"Selected {len(candidate_files)} candidate file(s) via direct definition, "
                "call, and inheritance relationships."
            )
        else:
            parts.append("No candidate files found.")
        return " ".join(parts)


class _TokenBudget:
    """Deterministic token-budget gate for unbounded traversal
    (traversal_depth=None). Files are already sorted into the traversal
    by hop before this is consulted, so "closest to the entry point
    fits first" falls out naturally rather than needing its own
    priority logic here."""

    def __init__(
        self,
        index: CodeIntelligenceIndex,
        candidate_files: set[str],
        max_expansion_tokens: int | None,
    ) -> None:
        self._index = index
        self._candidate_files = candidate_files
        self._max_expansion_tokens = max_expansion_tokens

    def allow(self, file_path: str) -> bool:
        if self._max_expansion_tokens is None:
            return True
        if file_path in self._candidate_files:
            return True
        current = sum(self._index.token_counts.get(f, 0) for f in self._candidate_files)
        return current + self._index.token_counts.get(file_path, 0) <= self._max_expansion_tokens
