"""CSharpLanguageAnalyzer — fifth LanguageAnalyzer implementation (Stage
6 of the v2.3 migration plan, see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md
Sec. 2.3/6/7), via tree-sitter-c-sharp.

Grammar node types/field names used below (class_declaration's [name/
body], the base_list clause listing identifier/generic_name entries
directly (no nested type_list wrapper, unlike Java's super_interfaces),
interface_declaration's [name/body], method_declaration's [name/
parameters/body], invocation_expression's [function/arguments],
member_access_expression's [expression/name], and using_directive's
three shapes — bare `using System;`, dotted `using MyApp.Auth;`, and
aliased `using Helper = MyApp.Util.Helpers;`, discriminated by whether
using_directive's own `name` field is populated (only true for the
aliased form)) were verified empirically against the installed
tree-sitter-c-sharp grammar, not assumed from memory.

Single recursive descent, same shape as JavaLanguageAnalyzer's — C#
also lexically nests methods inside class/interface bodies (and
namespace_declaration bodies too, just descended through without
producing a Symbol for the namespace itself, since NAMESPACE isn't
part of this IR's SymbolKind vocabulary).

Import resolution is deliberately weaker than Java's: a C# `using`
names a NAMESPACE, and C# has no requirement that a namespace map to
one file (or even one directory) — unlike Java's one-class-per-file
convention. This analyzer treats the namespace's dotted segments as a
workspace-relative directory (a fair assumption absent .csproj/project
data this analyzer never sees) and resolves to the alphabetically
first .cs file under it, if any, as a representative file — the same
honest, documented best-effort choice GoLanguageAnalyzer makes for
package imports. `using static SomeClass;` (importing one class's
static members, not a namespace) is out of scope — not handled here,
same as this analyzer's peers each skipping constructs beyond their
core class/interface/method/call/import scope.
"""

from dataclasses import dataclass, field

import tree_sitter_c_sharp as tscsharp
from tree_sitter import Language, Node, Parser

from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)

_CSHARP_LANGUAGE = Language(tscsharp.language())


@dataclass
class _WalkContext:
    file_path: str
    workspace_files: frozenset[str]
    source_bytes: bytes
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[CallReference] = field(default_factory=list)
    imports: list[ImportReference] = field(default_factory=list)


class CSharpLanguageAnalyzer:
    @property
    def language(self) -> str:
        return "csharp"

    def handles(self, file_path: str) -> bool:
        return file_path.endswith(".cs")

    def analyze_file(
        self, file_path: str, source_text: str, workspace_files: frozenset[str]
    ) -> FileAnalysis:
        source_bytes = source_text.encode("utf-8")
        # A fresh Parser per call — tree-sitter Parser objects aren't safe
        # to share across concurrent threads; _CSHARP_LANGUAGE itself is
        # immutable and fine to reuse.
        tree = Parser(_CSHARP_LANGUAGE).parse(source_bytes)

        ctx = _WalkContext(
            file_path=file_path, workspace_files=workspace_files, source_bytes=source_bytes
        )
        self._visit(tree.root_node, [], [], ctx)

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

    # -- tree walking -----------------------------------------------------

    def _visit(
        self,
        root: Node,
        scope_stack: list[Symbol],
        qualname_parts: list[str],
        ctx: _WalkContext,
    ) -> None:
        # Iterative, explicit-stack pre-order traversal — a plain recursive
        # descent overflows Python's call stack on deeply nested real-world
        # files; this stays bounded by heap, not the C call stack. Children
        # are pushed in reverse so pop() yields them in the same
        # left-to-right order the recursive version visited.
        stack: list[tuple[Node, list[Symbol], list[str]]] = [(root, scope_stack, qualname_parts)]
        while stack:
            node, node_scope, node_qualname = stack.pop()

            if node.type == "class_declaration":
                symbol = self._build_class_symbol(node, node_scope, node_qualname, ctx)
                ctx.symbols.append(symbol)
                body = node.child_by_field_name("body")
                if body is not None:
                    new_scope = [*node_scope, symbol]
                    new_qual = [*node_qualname, symbol.name]
                    stack.extend((c, new_scope, new_qual) for c in reversed(body.children))
                continue

            if node.type == "interface_declaration":
                symbol = self._build_interface_symbol(node, node_scope, node_qualname, ctx)
                ctx.symbols.append(symbol)
                body = node.child_by_field_name("body")
                if body is not None:
                    new_scope = [*node_scope, symbol]
                    new_qual = [*node_qualname, symbol.name]
                    stack.extend((c, new_scope, new_qual) for c in reversed(body.children))
                continue

            if node.type == "method_declaration":
                symbol = self._build_method_symbol(node, node_scope, node_qualname, ctx)
                ctx.symbols.append(symbol)
                body = node.child_by_field_name("body")
                if body is not None:
                    new_scope = [*node_scope, symbol]
                    new_qual = [*node_qualname, symbol.name]
                    stack.extend((c, new_scope, new_qual) for c in reversed(body.children))
                continue

            if node.type == "invocation_expression":
                self._record_call(node, node_scope, ctx)
                stack.extend((c, node_scope, node_qualname) for c in reversed(node.children))
                continue

            if node.type == "using_directive":
                self._extract_import(node, ctx)
                continue

            stack.extend((c, node_scope, node_qualname) for c in reversed(node.children))

    # -- symbol builders --------------------------------------------------

    def _build_class_symbol(
        self, node: Node, scope_stack: list[Symbol], qualname_parts: list[str], ctx: _WalkContext
    ) -> Symbol:
        name_node = node.child_by_field_name("name")
        name = self._text(name_node, ctx) if name_node else "<anonymous>"
        qualified_name = ".".join([*qualname_parts, name])
        parent = scope_stack[-1] if scope_stack else None
        location = self._location(node, ctx.file_path)
        return Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=SymbolKind.CLASS,
            file_path=ctx.file_path,
            location=location,
            base_names=self._extract_base_names(node, ctx),
            parent_id=parent.id if parent else None,
        )

    def _build_interface_symbol(
        self, node: Node, scope_stack: list[Symbol], qualname_parts: list[str], ctx: _WalkContext
    ) -> Symbol:
        name_node = node.child_by_field_name("name")
        name = self._text(name_node, ctx) if name_node else "<anonymous>"
        qualified_name = ".".join([*qualname_parts, name])
        parent = scope_stack[-1] if scope_stack else None
        location = self._location(node, ctx.file_path)
        return Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=SymbolKind.INTERFACE,
            file_path=ctx.file_path,
            location=location,
            base_names=self._extract_base_names(node, ctx),
            parent_id=parent.id if parent else None,
        )

    def _build_method_symbol(
        self, node: Node, scope_stack: list[Symbol], qualname_parts: list[str], ctx: _WalkContext
    ) -> Symbol:
        name_node = node.child_by_field_name("name")
        name = self._text(name_node, ctx) if name_node else "<anonymous>"
        qualified_name = ".".join([*qualname_parts, name])
        parent = scope_stack[-1] if scope_stack else None
        kind = (
            SymbolKind.METHOD
            if parent is not None and parent.kind in (SymbolKind.CLASS, SymbolKind.INTERFACE)
            else SymbolKind.FUNCTION
        )
        location = self._location(node, ctx.file_path)
        return Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=kind,
            file_path=ctx.file_path,
            location=location,
            parent_id=parent.id if parent else None,
        )

    def _extract_base_names(self, node: Node, ctx: _WalkContext) -> list[str]:
        base_list = next((c for c in node.children if c.type == "base_list"), None)
        if base_list is None:
            return []
        names = []
        for child in base_list.children:
            if child.type == "identifier":
                names.append(self._text(child, ctx))
            elif child.type == "generic_name":
                base = next((c for c in child.children if c.type == "identifier"), None)
                if base is not None:
                    names.append(self._text(base, ctx))
        return names

    # -- calls --------------------------------------------------------------

    def _record_call(self, call_node: Node, scope_stack: list[Symbol], ctx: _WalkContext) -> None:
        func_node = call_node.child_by_field_name("function")
        callee_name = self._callee_name(func_node, ctx) if func_node else None
        if callee_name is None:
            return
        caller = self._nearest_callable(scope_stack)
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
        if func_node.type == "member_access_expression":
            name_node = func_node.child_by_field_name("name")
            return self._text(name_node, ctx) if name_node else None
        return None

    @staticmethod
    def _nearest_callable(scope_stack: list[Symbol]) -> Symbol | None:
        for symbol in reversed(scope_stack):
            if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                return symbol
        return None

    # -- imports --------------------------------------------------------------

    def _extract_import(self, node: Node, ctx: _WalkContext) -> None:
        alias_node = node.child_by_field_name("name")
        alias_id = alias_node.id if alias_node is not None else None
        value_node = next(
            (
                c
                for c in node.children
                if c.type in ("identifier", "qualified_name") and c.id != alias_id
            ),
            None,
        )
        if value_node is None:
            return

        dotted = self._text(value_node, ctx)
        imported_names = (
            [self._text(alias_node, ctx)] if alias_node is not None else [dotted.rsplit(".", 1)[-1]]
        )
        resolved = self._resolve_namespace(dotted, ctx.workspace_files)
        ctx.imports.append(
            ImportReference(
                source_file=ctx.file_path,
                raw_module=dotted,
                imported_names=imported_names,
                resolved_file_path=resolved,
                location=self._location(node, ctx.file_path),
            )
        )

    @staticmethod
    def _resolve_namespace(dotted: str, workspace_files: frozenset[str]) -> str | None:
        prefix = dotted.replace(".", "/") + "/"
        matches = sorted(f for f in workspace_files if f.startswith(prefix) and f.endswith(".cs"))
        return matches[0] if matches else None

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
