"""SymbolIndex — fast, language-agnostic symbol lookup (Phase 5 deliverable).

One unified index over Symbol.kind rather than four parallel
structures: "class index", "method index", "function index", and
"interface index" (named separately in the playbook) are just
.classes()/.methods()/.functions()/.interfaces() queries here, filtered
by kind. Building four data structures that all have to be kept in
sync for one list of facts would be pure duplication.
"""

from collections import defaultdict

from domain.code_intelligence import Symbol, SymbolKind


class SymbolIndex:
    def __init__(self, symbols: list[Symbol]) -> None:
        self._by_id: dict[str, Symbol] = {}
        self._by_name: dict[str, list[Symbol]] = defaultdict(list)
        self._by_qualified_name: dict[str, list[Symbol]] = defaultdict(list)
        self._by_file: dict[str, list[Symbol]] = defaultdict(list)

        for symbol in symbols:
            self._by_id[symbol.id] = symbol
            self._by_name[symbol.name].append(symbol)
            self._by_qualified_name[symbol.qualified_name].append(symbol)
            self._by_file[symbol.file_path].append(symbol)

    def get(self, symbol_id: str) -> Symbol | None:
        return self._by_id.get(symbol_id)

    def find_by_name(self, name: str) -> list[Symbol]:
        return list(self._by_name.get(name, []))

    def find_by_qualified_name(self, qualified_name: str) -> list[Symbol]:
        return list(self._by_qualified_name.get(qualified_name, []))

    def by_file(self, file_path: str) -> list[Symbol]:
        return list(self._by_file.get(file_path, []))

    def by_kind(self, kind: SymbolKind) -> list[Symbol]:
        return [symbol for symbol in self._by_id.values() if symbol.kind is kind]

    def classes(self) -> list[Symbol]:
        return self.by_kind(SymbolKind.CLASS)

    def functions(self) -> list[Symbol]:
        return self.by_kind(SymbolKind.FUNCTION)

    def methods(self) -> list[Symbol]:
        return self.by_kind(SymbolKind.METHOD)

    def interfaces(self) -> list[Symbol]:
        return self.by_kind(SymbolKind.INTERFACE)

    def all(self) -> list[Symbol]:
        return list(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)
