"""LibraryBoundaryClassifier (ARCF-DI Phase 2) — classifies every
ImportReference as REPOSITORY / EXTERNAL / STDLIB / UNRESOLVED.

Deliberately does not re-derive repository-internal resolution: every
LanguageAnalyzer already fills in ImportReference.resolved_file_path when
a raw import resolves to a workspace file (python_analyzer.py,
go_analyzer.py, etc.) — this classifier only decides EXTERNAL / STDLIB /
UNRESOLVED for the imports that field leaves unresolved, the same "read,
never re-derive" discipline ImportGraph/DependencyGraph already apply to
that field (domain/code_intelligence.py's own docstring for it).

An unsupported ecosystem, or an import that matches no declared
dependency and no stdlib list, is UNRESOLVED — never guessed at as
EXTERNAL. Nothing here reads file content or a manifest itself; it only
consumes the DeclaredDependency list DependencyManifestParser already
produced, keeping this a pure function of (imports, declared
dependencies, language) with no I/O of its own.
"""

import sys
from collections import defaultdict

from domain.code_intelligence import DeclaredDependency, ImportReference, ImportResolutionKind

_ECOSYSTEM_OF_LANGUAGE: dict[str, str] = {
    "python": "pip",
    "typescript": "npm",
    "go": "go",
}
"""Languages this phase can classify beyond REPOSITORY/UNRESOLVED. Every
other language ARCF's analyzers support (java, csharp, kotlin, cpp, rust)
has no manifest parser yet (DependencyManifestParser) and no stdlib list
below, so its imports classify REPOSITORY (via resolved_file_path) or
UNRESOLVED — never a guessed EXTERNAL. Extending coverage means adding a
DependencyManifestParser._parse_* method, an entry here, and (if the
language has one) a stdlib set below."""

_PYTHON_STDLIB_MODULES: frozenset[str] = frozenset(sys.stdlib_module_names)
"""Python's own deterministic enumeration (3.10+) — not hand-maintained."""

_NODE_BUILTIN_MODULES: frozenset[str] = frozenset(
    {
        "assert", "buffer", "child_process", "cluster", "crypto", "dns",
        "events", "fs", "http", "https", "net", "os", "path", "process",
        "querystring", "readline", "stream", "tls", "url", "util", "zlib",
    }
)
"""Node.js core modules a TypeScript/JavaScript import can name without
any package.json entry existing for them. Not exhaustive of every Node
built-in — extend the set (or add a real list) if a real repo surfaces a
false UNRESOLVED for one that's missing; never guess module-by-module."""


def _npm_top_level(module_path: str) -> str:
    parts = module_path.split("/")
    if module_path.startswith("@") and len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def _is_stdlib(raw_module: str, language: str) -> bool:
    if language == "python":
        return raw_module.split(".")[0] in _PYTHON_STDLIB_MODULES
    if language == "typescript":
        return raw_module.removeprefix("node:") in _NODE_BUILTIN_MODULES or _npm_top_level(
            raw_module
        ) in _NODE_BUILTIN_MODULES
    if language == "go":
        # Standard Go convention, not a language guarantee: a domain-
        # qualified import path (github.com/..., golang.org/x/...) always
        # has a dot in its first path segment; the standard library never
        # does ("fmt", "net/http"). Surfaced as a heuristic in
        # BLUEPRINT.md Phase 2, same status as ReferenceResolver's
        # locality scoring in Phase 3 — explainable, deterministic,
        # not proof.
        first_segment = raw_module.split("/")[0]
        return "." not in first_segment
    return False


class LibraryBoundaryClassifier:
    def __init__(self, dependencies: list[DeclaredDependency]) -> None:
        self._by_ecosystem: dict[str, dict[str, DeclaredDependency]] = defaultdict(dict)
        for dep in dependencies:
            self._by_ecosystem[dep.ecosystem][dep.name] = dep

    def classify(self, imports: list[ImportReference], language: str) -> list[ImportReference]:
        """Returns new ImportReference instances (frozen models) with
        resolved_kind/resolved_library set — never mutates its input."""
        return [self._classify_one(imp, language) for imp in imports]

    def _classify_one(self, imp: ImportReference, language: str) -> ImportReference:
        if imp.resolved_file_path is not None:
            return imp.model_copy(update={"resolved_kind": ImportResolutionKind.REPOSITORY})

        if _is_stdlib(imp.raw_module, language):
            return imp.model_copy(update={"resolved_kind": ImportResolutionKind.STDLIB})

        matched = self._match_declared(imp.raw_module, language)
        if matched is not None:
            return imp.model_copy(
                update={
                    "resolved_kind": ImportResolutionKind.EXTERNAL,
                    "resolved_library": matched.name,
                }
            )

        return imp.model_copy(update={"resolved_kind": ImportResolutionKind.UNRESOLVED})

    def _match_declared(self, raw_module: str, language: str) -> DeclaredDependency | None:
        ecosystem = _ECOSYSTEM_OF_LANGUAGE.get(language)
        if ecosystem is None:
            return None
        declared = self._by_ecosystem.get(ecosystem, {})

        if ecosystem == "go":
            # go.mod declares module roots; an import is commonly a
            # subpackage of one ("github.com/hashicorp/consul/agent/cache"
            # under a declared "github.com/hashicorp/consul") — longest
            # matching declared root wins, deterministic tie-break by
            # name length then lexicographic.
            candidates = [
                dep
                for name, dep in declared.items()
                if raw_module == name or raw_module.startswith(name + "/")
            ]
            if not candidates:
                return None
            return sorted(candidates, key=lambda dep: (-len(dep.name), dep.name))[0]

        if ecosystem == "npm":
            return declared.get(_npm_top_level(raw_module))

        if ecosystem == "pip":
            return declared.get(raw_module.split(".")[0])

        return None
