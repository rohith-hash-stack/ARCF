"""RustLanguageAnalyzer — LanguageAnalyzer implementation for Rust, via
tree-sitter-rust.

Grammar node types/field names below (struct_item's/enum_item's/trait_item's
[name/body], impl_item's [type/trait/body], function_item's/
function_signature_item's [name/parameters/body], call_expression's
[function/arguments], field_expression's [value/field], scoped_identifier's
[path/name], use_declaration's argument [scoped_identifier/identifier/
use_as_clause/use_wildcard/scoped_use_list], mod_item's [name/body]) were
verified empirically against the installed tree-sitter-rust grammar, not
assumed from memory.

Structurally closest to Go's analyzer, for a similar reason: Rust
separates a type's DATA (`struct`/`enum` item) from its BEHAVIOR (one or
more separate `impl TypeName { ... }` blocks, or `impl Trait for TypeName
{ ... }` blocks), each naming the type BY TEXT via `impl_item`'s `type`
field rather than lexical nesting — the same "declared separately,
resolve by name" problem Go's receiver methods pose. So, as with Go and
C/C++:

1. `_collect_type_declarations` walks the whole tree first (mod-aware,
   Rust's `mod` nesting is qualified with "::" like a namespace, not
   captured as parent_id since a module is not a CLASS/FUNCTION Symbol)
   building CLASS symbols for `struct_item`/`enum_item` (enums have no
   dedicated SymbolKind, so — mirroring Go's struct->CLASS choice — both
   map to CLASS) and INTERFACE symbols for `trait_item`, into
   `types_by_name` (keyed by simple name only, same documented
   simplification as Go's package-level map: same name in two different
   modules collides, last one wins). Unlike C++/Go, a bare `struct Marker;`
   (a real, complete "unit struct" with no braces at all — Rust has no
   forward-declaration syntax for structs) still counts as a definition,
   so — unlike the C++ analyzer's forward-declaration check — this does
   NOT require a `body` field to be present, only `name`.

2. `_visit_children` walks the whole tree again, resolving:
   - `impl_item`'s methods via its `type` field text and a
     `types_by_name` lookup (methods land on the concrete type being
     impl'd even for `impl Trait for Type`, never on the trait itself —
     trait *default* method bodies, which live directly inside
     `trait_item`, are instead resolved through `trait_item`'s own
     already-built INTERFACE symbol, the same immediate-nesting case
     C++'s class body is),
   - free functions, module-qualified by the enclosing `mod_path`
     (joined with "::", Rust's own path syntax) but never given a
     `parent_id` (a module is not a CLASS/FUNCTION Symbol),
   - calls (identifier / `obj.field()` / `Type::method()` or
     `module::func()`),
   - `use` declarations.

Both passes are iterative explicit-stack pre-order traversals for the same
reason as every other analyzer here: deeply nested real-world Rust
(heavily macro-generated code, deeply chained builder APIs) can overflow
Python's call stack. The small `use`-argument dispatch is plain recursion
(`_extract_use_argument`), since a `use` path's own AST is always a few
levels deep at most, unlike a whole file body.

Import resolution: `use crate::a::b`/`use self::x`/`use super::y` name a
module path relative to the crate/current/parent module — Rust's module
system maps a path segment to either `segment.rs` or `segment/mod.rs` on
disk, and (like Go's module-qualified imports) the crate's own name never
appears in workspace-relative paths. `_resolve_use_path` strips the
leading `crate`/`self`/`super` segment, then — mirroring Go's
progressively-shorter-suffix search — tries each suffix of the remaining
path against both on-disk conventions. A `use std::...` or third-party
crate path is left unresolved, same treatment Go gives stdlib/third-party
imports.
"""

from dataclasses import dataclass, field

import tree_sitter_rust as tsrust
from tree_sitter import Language, Node, Parser

from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)

_RUST_LANGUAGE = Language(tsrust.language())

_LOCAL_USE_PREFIXES = ("crate", "self", "super")


@dataclass
class _WalkContext:
    file_path: str
    workspace_files: frozenset[str]
    source_bytes: bytes
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[CallReference] = field(default_factory=list)
    imports: list[ImportReference] = field(default_factory=list)
    types_by_name: dict[str, Symbol] = field(default_factory=dict)


class RustLanguageAnalyzer:
    @property
    def language(self) -> str:
        return "rust"

    def handles(self, file_path: str) -> bool:
        return file_path.endswith(".rs")

    def analyze_file(
        self, file_path: str, source_text: str, workspace_files: frozenset[str]
    ) -> FileAnalysis:
        source_bytes = source_text.encode("utf-8")
        # A fresh Parser per call — tree-sitter Parser objects aren't safe
        # to share across concurrent threads; _RUST_LANGUAGE itself is
        # immutable and fine to reuse.
        tree = Parser(_RUST_LANGUAGE).parse(source_bytes)

        ctx = _WalkContext(
            file_path=file_path, workspace_files=workspace_files, source_bytes=source_bytes
        )
        self._collect_type_declarations(tree.root_node, ctx, ())
        self._visit_children(tree.root_node, (), [], ctx)

        parse_errors = (
            ["Syntax error encountered; results may be partial"] if tree.root_node.has_error else []
        )

        return FileAnalysis(
            file_path=file_path,
            language=self.language,
            symbols=ctx.symbols,
            calls=ctx.calls,
            imports=ctx.imports,
            parse_errors=parse_errors,
        )

    # -- pass 1: struct/enum/trait declarations -----------------------------

    def _collect_type_declarations(
        self, root: Node, ctx: _WalkContext, mod_path: tuple[str, ...]
    ) -> None:
        stack: list[tuple[Node, tuple[str, ...]]] = [
            (child, mod_path) for child in reversed(root.children)
        ]
        while stack:
            node, path = stack.pop()

            if node.type == "mod_item":
                name_node = node.child_by_field_name("name")
                body = node.child_by_field_name("body")
                if name_node is not None and body is not None:
                    new_path = (*path, self._text(name_node, ctx))
                    stack.extend((c, new_path) for c in reversed(body.children))
                continue

            if node.type in ("struct_item", "enum_item"):
                self._build_type_symbol(node, ctx, path, SymbolKind.CLASS)
                continue

            if node.type == "trait_item":
                self._build_type_symbol(node, ctx, path, SymbolKind.INTERFACE)
                continue

            stack.extend((c, path) for c in reversed(node.children))

    def _build_type_symbol(
        self, node: Node, ctx: _WalkContext, mod_path: tuple[str, ...], kind: SymbolKind
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return  # every struct/enum/trait names itself; absent means malformed source
        name = self._text(name_node, ctx)
        qualified_name = "::".join((*mod_path, name)) if mod_path else name
        location = self._location(node, ctx.file_path)
        symbol = Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=kind,
            file_path=ctx.file_path,
            location=location,
        )
        ctx.symbols.append(symbol)
        ctx.types_by_name[name] = symbol

    # -- pass 2: impls/functions/calls/uses ---------------------------------

    def _visit_children(
        self,
        root: Node,
        mod_path: tuple[str, ...],
        scope_stack: list[Symbol],
        ctx: _WalkContext,
    ) -> None:
        # Iterative, explicit-stack pre-order traversal — see the module
        # docstring for why plain recursion isn't safe here.
        Frame = tuple[Node, tuple[str, ...], list[Symbol]]
        stack: list[Frame] = [(child, mod_path, scope_stack) for child in reversed(root.children)]
        while stack:
            node, path, scope = stack.pop()

            if node.type == "mod_item":
                name_node = node.child_by_field_name("name")
                body = node.child_by_field_name("body")
                if name_node is not None and body is not None:
                    new_path = (*path, self._text(name_node, ctx))
                    stack.extend((c, new_path, scope) for c in reversed(body.children))
                continue

            if node.type == "trait_item":
                name_node = node.child_by_field_name("name")
                body = node.child_by_field_name("body")
                if name_node is None or body is None:
                    continue
                trait_symbol = ctx.types_by_name.get(self._text(name_node, ctx))
                new_scope = [*scope, trait_symbol] if trait_symbol is not None else scope
                stack.extend((c, path, new_scope) for c in reversed(body.children))
                continue

            if node.type == "impl_item":
                type_node = node.child_by_field_name("type")
                body = node.child_by_field_name("body")
                if type_node is None or body is None:
                    continue
                target = ctx.types_by_name.get(self._text(type_node, ctx))
                new_scope = [*scope, target] if target is not None else scope
                stack.extend((c, path, new_scope) for c in reversed(body.children))
                continue

            if node.type in ("function_item", "function_signature_item"):
                symbol = self._build_function_or_method_symbol(node, path, scope, ctx)
                if symbol is None:
                    stack.extend((c, path, scope) for c in reversed(node.children))
                    continue
                ctx.symbols.append(symbol)
                body = node.child_by_field_name("body")
                if body is not None:
                    new_scope = [*scope, symbol]
                    stack.extend((c, path, new_scope) for c in reversed(body.children))
                continue

            if node.type == "call_expression":
                self._record_call(node, scope, ctx)
                stack.extend((c, path, scope) for c in reversed(node.children))
                continue

            if node.type == "use_declaration":
                argument = node.child_by_field_name("argument")
                if argument is not None:
                    self._extract_use_argument(argument, "", ctx, node)
                continue

            stack.extend((c, path, scope) for c in reversed(node.children))

    def _build_function_or_method_symbol(
        self, node: Node, mod_path: tuple[str, ...], scope: list[Symbol], ctx: _WalkContext
    ) -> Symbol | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        name = self._text(name_node, ctx)
        location = self._location(node, ctx.file_path)

        parent = (
            scope[-1] if scope and scope[-1].kind in (SymbolKind.CLASS, SymbolKind.INTERFACE) else None
        )
        if parent is not None:
            qualified_name = f"{parent.qualified_name}::{name}"
            return Symbol(
                id=self._symbol_id(ctx.file_path, qualified_name, location),
                name=name,
                qualified_name=qualified_name,
                kind=SymbolKind.METHOD,
                file_path=ctx.file_path,
                location=location,
                parent_id=parent.id,
            )

        qualified_name = "::".join((*mod_path, name)) if mod_path else name
        return Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=SymbolKind.FUNCTION,
            file_path=ctx.file_path,
            location=location,
            parent_id=None,
        )

    # -- calls ----------------------------------------------------------

    def _record_call(self, call_node: Node, scope: list[Symbol], ctx: _WalkContext) -> None:
        func_node = call_node.child_by_field_name("function")
        callee_name = self._callee_name(func_node, ctx) if func_node else None
        if callee_name is None:
            return
        caller = self._nearest_callable(scope)
        ctx.calls.append(
            CallReference(
                caller_id=caller.id if caller else None,
                callee_name=callee_name,
                file_path=ctx.file_path,
                location=self._location(call_node, ctx.file_path),
            )
        )

    def _callee_name(self, func_node: Node, ctx: _WalkContext) -> str | None:
        if func_node.type == "identifier":
            return self._text(func_node, ctx)
        if func_node.type == "field_expression":
            field_node = func_node.child_by_field_name("field")
            return self._text(field_node, ctx) if field_node else None
        if func_node.type == "scoped_identifier":
            name_node = func_node.child_by_field_name("name")
            return self._text(name_node, ctx) if name_node else self._text(func_node, ctx)
        return None

    @staticmethod
    def _nearest_callable(scope: list[Symbol]) -> Symbol | None:
        for symbol in reversed(scope):
            if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                return symbol
        return None

    # -- imports ----------------------------------------------------------

    def _extract_use_argument(
        self, node: Node, prefix: str, ctx: _WalkContext, use_node: Node
    ) -> None:
        # Import path trees are always a few levels deep at most (unlike a
        # whole file body), so plain recursion here is safe.
        if node.type in ("identifier", "self", "crate", "super"):
            raw_module = self._join(prefix, self._text(node, ctx))
            self._record_import(raw_module, [self._text(node, ctx)], use_node, ctx)
            return

        if node.type == "scoped_identifier":
            path_node = node.child_by_field_name("path")
            name_node = node.child_by_field_name("name")
            path_text = self._text(path_node, ctx) if path_node is not None else ""
            name_text = self._text(name_node, ctx) if name_node is not None else ""
            raw_module = self._join(prefix, f"{path_text}::{name_text}" if path_text else name_text)
            self._record_import(raw_module, [name_text], use_node, ctx)
            return

        if node.type == "use_as_clause":
            path_node = node.child_by_field_name("path")
            alias_node = node.child_by_field_name("alias")
            if path_node is None:
                return
            raw_path = self._text(path_node, ctx)
            raw_module = self._join(prefix, raw_path)
            alias = self._text(alias_node, ctx) if alias_node is not None else raw_path.rsplit("::", 1)[-1]
            self._record_import(raw_module, [alias], use_node, ctx)
            return

        if node.type == "use_wildcard":
            path_node = next(
                (c for c in node.children if c.type in ("scoped_identifier", "identifier")), None
            )
            path_text = self._text(path_node, ctx) if path_node is not None else ""
            raw_module = self._join(prefix, f"{path_text}::*" if path_text else "*")
            self._record_import(raw_module, ["*"], use_node, ctx)
            return

        if node.type == "scoped_use_list":
            path_node = node.child_by_field_name("path")
            list_node = node.child_by_field_name("list")
            base = self._join(prefix, self._text(path_node, ctx)) if path_node is not None else prefix
            if list_node is not None:
                for entry in list_node.children:
                    if entry.type in (
                        "identifier",
                        "scoped_identifier",
                        "use_as_clause",
                        "use_wildcard",
                        "scoped_use_list",
                        "self",
                    ):
                        self._extract_use_argument(entry, base, ctx, use_node)
            return

    @staticmethod
    def _join(prefix: str, path: str) -> str:
        return f"{prefix}::{path}" if prefix else path

    def _record_import(
        self, raw_module: str, imported_names: list[str], use_node: Node, ctx: _WalkContext
    ) -> None:
        resolved = self._resolve_use_path(raw_module, ctx.workspace_files)
        ctx.imports.append(
            ImportReference(
                source_file=ctx.file_path,
                raw_module=raw_module,
                imported_names=imported_names,
                resolved_file_path=resolved,
                location=self._location(use_node, ctx.file_path),
            )
        )

    @staticmethod
    def _resolve_use_path(raw_path: str, workspace_files: frozenset[str]) -> str | None:
        segments = raw_path.split("::")
        if not segments or segments[0] not in _LOCAL_USE_PREFIXES:
            return None
        remainder = [s for s in segments[1:] if s != "*"]
        if not remainder:
            return None
        for start in range(len(remainder)):
            suffix_path = "/".join(remainder[start:])
            candidates = (f"{suffix_path}.rs", f"{suffix_path}/mod.rs")
            matches = sorted(
                f for f in workspace_files if f.endswith(".rs") and any(
                    f == c or f.endswith("/" + c) for c in candidates
                )
            )
            if matches:
                return matches[0]
        return None

    # -- node helpers ---------------------------------------------------

    @staticmethod
    def _text(node: Node, ctx: _WalkContext) -> str:
        return ctx.source_bytes[node.start_byte : node.end_byte].decode("utf-8")

    @staticmethod
    def _location(node: Node, file_path: str) -> SourceLocation:
        return SourceLocation(
            file_path=file_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

    @staticmethod
    def _symbol_id(file_path: str, qualified_name: str, location: SourceLocation) -> str:
        return f"{file_path}::{qualified_name}#{location.start_line}"
