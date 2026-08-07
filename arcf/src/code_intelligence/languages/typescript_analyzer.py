"""TypeScriptLanguageAnalyzer — second LanguageAnalyzer implementation
(Stage 1 of the v2.3 migration plan, see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md
Sec. 2.3/7), via tree-sitter-typescript.

Grammar node types/field names used below (class_declaration.name/body,
class_heritage's extends_clause.value + implements_clause's
type_identifier children, interface_declaration.name/body,
extends_type_clause's repeated "type" field, function_declaration.name/
parameters/body, method_definition.name/body, public_field_definition.
name/value, variable_declarator.name/value, arrow_function.parameters/
body, call_expression.function/arguments, member_expression.object/
property, import_statement.source + import_clause's named_imports/
namespace_import/bare-identifier shapes) were verified empirically
against the installed tree-sitter-typescript grammar (both the
"typescript" and "tsx" dialects), not assumed from memory.

Everything this module knows about TypeScript/JavaScript syntax stays
in this file — it emits only the shared IR (Symbol, CallReference,
ImportReference) defined in domain/code_intelligence.py, exactly like
PythonLanguageAnalyzer. Name resolution (matching a call's callee_name
or a class's base_names against actual Symbols) is deliberately NOT
done here — that's ReferenceResolver's job, working purely off IR.

One thing this analyzer handles that Python's doesn't need to:
TS/JS routinely defines functions as values (`const f = () => {}`,
class-field arrow methods `render = () => {}`) rather than only via
`function`/`def` keywords. Both shapes are treated as a Symbol
(FUNCTION or METHOD, by the same "is the enclosing scope a class?"
rule Python uses) so the call/dependency graphs see them uniformly.
Arrow functions also support a concise (non-block) body — an
expression directly, e.g. `() => doThing()` — so the walk recurses
into whatever node the body field holds rather than assuming a
statement_block.

Best-effort, not a type checker: callee_name is a call's simple name
only (`this.foo()` and `foo()` both record "foo"); base_names are raw
text from `extends`/`implements`. Cross-file resolution of those
strings against real Symbols is ReferenceResolver's job. Import
resolution here only follows relative specifiers (`./`, `../`) against
the workspace file set — bare specifiers (npm packages) are left
unresolved, same treatment Python gives stdlib/third-party imports.
"""

from dataclasses import dataclass, field

import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser

from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)

_TS_LANGUAGE = Language(tsts.language_typescript())
_TSX_LANGUAGE = Language(tsts.language_tsx())

_CLASS_TYPES = ("class_declaration", "abstract_class_declaration")
_FUNCTION_LIKE_TYPES = ("function_declaration", "method_definition", "abstract_method_signature")
_FUNCTION_VALUE_TYPES = ("arrow_function", "function_expression")
_IMPORT_RESOLUTION_SUFFIXES = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    "/index.ts",
    "/index.tsx",
    "/index.js",
    "/index.jsx",
)


@dataclass
class _WalkContext:
    file_path: str
    workspace_files: frozenset[str]
    source_bytes: bytes
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[CallReference] = field(default_factory=list)
    imports: list[ImportReference] = field(default_factory=list)


class TypeScriptLanguageAnalyzer:
    @property
    def language(self) -> str:
        return "typescript"

    def handles(self, file_path: str) -> bool:
        return file_path.endswith((".ts", ".tsx", ".js", ".jsx"))

    def analyze_file(
        self, file_path: str, source_text: str, workspace_files: frozenset[str]
    ) -> FileAnalysis:
        source_bytes = source_text.encode("utf-8")
        grammar = _TSX_LANGUAGE if file_path.endswith((".tsx", ".jsx")) else _TS_LANGUAGE
        # A fresh Parser per call — tree-sitter Parser objects aren't safe
        # to share across concurrent threads; the Language objects
        # themselves are immutable and fine to reuse.
        tree = Parser(grammar).parse(source_bytes)

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
        # files; this stays bounded by heap, not the C call stack. Each
        # stack entry is one "_visit(node, ...)" call, not one child, since
        # the concise-arrow-body case below revisits a single node directly
        # rather than only its children (what the old _visit_children did).
        stack: list[tuple[Node, list[Symbol], list[str]]] = [(root, scope_stack, qualname_parts)]
        while stack:
            node, node_scope, node_qualname = stack.pop()

            if node.type in _CLASS_TYPES:
                symbol = self._build_class_symbol(node, node_scope, node_qualname, ctx)
                ctx.symbols.append(symbol)
                body = node.child_by_field_name("body")
                if body is not None:
                    new_scope = [*node_scope, symbol]
                    new_qualname = [*node_qualname, symbol.name]
                    stack.extend((c, new_scope, new_qualname) for c in reversed(body.children))
                continue

            if node.type == "interface_declaration":
                ctx.symbols.append(
                    self._build_interface_symbol(node, node_scope, node_qualname, ctx)
                )
                continue

            if node.type in _FUNCTION_LIKE_TYPES:
                symbol = self._build_named_symbol(node, node_scope, node_qualname, ctx)
                ctx.symbols.append(symbol)
                body = node.child_by_field_name("body")
                if body is not None:
                    new_scope = [*node_scope, symbol]
                    new_qualname = [*node_qualname, symbol.name]
                    stack.extend((c, new_scope, new_qualname) for c in reversed(body.children))
                continue

            if node.type in ("public_field_definition", "variable_declarator"):
                value = node.child_by_field_name("value")
                name_node = node.child_by_field_name("name")
                if (
                    value is not None
                    and value.type in _FUNCTION_VALUE_TYPES
                    and name_node is not None
                ):
                    symbol = self._build_named_symbol(node, node_scope, node_qualname, ctx)
                    ctx.symbols.append(symbol)
                    new_scope = [*node_scope, symbol]
                    new_qualname = [*node_qualname, symbol.name]
                    fn_body = value.child_by_field_name("body")
                    if fn_body is not None:
                        if fn_body.type == "statement_block":
                            stack.extend(
                                (c, new_scope, new_qualname) for c in reversed(fn_body.children)
                            )
                        else:
                            # Concise arrow body, e.g. `() => doThing()` —
                            # the body field is the expression itself, not
                            # a block, so revisit it directly.
                            stack.append((fn_body, new_scope, new_qualname))
                    continue
                stack.extend((c, node_scope, node_qualname) for c in reversed(node.children))
                continue

            if node.type == "call_expression":
                self._record_call(node, node_scope, ctx)
                stack.extend((c, node_scope, node_qualname) for c in reversed(node.children))
                continue

            if node.type == "import_statement":
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
            base_names=self._extract_class_base_names(node, ctx),
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
            base_names=self._extract_interface_base_names(node, ctx),
            parent_id=parent.id if parent else None,
        )

    def _build_named_symbol(
        self, node: Node, scope_stack: list[Symbol], qualname_parts: list[str], ctx: _WalkContext
    ) -> Symbol:
        """Builds a FUNCTION/METHOD symbol for any of: function_declaration,
        method_definition, abstract_method_signature, a class-field arrow
        (public_field_definition), or a variable-bound arrow/function
        expression (variable_declarator) — all four shapes carry the name
        under the same "name" field."""
        name_node = node.child_by_field_name("name")
        name = self._text(name_node, ctx) if name_node else "<anonymous>"
        qualified_name = ".".join([*qualname_parts, name])
        parent = scope_stack[-1] if scope_stack else None
        kind = (
            SymbolKind.METHOD
            if parent is not None and parent.kind is SymbolKind.CLASS
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

    def _extract_class_base_names(self, class_node: Node, ctx: _WalkContext) -> list[str]:
        heritage = next(
            (c for c in class_node.children if c.type == "class_heritage"), None
        )
        if heritage is None:
            return []
        names: list[str] = []
        for child in heritage.children:
            if child.type == "extends_clause":
                value = child.child_by_field_name("value")
                if value is not None:
                    names.append(self._text(value, ctx))
            elif child.type == "implements_clause":
                names.extend(
                    self._text(t, ctx) for t in child.children if t.type == "type_identifier"
                )
        return names

    def _extract_interface_base_names(self, interface_node: Node, ctx: _WalkContext) -> list[str]:
        clause = next(
            (c for c in interface_node.children if c.type == "extends_type_clause"), None
        )
        if clause is None:
            return []
        return [self._text(t, ctx) for t in clause.children_by_field_name("type")]

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
        if func_node.type == "member_expression":
            prop_node = func_node.child_by_field_name("property")
            return self._text(prop_node, ctx) if prop_node else None
        return None

    @staticmethod
    def _nearest_callable(scope_stack: list[Symbol]) -> Symbol | None:
        for symbol in reversed(scope_stack):
            if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                return symbol
        return None

    # -- imports --------------------------------------------------------------

    def _extract_import(self, node: Node, ctx: _WalkContext) -> None:
        source_node = node.child_by_field_name("source")
        if source_node is None:
            return
        raw_module = self._string_literal_text(source_node, ctx)

        clause = next((c for c in node.children if c.type == "import_clause"), None)
        imported_names = self._extract_imported_names(clause, ctx) if clause is not None else []

        resolved = self._resolve_relative_import(raw_module, ctx.file_path, ctx.workspace_files)
        ctx.imports.append(
            ImportReference(
                source_file=ctx.file_path,
                raw_module=raw_module,
                imported_names=imported_names,
                resolved_file_path=resolved,
                location=self._location(node, ctx.file_path),
            )
        )

    def _extract_imported_names(self, clause: Node, ctx: _WalkContext) -> list[str]:
        names: list[str] = []
        for child in clause.children:
            if child.type == "named_imports":
                for spec in child.children:
                    if spec.type == "import_specifier":
                        name_node = spec.child_by_field_name("name")
                        if name_node is not None:
                            names.append(self._text(name_node, ctx))
            elif child.type == "namespace_import":
                names.append("*")
            elif child.type == "identifier":
                # Default import, e.g. `import Default from '../other'`.
                names.append(self._text(child, ctx))
        return names

    @staticmethod
    def _string_literal_text(string_node: Node, ctx: _WalkContext) -> str:
        fragment = next(
            (c for c in string_node.children if c.type == "string_fragment"), None
        )
        return TypeScriptLanguageAnalyzer._text(fragment, ctx) if fragment else ""

    @staticmethod
    def _resolve_relative_import(
        raw_module: str, current_file: str, workspace_files: frozenset[str]
    ) -> str | None:
        if not raw_module.startswith("."):
            return None  # Bare specifier (npm package) — external, not in-workspace.

        current_dir_parts = (
            current_file.rsplit("/", 1)[0].split("/") if "/" in current_file else []
        )
        parts = list(current_dir_parts)
        for segment in raw_module.split("/"):
            if segment in ("", "."):
                continue
            if segment == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(segment)
        base = "/".join(parts)

        for suffix in _IMPORT_RESOLUTION_SUFFIXES:
            candidate = base + suffix
            if candidate in workspace_files:
                return candidate
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
