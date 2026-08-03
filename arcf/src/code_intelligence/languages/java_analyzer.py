"""JavaLanguageAnalyzer — fourth LanguageAnalyzer implementation (Stage
6 of the v2.3 migration plan, see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md
Sec. 2.3/6/7), via tree-sitter-java.

Grammar node types/field names used below (class_declaration's [name/
superclass/interfaces/body], interface_declaration's [name/body],
super_interfaces/extends_interfaces wrapping a type_list of
type_identifier/generic_type, method_declaration's [name/parameters/
body], method_invocation's [name/arguments] — Java's grammar already
normalizes `foo()`/`this.foo()`/`obj.foo()` to the same `name` field,
unlike Python's/Go's/TypeScript's split between a bare identifier and
an attribute/selector/member expression — and import_declaration's
scoped_identifier + optional `static`/trailing asterisk) were verified
empirically against the installed tree-sitter-java grammar, not
assumed from memory.

Single recursive descent, same shape as PythonLanguageAnalyzer's,
because Java (unlike Go) DOES lexically nest methods inside class/
interface bodies — no two-pass receiver resolution needed here.

Import resolution: a dotted path (e.g. "com.example.auth.Authenticator")
maps to "com/example/auth/Authenticator.java" by replacing dots with
slashes. Two things stay honestly best-effort, same spirit as
GoLanguageAnalyzer's package-vs-file gap:
- A static import's raw scoped_identifier includes the imported
  member name as its last segment (e.g. "...Helpers.helper") — resolved
  by first trying the full path as a class, then the path minus its
  last segment.
- A wildcard import ("com.example.util.*") names a whole package, not
  one file — resolved to the alphabetically-first .java file in that
  directory, if any, as a representative file.
"""

from dataclasses import dataclass, field

import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)

_JAVA_LANGUAGE = Language(tsjava.language())


@dataclass
class _WalkContext:
    file_path: str
    workspace_files: frozenset[str]
    source_bytes: bytes
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[CallReference] = field(default_factory=list)
    imports: list[ImportReference] = field(default_factory=list)


class JavaLanguageAnalyzer:
    @property
    def language(self) -> str:
        return "java"

    def handles(self, file_path: str) -> bool:
        return file_path.endswith(".java")

    def analyze_file(
        self, file_path: str, source_text: str, workspace_files: frozenset[str]
    ) -> FileAnalysis:
        source_bytes = source_text.encode("utf-8")
        # A fresh Parser per call — tree-sitter Parser objects aren't safe
        # to share across concurrent threads; _JAVA_LANGUAGE itself is
        # immutable and fine to reuse.
        tree = Parser(_JAVA_LANGUAGE).parse(source_bytes)

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
        node: Node,
        scope_stack: list[Symbol],
        qualname_parts: list[str],
        ctx: _WalkContext,
    ) -> None:
        if node.type == "class_declaration":
            symbol = self._build_class_symbol(node, scope_stack, qualname_parts, ctx)
            ctx.symbols.append(symbol)
            body = node.child_by_field_name("body")
            if body is not None:
                new_scope, new_qual = [*scope_stack, symbol], [*qualname_parts, symbol.name]
                self._visit_children(body, new_scope, new_qual, ctx)
            return

        if node.type == "interface_declaration":
            symbol = self._build_interface_symbol(node, scope_stack, qualname_parts, ctx)
            ctx.symbols.append(symbol)
            body = node.child_by_field_name("body")
            if body is not None:
                new_scope, new_qual = [*scope_stack, symbol], [*qualname_parts, symbol.name]
                self._visit_children(body, new_scope, new_qual, ctx)
            return

        if node.type == "method_declaration":
            symbol = self._build_method_symbol(node, scope_stack, qualname_parts, ctx)
            ctx.symbols.append(symbol)
            body = node.child_by_field_name("body")
            if body is not None:
                new_scope, new_qual = [*scope_stack, symbol], [*qualname_parts, symbol.name]
                self._visit_children(body, new_scope, new_qual, ctx)
            return

        if node.type == "method_invocation":
            self._record_call(node, scope_stack, ctx)
            self._visit_children(node, scope_stack, qualname_parts, ctx)
            return

        if node.type == "import_declaration":
            self._extract_import(node, ctx)
            return

        self._visit_children(node, scope_stack, qualname_parts, ctx)

    def _visit_children(
        self,
        node: Node,
        scope_stack: list[Symbol],
        qualname_parts: list[str],
        ctx: _WalkContext,
    ) -> None:
        for child in node.children:
            self._visit(child, scope_stack, qualname_parts, ctx)

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
        base_names = []
        extends = next((c for c in node.children if c.type == "extends_interfaces"), None)
        if extends is not None:
            base_names = self._type_names_from(extends, ctx)
        return Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=SymbolKind.INTERFACE,
            file_path=ctx.file_path,
            location=location,
            base_names=base_names,
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

    def _extract_class_base_names(self, class_node: Node, ctx: _WalkContext) -> list[str]:
        names: list[str] = []
        superclass = class_node.child_by_field_name("superclass")
        if superclass is not None:
            names.extend(self._type_names_from(superclass, ctx))
        interfaces = class_node.child_by_field_name("interfaces")
        if interfaces is not None:
            names.extend(self._type_names_from(interfaces, ctx))
        return names

    def _type_names_from(self, node: Node, ctx: _WalkContext) -> list[str]:
        """node is a `superclass`/`super_interfaces`/`extends_interfaces`
        clause; the actual type_identifier/generic_type entries live
        either directly in it or, for a comma-separated list, inside a
        nested type_list."""
        type_list = next((c for c in node.children if c.type == "type_list"), None)
        container = type_list if type_list is not None else node
        names = []
        for child in container.children:
            if child.type == "type_identifier":
                names.append(self._text(child, ctx))
            elif child.type == "generic_type":
                base = next((c for c in child.children if c.type == "type_identifier"), None)
                if base is not None:
                    names.append(self._text(base, ctx))
        return names

    # -- calls --------------------------------------------------------------

    def _record_call(self, call_node: Node, scope_stack: list[Symbol], ctx: _WalkContext) -> None:
        name_node = call_node.child_by_field_name("name")
        if name_node is None:
            return
        caller = self._nearest_callable(scope_stack)
        ctx.calls.append(
            CallReference(
                caller_id=caller.id if caller else None,
                callee_name=self._text(name_node, ctx),
                file_path=ctx.file_path,
                location=self._location(call_node, ctx.file_path),
            )
        )

    @staticmethod
    def _nearest_callable(scope_stack: list[Symbol]) -> Symbol | None:
        for symbol in reversed(scope_stack):
            if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                return symbol
        return None

    # -- imports --------------------------------------------------------------

    def _extract_import(self, node: Node, ctx: _WalkContext) -> None:
        is_static = any(c.type == "static" for c in node.children)
        is_wildcard = any(c.type == "asterisk" for c in node.children)
        scoped = next(
            (c for c in node.children if c.type in ("scoped_identifier", "identifier")), None
        )
        if scoped is None:
            return
        dotted = self._text(scoped, ctx)
        resolved = self._resolve_import(dotted, is_static, is_wildcard, ctx.workspace_files)
        imported_names = ["*"] if is_wildcard else [dotted.rsplit(".", 1)[-1]]
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
    def _resolve_class_path(dotted: str, workspace_files: frozenset[str]) -> str | None:
        candidate = dotted.replace(".", "/") + ".java"
        return candidate if candidate in workspace_files else None

    @classmethod
    def _resolve_import(
        cls, dotted: str, is_static: bool, is_wildcard: bool, workspace_files: frozenset[str]
    ) -> str | None:
        if is_wildcard:
            prefix = dotted.replace(".", "/") + "/"
            matches = sorted(
                f for f in workspace_files if f.startswith(prefix) and f.endswith(".java")
            )
            return matches[0] if matches else None

        direct = cls._resolve_class_path(dotted, workspace_files)
        if direct is not None:
            return direct
        if is_static and "." in dotted:
            return cls._resolve_class_path(dotted.rsplit(".", 1)[0], workspace_files)
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
