"""ToyLanguageAnalyzer — a deliberately trivial, non-tree-sitter
LanguageAnalyzer for a made-up ".toy" language.

Exists ONLY to prove code_intelligence/'s orchestration layer
(SymbolIndex, ImportGraph, DependencyGraph, InheritanceGraph, CallGraph,
CandidateFileSelector, CodeIntelligenceEngine) needs zero changes to
support a second language — see test_language_agnostic.py. It emits the
same IR as PythonLanguageAnalyzer via a one-line-per-fact toy grammar,
e.g.:

    class BasePage
    class LoginPage extends BasePage
    func authenticate
    func check calls authenticate
    import other.toy
"""

import re

from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)

_CLASS_RE = re.compile(r"class (\w+)(?: extends (\w+))?$")
_FUNC_RE = re.compile(r"func (\w+)(?: calls ([\w, ]+))?$")
_IMPORT_RE = re.compile(r"import (\S+)$")


class ToyLanguageAnalyzer:
    @property
    def language(self) -> str:
        return "toy"

    def handles(self, file_path: str) -> bool:
        return file_path.endswith(".toy")

    def analyze_file(
        self, file_path: str, source_text: str, workspace_files: frozenset[str]
    ) -> FileAnalysis:
        symbols: list[Symbol] = []
        calls: list[CallReference] = []
        imports: list[ImportReference] = []

        for line_number, raw_line in enumerate(source_text.splitlines(), start=1):
            line = raw_line.strip()
            location = SourceLocation(
                file_path=file_path, start_line=line_number, end_line=line_number
            )

            if class_match := _CLASS_RE.match(line):
                name, base = class_match.groups()
                symbols.append(
                    Symbol(
                        id=f"{file_path}::{name}",
                        name=name,
                        qualified_name=name,
                        kind=SymbolKind.CLASS,
                        file_path=file_path,
                        location=location,
                        base_names=[base] if base else [],
                    )
                )
            elif func_match := _FUNC_RE.match(line):
                name, callees_text = func_match.groups()
                symbol_id = f"{file_path}::{name}"
                symbols.append(
                    Symbol(
                        id=symbol_id,
                        name=name,
                        qualified_name=name,
                        kind=SymbolKind.FUNCTION,
                        file_path=file_path,
                        location=location,
                    )
                )
                for callee in (callees_text or "").split(","):
                    callee = callee.strip()
                    if callee:
                        calls.append(
                            CallReference(
                                caller_id=symbol_id,
                                callee_name=callee,
                                file_path=file_path,
                                location=location,
                            )
                        )
            elif import_match := _IMPORT_RE.match(line):
                (target,) = import_match.groups()
                imports.append(
                    ImportReference(
                        source_file=file_path,
                        raw_module=target,
                        resolved_file_path=target if target in workspace_files else None,
                        location=location,
                    )
                )

        return FileAnalysis(
            file_path=file_path,
            language=self.language,
            symbols=symbols,
            calls=calls,
            imports=imports,
        )
