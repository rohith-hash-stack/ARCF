"""DecoratorGraph (ARCF Phase 7 spike: Language Semantic Enrichment) —
symbol <-> decorator-name edges, structurally analogous to InheritanceGraph
but simpler: a decorator relationship is inherently single-hop (a symbol
either carries a given decorator or it doesn't; there's no transitive
"decorator of a decorator" closure the way subclassing or calling chain).

Indexed two ways, mirroring ReferenceResolver's own exact-then-simple-name
fallback: `decorator_name` in full ("app.get") for precise lookups, and by
its last dotted segment ("get") for callers that only know the bare verb —
e.g. a query mentioning "routes" has no way to know whether a repository's
router variable is named `app`, `router`, or `api`, but "get"/"post"/
"route" are the parts of the expression a query's wording could plausibly
share a lexical root with. Deliberately NOT resolved against SymbolIndex
the way CallGraph/InheritanceGraph resolve callee_name/base_names: a
decorator's callable (`app` in `app.get`) is a variable/instance, not a
declared Symbol this codebase's IR tracks — resolving *that* would require
real data-flow analysis, out of scope for a language-level (not
framework-level) relationship.
"""

from collections import defaultdict

from domain.code_intelligence import DecoratorReference


class DecoratorGraph:
    def __init__(self, decorators: list[DecoratorReference]) -> None:
        self._decorators_of: dict[str, list[DecoratorReference]] = defaultdict(list)
        self._symbols_by_full_name: dict[str, set[str]] = defaultdict(set)
        self._symbols_by_simple_name: dict[str, set[str]] = defaultdict(set)

        for decorator in decorators:
            self._decorators_of[decorator.symbol_id].append(decorator)
            self._symbols_by_full_name[decorator.decorator_name].add(decorator.symbol_id)
            simple_name = decorator.decorator_name.rsplit(".", 1)[-1]
            self._symbols_by_simple_name[simple_name].add(decorator.symbol_id)

    def decorators_of(self, symbol_id: str) -> list[DecoratorReference]:
        """Every decorator applied to `symbol_id`, in source order."""
        return list(self._decorators_of.get(symbol_id, []))

    def symbols_decorated_by(self, decorator_name: str) -> set[str]:
        """Symbol ids carrying a decorator whose full text ("app.get") or
        last dotted segment ("get") matches `decorator_name` exactly —
        full-name matches ONLY when `decorator_name` itself contains a
        dot (so a bare query term never accidentally full-matches a
        qualified decorator it wasn't written to describe)."""
        if "." in decorator_name:
            return set(self._symbols_by_full_name.get(decorator_name, set()))
        return set(self._symbols_by_simple_name.get(decorator_name, set()))

    def known_decorator_names(self) -> set[str]:
        """Every full decorator-name string seen, for lexical probing
        against a query's wording (see multi_hop_orchestrator.py)."""
        return set(self._symbols_by_full_name.keys())
