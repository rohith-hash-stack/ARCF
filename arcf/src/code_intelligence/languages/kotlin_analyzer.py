"""KotlinLanguageAnalyzer — sixth and final LanguageAnalyzer
implementation for Stage 6 of the v2.3 migration plan (see
arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md Sec. 2.3/6/7), via
tree-sitter-kotlin.

This grammar exposes far fewer named fields than tree-sitter-python/
-typescript/-java/-c-sharp — only function_declaration.name and
class_declaration.name are populated; everything else (body,
parameters, call targets, delegation/base-type lists, import
qualifiers) has to be found by node TYPE and position among a node's
children, verified empirically against the installed grammar rather
than assumed. Where a field isn't available, this file matches on
type: a "class_declaration" node is a Kotlin interface rather than a
class if one of its direct children has type "interface" instead of
"class" (Kotlin's own grammar uses one node type for both).

Single recursive descent, same shape as JavaLanguageAnalyzer's/
CSharpLanguageAnalyzer's — Kotlin also lexically nests functions
inside class/interface bodies. Function-valued properties
(`val handler = { ... }` a lambda, or `val f = fun() { ... }` an
anonymous function) are treated as FUNCTION/METHOD symbols, the same
"function as a value" pattern TypeScriptLanguageAnalyzer's/
GoLanguageAnalyzer's arrow-function/func-literal handling already
establishes.

Import resolution mirrors JavaLanguageAnalyzer's two-step fallback
(direct class-file guess, then package-directory-minus-last-segment)
plus GoLanguageAnalyzer's/CSharpLanguageAnalyzer's representative-file
heuristic for wildcard imports — Kotlin's package-to-directory
convention is looser than Java's (multiple top-level declarations per
file are normal), so neither guess is guaranteed, but both are honest,
documented best effort rather than a silent assumption.
"""

from dataclasses import dataclass, field

import tree_sitter_kotlin as tsk
from tree_sitter import Language, Node, Parser

from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)

_KOTLIN_LANGUAGE = Language(tsk.language())


@dataclass
class _WalkContext:
    file_path: str
    workspace_files: frozenset[str]
    source_bytes: bytes
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[CallReference] = field(default_factory=list)
    imports: list[ImportReference] = field(default_factory=list)


class KotlinLanguageAnalyzer:
    @property
    def language(self) -> str:
        return "kotlin"

    def handles(self, file_path: str) -> bool:
        return file_path.endswith((".kt", ".kts"))

    def analyze_file(
        self, file_path: str, source_text: str, workspace_files: frozenset[str]
    ) -> FileAnalysis:
        source_bytes = source_text.encode("utf-8")
        # A fresh Parser per call — tree-sitter Parser objects aren't safe
        # to share across concurrent threads; _KOTLIN_LANGUAGE itself is
        # immutable and fine to reuse.
        tree = Parser(_KOTLIN_LANGUAGE).parse(source_bytes)

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
                symbol = self._build_class_or_interface_symbol(
                    node, node_scope, node_qualname, ctx
                )
                ctx.symbols.append(symbol)
                body = next((c for c in node.children if c.type == "class_body"), None)
                if body is not None:
                    new_scope = [*node_scope, symbol]
                    new_qual = [*node_qualname, symbol.name]
                    stack.extend((c, new_scope, new_qual) for c in reversed(body.children))
                continue

            if node.type == "function_declaration":
                func_symbol = self._build_named_symbol(
                    node.child_by_field_name("name"), node, node_scope, node_qualname, ctx
                )
                if func_symbol is None:
                    stack.extend((c, node_scope, node_qualname) for c in reversed(node.children))
                    continue
                ctx.symbols.append(func_symbol)
                body = next((c for c in node.children if c.type == "function_body"), None)
                if body is not None:
                    new_scope = [*node_scope, func_symbol]
                    new_qual = [*node_qualname, func_symbol.name]
                    stack.extend((c, new_scope, new_qual) for c in reversed(body.children))
                continue

            if node.type == "property_declaration":
                binding = self._function_valued_property(node, node_scope, node_qualname, ctx)
                if binding is not None:
                    symbol, value = binding
                    ctx.symbols.append(symbol)
                    new_scope = [*node_scope, symbol]
                    new_qual = [*node_qualname, symbol.name]
                    stack.extend((c, new_scope, new_qual) for c in reversed(value.children))
                else:
                    stack.extend((c, node_scope, node_qualname) for c in reversed(node.children))
                continue

            if node.type == "call_expression":
                self._record_call(node, node_scope, ctx)
                stack.extend((c, node_scope, node_qualname) for c in reversed(node.children))
                continue

            if node.type == "import":
                self._extract_import(node, ctx)
                continue

            stack.extend((c, node_scope, node_qualname) for c in reversed(node.children))

    def _function_valued_property(
        self,
        node: Node,
        scope_stack: list[Symbol],
        qualname_parts: list[str],
        ctx: _WalkContext,
    ) -> tuple[Symbol, Node] | None:
        var_decl = next((c for c in node.children if c.type == "variable_declaration"), None)
        value = next(
            (c for c in node.children if c.type in ("lambda_literal", "anonymous_function")), None
        )
        if var_decl is None or value is None:
            return None
        name_node = next((c for c in var_decl.children if c.type == "identifier"), None)
        if name_node is None:
            return None

        symbol = self._build_named_symbol(name_node, node, scope_stack, qualname_parts, ctx)
        if symbol is None:
            return None
        return symbol, value

    # -- symbol builders --------------------------------------------------

    def _build_class_or_interface_symbol(
        self, node: Node, scope_stack: list[Symbol], qualname_parts: list[str], ctx: _WalkContext
    ) -> Symbol:
        name_node = node.child_by_field_name("name")
        name = self._text(name_node, ctx) if name_node else "<anonymous>"
        qualified_name = ".".join([*qualname_parts, name])
        parent = scope_stack[-1] if scope_stack else None
        location = self._location(node, ctx.file_path)
        is_interface = any(c.type == "interface" for c in node.children)
        return Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=SymbolKind.INTERFACE if is_interface else SymbolKind.CLASS,
            file_path=ctx.file_path,
            location=location,
            base_names=self._extract_base_names(node, ctx),
            parent_id=parent.id if parent else None,
        )

    def _build_named_symbol(
        self,
        name_node: Node | None,
        location_node: Node,
        scope_stack: list[Symbol],
        qualname_parts: list[str],
        ctx: _WalkContext,
    ) -> Symbol | None:
        if name_node is None:
            return None
        name = self._text(name_node, ctx)
        qualified_name = ".".join([*qualname_parts, name])
        parent = scope_stack[-1] if scope_stack else None
        kind = (
            SymbolKind.METHOD
            if parent is not None and parent.kind in (SymbolKind.CLASS, SymbolKind.INTERFACE)
            else SymbolKind.FUNCTION
        )
        location = self._location(location_node, ctx.file_path)
        return Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=kind,
            file_path=ctx.file_path,
            location=location,
            parent_id=parent.id if parent else None,
        )

    def _extract_base_names(self, class_node: Node, ctx: _WalkContext) -> list[str]:
        delegation = next(
            (c for c in class_node.children if c.type == "delegation_specifiers"), None
        )
        if delegation is None:
            return []
        names = []
        for spec in (c for c in delegation.children if c.type == "delegation_specifier"):
            user_type = self._user_type_of(spec)
            if user_type is None:
                continue
            ident = next((c for c in user_type.children if c.type == "identifier"), None)
            if ident is not None:
                names.append(self._text(ident, ctx))
        return names

    @staticmethod
    def _user_type_of(delegation_specifier: Node) -> Node | None:
        for child in delegation_specifier.children:
            if child.type == "user_type":
                return child
            if child.type == "constructor_invocation":
                return next((c for c in child.children if c.type == "user_type"), None)
        return None

    # -- calls --------------------------------------------------------------

    def _record_call(self, call_node: Node, scope_stack: list[Symbol], ctx: _WalkContext) -> None:
        callee_name = self._callee_name(call_node, ctx)
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

    def _callee_name(self, call_node: Node, ctx: _WalkContext) -> str | None:
        target = call_node.children[0] if call_node.children else None
        if target is None:
            return None
        if target.type == "identifier":
            return self._text(target, ctx)
        if target.type == "navigation_expression":
            identifiers = [c for c in target.children if c.type == "identifier"]
            return self._text(identifiers[-1], ctx) if identifiers else None
        return None

    @staticmethod
    def _nearest_callable(scope_stack: list[Symbol]) -> Symbol | None:
        for symbol in reversed(scope_stack):
            if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                return symbol
        return None

    # -- imports --------------------------------------------------------------

    def _extract_import(self, node: Node, ctx: _WalkContext) -> None:
        qualified = next((c for c in node.children if c.type == "qualified_identifier"), None)
        if qualified is None:
            return
        dotted = self._text(qualified, ctx)
        is_wildcard = any(c.type == "*" for c in node.children)

        alias_node = None
        saw_as = False
        for child in node.children:
            if child.type == "as":
                saw_as = True
            elif saw_as and child.type == "identifier":
                alias_node = child
                break

        if is_wildcard:
            imported_names = ["*"]
        elif alias_node is not None:
            imported_names = [self._text(alias_node, ctx)]
        else:
            imported_names = [dotted.rsplit(".", 1)[-1]]

        resolved = self._resolve_import(dotted, is_wildcard, ctx.workspace_files)
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
    def _resolve_import(
        dotted: str, is_wildcard: bool, workspace_files: frozenset[str]
    ) -> str | None:
        if is_wildcard:
            prefix = dotted.replace(".", "/") + "/"
            matches = sorted(
                f for f in workspace_files if f.startswith(prefix) and f.endswith(".kt")
            )
            return matches[0] if matches else None

        direct = dotted.replace(".", "/") + ".kt"
        if direct in workspace_files:
            return direct
        if "." not in dotted:
            return None

        without_last = dotted.rsplit(".", 1)[0]
        as_file = without_last.replace(".", "/") + ".kt"
        if as_file in workspace_files:
            return as_file

        prefix = without_last.replace(".", "/") + "/"
        matches = sorted(f for f in workspace_files if f.startswith(prefix) and f.endswith(".kt"))
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
