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
"""

from collections import defaultdict

from code_intelligence.reference_resolver import ReferenceResolver
from domain.code_intelligence import CallReference, SymbolKind


class CallGraph:
    def __init__(self, calls: list[CallReference], resolver: ReferenceResolver) -> None:
        self._caller_symbols_of: dict[str, set[str]] = defaultdict(set)
        self._callee_symbols_of: dict[str, set[str]] = defaultdict(set)
        self._caller_files_of: dict[str, set[str]] = defaultdict(set)
        self._unresolved: list[CallReference] = []

        callable_kinds = (SymbolKind.FUNCTION, SymbolKind.METHOD)
        for call in calls:
            callees = resolver.resolve(call.callee_name, kinds=callable_kinds)
            if not callees:
                self._unresolved.append(call)
                continue
            for callee in callees:
                self._caller_files_of[callee.id].add(call.file_path)
                if call.caller_id is not None:
                    self._callee_symbols_of[call.caller_id].add(callee.id)
                    self._caller_symbols_of[callee.id].add(call.caller_id)

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
