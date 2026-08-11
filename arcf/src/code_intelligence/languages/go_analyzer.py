"""GoLanguageAnalyzer — third LanguageAnalyzer implementation (Stage 6
of the v2.3 migration plan, see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md
Sec. 2.3/6/7), via tree-sitter-go.

Grammar node types/field names used below (type_declaration's type_spec
[name/type], struct_type's field_declaration_list, interface_type's
method_elem [name/parameters/result], method_declaration's [receiver/
name/parameters/body], function_declaration's [name/body],
call_expression's [function/arguments], selector_expression's
[operand/field], import_declaration's import_spec [name/path]) were
verified empirically against the installed tree-sitter-go grammar, not
assumed from memory.

Structurally different from Python's/TypeScript's single recursive
descent, because Go's own syntax is structurally different: a method's
receiver type is a separate clause referencing a type BY NAME
(`func (b *BasePage) Render() {...}`), not lexical nesting inside a
class body — method_declaration and its receiver's type_declaration
are siblings at the top level, in either order, possibly in different
files of the same package. So this analyzer runs two passes:

1. Collect every type_declaration (struct -> CLASS, interface ->
   INTERFACE) into symbols AND a name -> Symbol map.
2. Walk the tree for function/method declarations and calls, using
   that map to resolve method_declaration's receiver type name to a
   parent_id — never by re-nesting or re-parsing, just a dict lookup
   built once up front.

A struct's embedded fields (`type X struct { BasePage }`, no `name`
field on that field_declaration) are Go's nearest equivalent to
inheritance — recorded as base_names, mirroring how Python's analyzer
extracts base_names from a class's `superclasses` clause.

Import resolution here is honestly weaker than Python's/TypeScript's:
a Go import path (e.g. "myapp/auth") names a PACKAGE (a whole
directory, possibly many files), not one file, whereas
ImportReference.resolved_file_path models a single resolved file. This
analyzer treats the import path as if it were a workspace-relative
directory and, if any workspace .go file lives under it, resolves to
the alphabetically-first one as a representative — a documented,
best-effort choice, not a guess hidden from the caller.

A real Go import is module-qualified (`github.com/org/repo/pkg/auth`),
not workspace-relative (`pkg/auth`) — the module's own declared prefix
(from `go.mod`, never read here) doesn't appear in `workspace_files` at
all. Matching the raw path directly against workspace-relative
directories, as an earlier version of this analyzer did, therefore
NEVER resolved a single Go import in any real multi-segment module path
— confirmed against a real 5,931-import Traefik scan, 0 resolved.
`_resolve_import_path` instead tries progressively shorter suffixes of
the import path (dropping leading segments one at a time: the full
path, then everything after the first segment, then after the second,
...) against `workspace_files`, returning the first (longest, most
specific) suffix that matches — this recovers the workspace-relative
portion of a module-qualified path without ever needing to read
`go.mod`, purely from data already available. A stdlib import
("context") or third-party import with no matching local directory
("github.com/rs/zerolog") tries every suffix and correctly resolves to
nothing, the same as before — this only fixes genuinely local imports.
"""

from dataclasses import dataclass, field

import tree_sitter_go as tsgo
from tree_sitter import Language, Node, Parser

from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)

_GO_LANGUAGE = Language(tsgo.language())


@dataclass
class _WalkContext:
    file_path: str
    workspace_files: frozenset[str]
    source_bytes: bytes
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[CallReference] = field(default_factory=list)
    imports: list[ImportReference] = field(default_factory=list)
    types_by_name: dict[str, Symbol] = field(default_factory=dict)


class GoLanguageAnalyzer:
    @property
    def language(self) -> str:
        return "go"

    def handles(self, file_path: str) -> bool:
        return file_path.endswith(".go")

    def analyze_file(
        self, file_path: str, source_text: str, workspace_files: frozenset[str]
    ) -> FileAnalysis:
        source_bytes = source_text.encode("utf-8")
        # A fresh Parser per call — tree-sitter Parser objects aren't safe
        # to share across concurrent threads; _GO_LANGUAGE itself is
        # immutable and fine to reuse.
        tree = Parser(_GO_LANGUAGE).parse(source_bytes)

        ctx = _WalkContext(
            file_path=file_path, workspace_files=workspace_files, source_bytes=source_bytes
        )
        self._collect_type_declarations(tree.root_node, ctx)
        self._visit_children(tree.root_node, [], ctx)

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

    # -- pass 1: type declarations (structs/interfaces) --------------------

    def _collect_type_declarations(self, root: Node, ctx: _WalkContext) -> None:
        for node in self._find_all(root, "type_declaration"):
            for type_spec in self._find_all(node, "type_spec"):
                self._build_type_symbol(type_spec, ctx)

    def _build_type_symbol(self, type_spec: Node, ctx: _WalkContext) -> None:
        name_node = type_spec.child_by_field_name("name")
        type_node = type_spec.child_by_field_name("type")
        if name_node is None or type_node is None:
            return
        name = self._text(name_node, ctx)
        location = self._location(type_spec, ctx.file_path)

        if type_node.type == "struct_type":
            symbol = Symbol(
                id=self._symbol_id(ctx.file_path, name, location),
                name=name,
                qualified_name=name,
                kind=SymbolKind.CLASS,
                file_path=ctx.file_path,
                location=location,
                base_names=self._extract_embedded_field_names(type_node, ctx),
            )
            ctx.symbols.append(symbol)
            ctx.types_by_name[name] = symbol
        elif type_node.type == "interface_type":
            symbol = Symbol(
                id=self._symbol_id(ctx.file_path, name, location),
                name=name,
                qualified_name=name,
                kind=SymbolKind.INTERFACE,
                file_path=ctx.file_path,
                location=location,
                base_names=self._extract_embedded_interface_names(type_node, ctx),
            )
            ctx.symbols.append(symbol)
            ctx.types_by_name[name] = symbol
            self._collect_interface_methods(type_node, symbol, ctx)

    def _collect_interface_methods(
        self, interface_node: Node, parent: Symbol, ctx: _WalkContext
    ) -> None:
        for method_elem in (c for c in interface_node.children if c.type == "method_elem"):
            name_node = method_elem.child_by_field_name("name")
            if name_node is None:
                continue
            name = self._text(name_node, ctx)
            location = self._location(method_elem, ctx.file_path)
            ctx.symbols.append(
                Symbol(
                    id=self._symbol_id(ctx.file_path, f"{parent.name}.{name}", location),
                    name=name,
                    qualified_name=f"{parent.name}.{name}",
                    kind=SymbolKind.METHOD,
                    file_path=ctx.file_path,
                    location=location,
                    parent_id=parent.id,
                )
            )

    def _extract_embedded_field_names(self, struct_node: Node, ctx: _WalkContext) -> list[str]:
        field_list = next(
            (c for c in struct_node.children if c.type == "field_declaration_list"), None
        )
        if field_list is None:
            return []
        names = []
        for field_decl in field_list.children:
            if field_decl.type != "field_declaration":
                continue
            if field_decl.child_by_field_name("name") is not None:
                continue  # named field, not embedded
            type_node = field_decl.child_by_field_name("type")
            if type_node is not None:
                names.append(self._unwrap_type_name(type_node, ctx))
        return names

    def _extract_embedded_interface_names(
        self, interface_node: Node, ctx: _WalkContext
    ) -> list[str]:
        return [
            self._text(child, ctx)
            for child in interface_node.children
            if child.type == "type_identifier"
        ]

    def _unwrap_type_name(self, type_node: Node, ctx: _WalkContext) -> str:
        if type_node.type == "pointer_type":
            inner = next(
                (c for c in type_node.children if c.type not in ("*",)), None
            )
            return self._unwrap_type_name(inner, ctx) if inner is not None else self._text(
                type_node, ctx
            )
        return self._text(type_node, ctx)

    # -- pass 2: functions/methods/calls/imports ---------------------------

    def _visit_children(self, root: Node, scope_stack: list[Symbol], ctx: _WalkContext) -> None:
        # Iterative, explicit-stack pre-order traversal — a plain recursive
        # descent overflows Python's call stack on deeply nested real-world
        # Go files (e.g. generated deepcopy code); this stays bounded by
        # heap, not the C call stack. Children are pushed in reverse so
        # pop() yields them in the same left-to-right order the recursive
        # version visited. Note this replaces both the old _visit and
        # _visit_children: a stack entry IS one "_visit(node, ...)" call.
        stack: list[tuple[Node, list[Symbol]]] = [
            (child, scope_stack) for child in reversed(root.children)
        ]
        while stack:
            node, node_scope = stack.pop()

            if node.type == "function_declaration":
                symbol = self._build_function_symbol(node, node_scope, ctx)
                ctx.symbols.append(symbol)
                body = node.child_by_field_name("body")
                if body is not None:
                    new_scope = [*node_scope, symbol]
                    stack.extend((c, new_scope) for c in reversed(body.children))
                continue

            if node.type == "method_declaration":
                symbol = self._build_method_symbol(node, ctx)
                ctx.symbols.append(symbol)
                body = node.child_by_field_name("body")
                if body is not None:
                    new_scope = [*node_scope, symbol]
                    stack.extend((c, new_scope) for c in reversed(body.children))
                continue

            if node.type == "short_var_declaration":
                binding = self._func_literal_binding(node, node_scope, ctx)
                if binding is not None:
                    symbol, body = binding
                    ctx.symbols.append(symbol)
                    if body is not None:
                        new_scope = [*node_scope, symbol]
                        stack.extend((c, new_scope) for c in reversed(body.children))
                else:
                    stack.extend((c, node_scope) for c in reversed(node.children))
                continue

            if node.type == "call_expression":
                self._record_call(node, node_scope, ctx)
                stack.extend((c, node_scope) for c in reversed(node.children))
                continue

            if node.type == "import_declaration":
                self._extract_imports(node, ctx)
                continue

            stack.extend((c, node_scope) for c in reversed(node.children))

    def _func_literal_binding(
        self, node: Node, scope_stack: list[Symbol], ctx: _WalkContext
    ) -> tuple[Symbol, Node | None] | None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:
            return None
        name_node = next((c for c in left.children if c.type == "identifier"), None)
        func_literal = next((c for c in right.children if c.type == "func_literal"), None)
        if name_node is None or func_literal is None:
            return None

        name = self._text(name_node, ctx)
        parent = scope_stack[-1] if scope_stack else None
        location = self._location(node, ctx.file_path)
        qualified_name = f"{parent.qualified_name}.{name}" if parent else name
        symbol = Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=SymbolKind.FUNCTION,
            file_path=ctx.file_path,
            location=location,
            parent_id=parent.id if parent else None,
        )
        return symbol, func_literal.child_by_field_name("body")

    def _build_function_symbol(
        self, node: Node, scope_stack: list[Symbol], ctx: _WalkContext
    ) -> Symbol:
        name_node = node.child_by_field_name("name")
        name = self._text(name_node, ctx) if name_node else "<anonymous>"
        parent = scope_stack[-1] if scope_stack else None
        qualified_name = f"{parent.qualified_name}.{name}" if parent else name
        location = self._location(node, ctx.file_path)
        return Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=SymbolKind.FUNCTION,
            file_path=ctx.file_path,
            location=location,
            parent_id=parent.id if parent else None,
        )

    def _build_method_symbol(self, node: Node, ctx: _WalkContext) -> Symbol:
        name_node = node.child_by_field_name("name")
        name = self._text(name_node, ctx) if name_node else "<anonymous>"
        receiver_type_name = self._receiver_type_name(node, ctx)
        parent = ctx.types_by_name.get(receiver_type_name) if receiver_type_name else None
        qualified_name = f"{receiver_type_name}.{name}" if receiver_type_name else name
        location = self._location(node, ctx.file_path)
        return Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=SymbolKind.METHOD,
            file_path=ctx.file_path,
            location=location,
            parent_id=parent.id if parent else None,
        )

    def _receiver_type_name(self, method_node: Node, ctx: _WalkContext) -> str | None:
        receiver = method_node.child_by_field_name("receiver")
        if receiver is None:
            return None
        param_decl = next(
            (c for c in receiver.children if c.type == "parameter_declaration"), None
        )
        if param_decl is None:
            return None
        type_node = param_decl.child_by_field_name("type")
        if type_node is None:
            return None
        return self._unwrap_type_name(type_node, ctx)

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
        if func_node.type == "selector_expression":
            field_node = func_node.child_by_field_name("field")
            return self._text(field_node, ctx) if field_node else None
        return None

    @staticmethod
    def _nearest_callable(scope_stack: list[Symbol]) -> Symbol | None:
        for symbol in reversed(scope_stack):
            if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                return symbol
        return None

    # -- imports --------------------------------------------------------------

    def _extract_imports(self, node: Node, ctx: _WalkContext) -> None:
        for import_spec in self._find_all(node, "import_spec"):
            path_node = import_spec.child_by_field_name("path")
            if path_node is None:
                continue
            raw_module = self._string_literal_text(path_node, ctx)
            name_node = import_spec.child_by_field_name("name")
            imported_names = [self._text(name_node, ctx)] if name_node is not None else []
            resolved = self._resolve_import_path(raw_module, ctx.workspace_files)
            ctx.imports.append(
                ImportReference(
                    source_file=ctx.file_path,
                    raw_module=raw_module,
                    imported_names=imported_names,
                    resolved_file_path=resolved,
                    location=self._location(import_spec, ctx.file_path),
                )
            )

    @staticmethod
    def _string_literal_text(string_node: Node, ctx: _WalkContext) -> str:
        content = next(
            (c for c in string_node.children if c.type == "interpreted_string_literal_content"),
            None,
        )
        return GoLanguageAnalyzer._text(content, ctx) if content else ""

    @staticmethod
    def _resolve_import_path(raw_path: str, workspace_files: frozenset[str]) -> str | None:
        """See the module docstring's own "Import resolution" section for
        why this tries multiple suffixes rather than the raw path
        directly: a real Go import is module-qualified
        (`github.com/org/repo/pkg/auth`), and the module's own prefix
        never appears in `workspace_files` (workspace-relative,
        `pkg/auth`). Trying the full path first, then progressively
        shorter suffixes, and returning the first match keeps the most
        specific interpretation whenever more than one suffix happens to
        match."""
        segments = raw_path.split("/")
        for start in range(len(segments)):
            prefix = "/".join(segments[start:]) + "/"
            matches = sorted(f for f in workspace_files if f.startswith(prefix) and f.endswith(".go"))
            if matches:
                return matches[0]
        return None

    # -- tree helpers ---------------------------------------------------

    @staticmethod
    def _find_all(root: Node, node_type: str) -> list[Node]:
        # Iterative pre-order search — see _visit_children's comment for why
        # this can't be plain recursion. Matched nodes are not searched
        # further, mirroring the original recursive behavior.
        found: list[Node] = []
        stack: list[Node] = list(reversed(root.children))
        while stack:
            node = stack.pop()
            if node.type == node_type:
                found.append(node)
            else:
                stack.extend(reversed(node.children))
        return found

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
