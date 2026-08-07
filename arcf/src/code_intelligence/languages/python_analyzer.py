"""PythonLanguageAnalyzer — the first LanguageAnalyzer implementation,
via tree-sitter-python.

Grammar node types/field names used below (class_definition.name/
superclasses/body, function_definition.name/body, call.function/
arguments, attribute.object/attribute, import_statement.name,
import_from_statement.module_name/name, relative_import's
import_prefix + optional dotted_name) were verified empirically against
the installed tree-sitter-python grammar, not assumed from memory.

Everything this module knows about Python syntax stays in this file —
it emits only the shared IR (Symbol, CallReference, ImportReference)
defined in domain/code_intelligence.py. Name resolution (matching a
call's callee_name or a class's base_names against actual Symbols) is
deliberately NOT done here: that's ReferenceResolver's job, working
purely off IR, so it applies identically to every future language.

Two things ARE resolved here, not upstream, because they are
inescapably language-specific:
- classifying a definition as FUNCTION vs. METHOD (Python: "is the
  immediately enclosing scope a class body?")
- import resolution (Python's dotted-module/relative-import rules are
  nothing like TypeScript's or Go's) — resolved_file_path is filled in
  here using workspace_files, so ImportGraph never needs to know how
  any language's imports work.

Best-effort, not a type checker: callee_name is the call's simple name
only (`self.foo()` and `foo()` both record "foo"); base_names are raw
text. Cross-file resolution of *those* strings against real Symbols is
ReferenceResolver's job and is necessarily approximate without full
type inference — documented, not hidden.
"""

from dataclasses import dataclass, field

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)

_PY_LANGUAGE = Language(tspython.language())


@dataclass
class _WalkContext:
    file_path: str
    workspace_files: frozenset[str]
    source_bytes: bytes
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[CallReference] = field(default_factory=list)
    imports: list[ImportReference] = field(default_factory=list)


class PythonLanguageAnalyzer:
    @property
    def language(self) -> str:
        return "python"

    def handles(self, file_path: str) -> bool:
        return file_path.endswith((".py", ".pyi"))

    def analyze_file(
        self, file_path: str, source_text: str, workspace_files: frozenset[str]
    ) -> FileAnalysis:
        source_bytes = source_text.encode("utf-8")
        # A fresh Parser per call — tree-sitter Parser objects aren't safe
        # to share across concurrent threads; _PY_LANGUAGE itself is
        # immutable and fine to reuse.
        tree = Parser(_PY_LANGUAGE).parse(source_bytes)

        ctx = _WalkContext(
            file_path=file_path, workspace_files=workspace_files, source_bytes=source_bytes
        )
        self._walk(tree.root_node, [], [], ctx)

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

    def _walk(
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
        stack: list[tuple[Node, list[Symbol], list[str]]] = [
            (child, scope_stack, qualname_parts) for child in reversed(root.children)
        ]
        while stack:
            node, node_scope, node_qualname = stack.pop()
            if node.type == "class_definition":
                symbol = self._build_class_symbol(node, node_scope, node_qualname, ctx)
                ctx.symbols.append(symbol)
                new_scope = [*node_scope, symbol]
                new_qualname = [*node_qualname, symbol.name]
                stack.extend((c, new_scope, new_qualname) for c in reversed(node.children))
            elif node.type == "function_definition":
                symbol = self._build_function_symbol(node, node_scope, node_qualname, ctx)
                ctx.symbols.append(symbol)
                new_scope = [*node_scope, symbol]
                new_qualname = [*node_qualname, symbol.name]
                stack.extend((c, new_scope, new_qualname) for c in reversed(node.children))
            elif node.type == "call":
                self._record_call(node, node_scope, ctx)
                stack.extend((c, node_scope, node_qualname) for c in reversed(node.children))
            elif node.type == "import_statement":
                self._extract_plain_imports(node, ctx)
            elif node.type == "import_from_statement":
                self._extract_from_imports(node, ctx)
            else:
                stack.extend((c, node_scope, node_qualname) for c in reversed(node.children))

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

    def _build_function_symbol(
        self, node: Node, scope_stack: list[Symbol], qualname_parts: list[str], ctx: _WalkContext
    ) -> Symbol:
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

    def _extract_base_names(self, class_node: Node, ctx: _WalkContext) -> list[str]:
        superclasses = class_node.child_by_field_name("superclasses")
        if superclasses is None:
            return []
        return [
            self._text(child, ctx)
            for child in superclasses.children
            if child.type in ("identifier", "attribute")
        ]

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
        if func_node.type == "attribute":
            attr_node = func_node.child_by_field_name("attribute")
            return self._text(attr_node, ctx) if attr_node else None
        return None

    @staticmethod
    def _nearest_callable(scope_stack: list[Symbol]) -> Symbol | None:
        for symbol in reversed(scope_stack):
            if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                return symbol
        return None

    # -- imports ------------------------------------------------------------

    def _extract_plain_imports(self, node: Node, ctx: _WalkContext) -> None:
        location = self._location(node, ctx.file_path)
        for name_node in node.children_by_field_name("name"):
            module_text = self._dotted_import_text(name_node, ctx)
            module_parts = module_text.split(".") if module_text else []
            resolved = self._resolve_module_path(module_parts, ctx.workspace_files)
            ctx.imports.append(
                ImportReference(
                    source_file=ctx.file_path,
                    raw_module=module_text,
                    imported_names=[],
                    resolved_file_path=resolved,
                    location=location,
                )
            )

    def _extract_from_imports(self, node: Node, ctx: _WalkContext) -> None:
        module_name_node = node.child_by_field_name("module_name")
        base_dir_parts, module_parts, raw_module = self._resolve_from_module(
            module_name_node, ctx
        )

        names = [self._dotted_import_text(n, ctx) for n in node.children_by_field_name("name")]
        if not names and any(child.type == "wildcard_import" for child in node.children):
            names = ["*"]

        location = self._location(node, ctx.file_path)
        whole_module_parts = [*base_dir_parts, *module_parts]
        whole_resolved = self._resolve_module_path(whole_module_parts, ctx.workspace_files)

        if whole_resolved is not None or not names:
            ctx.imports.append(
                ImportReference(
                    source_file=ctx.file_path,
                    raw_module=raw_module,
                    imported_names=names,
                    resolved_file_path=whole_resolved,
                    location=location,
                )
            )
            return

        # Whole module didn't resolve to a file — it may be a package
        # whose __init__.py doesn't exist in-scan, or each name may itself
        # be a submodule (`from . import foo, bar`). Try per-name.
        for name in names:
            sub_resolved = self._resolve_module_path(
                [*whole_module_parts, name], ctx.workspace_files
            )
            ctx.imports.append(
                ImportReference(
                    source_file=ctx.file_path,
                    raw_module=raw_module,
                    imported_names=[name],
                    resolved_file_path=sub_resolved,
                    location=location,
                )
            )

    def _resolve_from_module(
        self, module_name_node: Node | None, ctx: _WalkContext
    ) -> tuple[list[str], list[str], str]:
        if module_name_node is None:
            return [], [], ""

        if module_name_node.type == "dotted_name":
            module_text = self._text(module_name_node, ctx)
            return [], module_text.split("."), module_text

        if module_name_node.type == "relative_import":
            raw_text = self._text(module_name_node, ctx)
            level = 0
            dotted_part = ""
            for child in module_name_node.children:
                if child.type == "import_prefix":
                    level = sum(1 for dot in child.children if dot.type == ".")
                elif child.type == "dotted_name":
                    dotted_part = self._text(child, ctx)

            current_dir_parts = (
                ctx.file_path.rsplit("/", 1)[0].split("/") if "/" in ctx.file_path else []
            )
            levels_up = max(level - 1, 0)
            base_dir_parts = (
                current_dir_parts[: max(len(current_dir_parts) - levels_up, 0)]
                if levels_up > 0
                else current_dir_parts
            )
            module_parts = dotted_part.split(".") if dotted_part else []
            return base_dir_parts, module_parts, raw_text

        return [], [], ""

    def _dotted_import_text(self, node: Node, ctx: _WalkContext) -> str:
        if node.type == "aliased_import":
            name_node = node.child_by_field_name("name")
            return self._text(name_node, ctx) if name_node else ""
        return self._text(node, ctx)

    @staticmethod
    def _resolve_module_path(path_parts: list[str], workspace_files: frozenset[str]) -> str | None:
        parts = [part for part in path_parts if part]
        if not parts:
            return None
        candidate = "/".join(parts)
        for suffix in (".py", "/__init__.py"):
            candidate_path = candidate + suffix
            if candidate_path in workspace_files:
                return candidate_path
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
