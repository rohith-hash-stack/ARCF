"""CppLanguageAnalyzer — LanguageAnalyzer implementation for C and C++, via
tree-sitter-c and tree-sitter-cpp.

Grammar node types/field names below (preproc_include's path
[system_lib_string vs string_literal -> string_content], class_specifier/
struct_specifier's [name/body/base_class_clause], field_declaration's
[type/declarator], function_definition's [type/declarator/body],
function_declarator's [declarator/parameters], call_expression's
[function/arguments], field_expression's [argument/operator/field],
qualified_identifier's [scope/name], destructor_name, namespace_definition's
[name/body]) were verified empirically against the installed tree-sitter-c
and tree-sitter-cpp grammars, not assumed from memory — both grammars agree
on every node/field name used here, so one traversal serves both languages;
`.c` files are parsed with tree-sitter-c (which simply never produces the
C++-only node types below), everything else with tree-sitter-cpp.

Structurally closer to Go's two-pass design than Python's/TypeScript's
single recursive descent, for the same reason: an out-of-class method
definition (`ReturnType ClassName::method(...) {...}`) names its owning
type BY TEXT, not by lexical nesting, and may appear before or after the
class's own declaration in the same file. So:

1. `_collect_type_declarations` walks the whole tree first (namespace-aware,
   but not descending into a class/struct's own body — methods are pass 2's
   job) building CLASS symbols (both `class` and `struct` map to
   SymbolKind.CLASS, mirroring Go's struct->CLASS choice) and a
   name -> Symbol map (`types_by_name`, keyed by simple name only — a
   deliberate, documented simplification shared with Go's package-level
   name map: two classes of the same name in different namespaces collide,
   last one wins). A `struct_specifier`/`class_specifier` with no `body`
   field is a bare reference or forward declaration (e.g. `struct Point p;`
   or `struct Point;`), not a definition, and is skipped.

2. `_visit_children` walks the whole tree again, this time descending into
   class bodies, resolving:
   - in-class methods (prototype-only `field_declaration`, or inline
     `function_definition`) via the current scope's CLASS entry,
   - out-of-class method definitions via `qualified_identifier`'s text
     split on "::" and a `types_by_name` lookup on the second-to-last
     segment,
   - free functions, namespace-qualified by the enclosing `namespace_path`
     (joined with "::", matching C++'s own qualification syntax) — but
     never given a `parent_id`, since a namespace is not a CLASS or
     FUNCTION Symbol; `parent_id` models lexical nesting inside another
     symbol, not namespace membership,
   - calls (identifier / `obj.field()` / `obj->field()` / `Ns::func()`),
   - `#include` directives.

Both passes are iterative explicit-stack pre-order traversals (never plain
recursion) for the same reason as every other analyzer here: deeply nested
real-world C++ (heavily templated headers, generated code) can overflow
Python's call stack.

Function pointers, operator overloads, and lambdas are handled only to the
extent the shared traversal naturally covers them (`operator_name` and
`destructor_name` declarators are treated as ordinary method/function
names; a `pointer_declarator`/`reference_declarator` wrapping a
`function_declarator`, e.g. `int* get_ptr();`, is unwrapped down to the
`function_declarator`). Lambdas are not extracted as their own Symbol
(C++ has no named-nested-function construct the way Go's assigned func
literals do) — a call inside a lambda body is still attributed to the
nearest enclosing named FUNCTION/METHOD, since the traversal just keeps
descending through the lambda node via the generic fallback branch without
pushing a new scope entry.

Include resolution: a quoted include (`#include "local/foo.h"`) is
resolved like TypeScript's relative imports — first directly against the
current file's directory, then (since `#include` search paths routinely
add project include roots ARCF has no visibility into) by suffix match
against `workspace_files`, picking the alphabetically-first match if more
than one file shares that suffix. An angle-bracket include
(`#include <vector>`) is always a system/third-party header and is left
unresolved, mirroring Go's stdlib-import treatment.
"""

from dataclasses import dataclass, field

import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
from tree_sitter import Language, Node, Parser

from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)

_C_LANGUAGE = Language(tsc.language())
_CPP_LANGUAGE = Language(tscpp.language())

_C_EXTENSIONS = (".c",)
_CPP_EXTENSIONS = (".cpp", ".cc", ".cxx", ".c++", ".hpp", ".hh", ".hxx", ".h++", ".h", ".ipp", ".inl")

_TYPE_DEFINITION_NODE_TYPES = ("class_specifier", "struct_specifier")
_NAME_DECLARATOR_TYPES = ("identifier", "field_identifier", "destructor_name", "operator_name")


@dataclass
class _WalkContext:
    file_path: str
    workspace_files: frozenset[str]
    source_bytes: bytes
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[CallReference] = field(default_factory=list)
    imports: list[ImportReference] = field(default_factory=list)
    types_by_name: dict[str, Symbol] = field(default_factory=dict)


class CppLanguageAnalyzer:
    @property
    def language(self) -> str:
        return "cpp"

    def handles(self, file_path: str) -> bool:
        return file_path.endswith(_C_EXTENSIONS + _CPP_EXTENSIONS)

    def analyze_file(
        self, file_path: str, source_text: str, workspace_files: frozenset[str]
    ) -> FileAnalysis:
        source_bytes = source_text.encode("utf-8")
        grammar = _C_LANGUAGE if file_path.endswith(_C_EXTENSIONS) else _CPP_LANGUAGE
        # A fresh Parser per call — tree-sitter Parser objects aren't safe
        # to share across concurrent threads; the Language objects
        # themselves are immutable and fine to reuse.
        tree = Parser(grammar).parse(source_bytes)

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

    # -- pass 1: class/struct declarations ----------------------------------

    def _collect_type_declarations(
        self, root: Node, ctx: _WalkContext, namespace_path: tuple[str, ...]
    ) -> None:
        stack: list[tuple[Node, tuple[str, ...]]] = [
            (child, namespace_path) for child in reversed(root.children)
        ]
        while stack:
            node, ns_path = stack.pop()

            if node.type == "namespace_definition":
                name_node = node.child_by_field_name("name")
                body = node.child_by_field_name("body")
                if name_node is not None and body is not None:
                    new_ns = (*ns_path, self._text(name_node, ctx))
                    stack.extend((c, new_ns) for c in reversed(body.children))
                continue

            if node.type in _TYPE_DEFINITION_NODE_TYPES:
                self._build_type_symbol(node, ctx, ns_path)
                continue  # methods inside are pass 2's job

            stack.extend((c, ns_path) for c in reversed(node.children))

    def _build_type_symbol(
        self, type_node: Node, ctx: _WalkContext, namespace_path: tuple[str, ...]
    ) -> None:
        name_node = type_node.child_by_field_name("name")
        body = type_node.child_by_field_name("body")
        if name_node is None or body is None:
            return  # forward declaration or bare reference, not a definition
        name = self._text(name_node, ctx)
        qualified_name = "::".join((*namespace_path, name)) if namespace_path else name
        location = self._location(type_node, ctx.file_path)
        symbol = Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=SymbolKind.CLASS,
            file_path=ctx.file_path,
            location=location,
            base_names=self._extract_base_names(type_node, ctx),
        )
        ctx.symbols.append(symbol)
        ctx.types_by_name[name] = symbol

    def _extract_base_names(self, type_node: Node, ctx: _WalkContext) -> list[str]:
        base_clause = next((c for c in type_node.children if c.type == "base_class_clause"), None)
        if base_clause is None:
            return []
        return [
            self._text(child, ctx)
            for child in base_clause.children
            if child.type in ("type_identifier", "qualified_identifier")
        ]

    # -- pass 2: functions/methods/calls/includes ---------------------------

    def _visit_children(
        self,
        root: Node,
        namespace_path: tuple[str, ...],
        scope_stack: list[Symbol],
        ctx: _WalkContext,
    ) -> None:
        # Iterative, explicit-stack pre-order traversal — see the module
        # docstring for why plain recursion isn't safe here.
        Frame = tuple[Node, tuple[str, ...], list[Symbol]]
        stack: list[Frame] = [(child, namespace_path, scope_stack) for child in reversed(root.children)]
        while stack:
            node, ns_path, scope = stack.pop()

            if node.type == "namespace_definition":
                name_node = node.child_by_field_name("name")
                body = node.child_by_field_name("body")
                if name_node is not None and body is not None:
                    new_ns = (*ns_path, self._text(name_node, ctx))
                    stack.extend((c, new_ns, scope) for c in reversed(body.children))
                continue

            if node.type in _TYPE_DEFINITION_NODE_TYPES:
                name_node = node.child_by_field_name("name")
                body = node.child_by_field_name("body")
                if name_node is None or body is None:
                    continue
                class_symbol = ctx.types_by_name.get(self._text(name_node, ctx))
                new_scope = [*scope, class_symbol] if class_symbol is not None else scope
                stack.extend((c, ns_path, new_scope) for c in reversed(body.children))
                continue

            if node.type == "field_declaration":
                symbol = self._build_member_method_symbol(node, scope, ctx)
                if symbol is not None:
                    ctx.symbols.append(symbol)
                continue  # a member declaration (data or method prototype) has no body here

            if node.type == "function_definition":
                symbol = self._build_function_or_method_symbol(node, ns_path, scope, ctx)
                if symbol is None:
                    stack.extend((c, ns_path, scope) for c in reversed(node.children))
                    continue
                ctx.symbols.append(symbol)
                body = node.child_by_field_name("body")
                if body is not None:
                    new_scope = [*scope, symbol]
                    stack.extend((c, ns_path, new_scope) for c in reversed(body.children))
                continue

            if node.type == "call_expression":
                self._record_call(node, scope, ctx)
                stack.extend((c, ns_path, scope) for c in reversed(node.children))
                continue

            if node.type == "preproc_include":
                self._extract_include(node, ctx)
                continue

            stack.extend((c, ns_path, scope) for c in reversed(node.children))

    def _build_member_method_symbol(
        self, node: Node, scope: list[Symbol], ctx: _WalkContext
    ) -> Symbol | None:
        declarator = node.child_by_field_name("declarator")
        if declarator is None or declarator.type != "function_declarator":
            return None  # a data member, not a method prototype
        name = self._declarator_simple_name(declarator, ctx)
        if name is None:
            return None
        parent = scope[-1] if scope and scope[-1].kind == SymbolKind.CLASS else None
        qualified_name = f"{parent.qualified_name}::{name}" if parent else name
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

    def _build_function_or_method_symbol(
        self, node: Node, namespace_path: tuple[str, ...], scope: list[Symbol], ctx: _WalkContext
    ) -> Symbol | None:
        function_declarator = node.child_by_field_name("declarator")
        while function_declarator is not None and function_declarator.type != "function_declarator":
            function_declarator = function_declarator.child_by_field_name("declarator")
        if function_declarator is None:
            return None
        inner = function_declarator.child_by_field_name("declarator")
        if inner is None:
            return None
        location = self._location(node, ctx.file_path)

        if inner.type == "qualified_identifier":
            # Out-of-class method definition: `Owner::method(...) {...}`,
            # possibly `Outer::Inner::method` — split on "::" rather than
            # walking the (possibly recursively-nested) qualified_identifier
            # field structure, since the text form is unambiguous either way.
            full_text = self._text(inner, ctx)
            *scope_parts, name = full_text.split("::")
            owner_name = scope_parts[-1] if scope_parts else None
            parent = ctx.types_by_name.get(owner_name) if owner_name else None
            return Symbol(
                id=self._symbol_id(ctx.file_path, full_text, location),
                name=name,
                qualified_name=full_text,
                kind=SymbolKind.METHOD,
                file_path=ctx.file_path,
                location=location,
                parent_id=parent.id if parent else None,
            )

        if inner.type not in _NAME_DECLARATOR_TYPES:
            return None
        name = self._text(inner, ctx)

        class_parent = scope[-1] if scope and scope[-1].kind == SymbolKind.CLASS else None
        if class_parent is not None:
            qualified_name = f"{class_parent.qualified_name}::{name}"
            return Symbol(
                id=self._symbol_id(ctx.file_path, qualified_name, location),
                name=name,
                qualified_name=qualified_name,
                kind=SymbolKind.METHOD,
                file_path=ctx.file_path,
                location=location,
                parent_id=class_parent.id,
            )

        qualified_name = "::".join((*namespace_path, name)) if namespace_path else name
        return Symbol(
            id=self._symbol_id(ctx.file_path, qualified_name, location),
            name=name,
            qualified_name=qualified_name,
            kind=SymbolKind.FUNCTION,
            file_path=ctx.file_path,
            location=location,
            parent_id=None,
        )

    @staticmethod
    def _declarator_simple_name(function_declarator: Node, ctx: _WalkContext) -> str | None:
        inner = function_declarator.child_by_field_name("declarator")
        if inner is None:
            return None
        if inner.type == "qualified_identifier":
            name_node = inner.child_by_field_name("name")
            return CppLanguageAnalyzer._text(name_node, ctx) if name_node is not None else None
        if inner.type in _NAME_DECLARATOR_TYPES:
            return CppLanguageAnalyzer._text(inner, ctx)
        return None

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
        if func_node.type == "qualified_identifier":
            name_node = func_node.child_by_field_name("name")
            return self._text(name_node, ctx) if name_node else self._text(func_node, ctx)
        return None

    @staticmethod
    def _nearest_callable(scope: list[Symbol]) -> Symbol | None:
        for symbol in reversed(scope):
            if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                return symbol
        return None

    # -- includes ---------------------------------------------------------

    def _extract_include(self, node: Node, ctx: _WalkContext) -> None:
        path_node = node.child_by_field_name("path")
        if path_node is None:
            return

        if path_node.type == "system_lib_string":
            raw_module = self._text(path_node, ctx)
            resolved = None
        elif path_node.type == "string_literal":
            content = next((c for c in path_node.children if c.type == "string_content"), None)
            raw_module = self._text(content, ctx) if content is not None else ""
            resolved = self._resolve_include_path(raw_module, ctx.file_path, ctx.workspace_files)
        else:
            return

        ctx.imports.append(
            ImportReference(
                source_file=ctx.file_path,
                raw_module=raw_module,
                imported_names=[],
                resolved_file_path=resolved,
                location=self._location(node, ctx.file_path),
            )
        )

    @staticmethod
    def _resolve_include_path(
        raw_path: str, current_file: str, workspace_files: frozenset[str]
    ) -> str | None:
        if raw_path in workspace_files:
            return raw_path

        current_dir_parts = (
            current_file.rsplit("/", 1)[0].split("/") if "/" in current_file else []
        )
        parts = list(current_dir_parts)
        for segment in raw_path.split("/"):
            if segment in ("", "."):
                continue
            if segment == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(segment)
        candidate = "/".join(parts)
        if candidate in workspace_files:
            return candidate

        suffix = "/" + raw_path
        matches = sorted(f for f in workspace_files if f.endswith(suffix))
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
