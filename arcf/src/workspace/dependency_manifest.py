"""DependencyManifestParser (ARCF-DI Phase 2) — deterministic per-ecosystem
parsing of declared dependencies from manifest files already located by
ProjectStructureAnalyzer's MANIFEST_FILENAMES.

Deliberately narrow scope for this phase: npm (package.json), pip
(pyproject.toml's [project.dependencies], [dependency-groups] (PEP 735),
and Poetry's table, plus requirements.txt), and go (go.mod). Extending
to another ecosystem (Java/Maven, C#/NuGet, Kotlin/
Gradle, Rust/Cargo) means adding one more `_parse_*` method and a filename
branch in `parse()` — nothing else in ARCF-DI's boundary classifier needs
to change, since it only ever consumes the resulting DeclaredDependency
list, never a manifest format directly. An import in a language this
parser has no manifest support for is left for LibraryBoundaryClassifier
to record as UNRESOLVED — never guessed at as EXTERNAL from an unparsed
manifest.

Deliberate, self-contained duplication of FrameworkDetector's own
manifest-reading pattern (PermissionManager.safe_read_text, json/tomllib
for structured formats, line-by-line for requirements.txt) rather than
importing its private per-format methods: FrameworkDetector only needs a
lowercased name set for keyword matching and stays that way, this module
also needs the declared version spec and a source line per dependency
(ExternalLibraryReference.manifest_location) that FrameworkDetector has no
use for. A future consolidation of the two shared read/parse helpers is a
reasonable follow-up, not done here to keep this phase additive-only.
"""

import json
import re
import tomllib
from pathlib import Path

from domain.code_intelligence import DeclaredDependency, SourceLocation
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager
from workspace.scanner import ScannedFile

_READ_ERRORS: tuple[type[Exception], ...] = (OSError, ValueError, WorkspacePathError)

# name[extras]comparator... -> just the bare name, same shape as a PEP 508
# requirement or a requirements.txt line before any version specifier.
_PEP_508_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+")


def _pip_name(spec: str) -> tuple[str, str | None]:
    """Splits a PEP 508 / requirements.txt entry into (lowercased bare
    name, verbatim version spec or None). "fastapi>=0.115" ->
    ("fastapi", ">=0.115"); "fastapi" -> ("fastapi", None)."""
    stripped = spec.strip()
    match = _PEP_508_NAME_RE.match(stripped)
    if not match:
        return "", None
    name = match.group(0).lower()
    rest = stripped[match.end() :].strip()
    return name, (rest or None)


def _npm_top_level(module_path: str) -> str:
    """"axios/lib/utils" -> "axios"; "@playwright/test/reporter" ->
    "@playwright/test" (scoped packages are two path segments)."""
    parts = module_path.split("/")
    if module_path.startswith("@") and len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


class DependencyManifestParser:
    def __init__(self, permissions: PermissionManager) -> None:
        self._permissions = permissions

    def parse(self, files: list[ScannedFile]) -> list[DeclaredDependency]:
        dependencies: list[DeclaredDependency] = []
        for file in files:
            filename = Path(file.relative_path).name
            if filename == "package.json":
                dependencies += self._parse_package_json(file.relative_path)
            elif filename == "pyproject.toml":
                dependencies += self._parse_pyproject_toml(file.relative_path)
            elif filename in ("requirements.txt", "requirements-dev.txt"):
                dependencies += self._parse_requirements_txt(file.relative_path)
            elif filename == "go.mod":
                dependencies += self._parse_go_mod(file.relative_path)
        # ecosystem then name: deterministic regardless of scan order, and
        # groups a repo's dependencies the way a person would scan them.
        return sorted(dependencies, key=lambda dep: (dep.ecosystem, dep.name))

    def _parse_package_json(self, relative_path: str) -> list[DeclaredDependency]:
        try:
            raw_text = self._permissions.safe_read_text(relative_path)
            data = json.loads(raw_text)
        except _READ_ERRORS:
            return []

        results: list[DeclaredDependency] = []
        seen: set[str] = set()
        for key in ("dependencies", "devDependencies"):
            deps = data.get(key)
            if not isinstance(deps, dict):
                continue
            for name, version in deps.items():
                if name in seen:
                    continue
                seen.add(name)
                location = _locate_key_line(raw_text, name, relative_path)
                results.append(
                    DeclaredDependency(
                        name=name.lower(),
                        ecosystem="npm",
                        version_spec=str(version) if version is not None else None,
                        manifest_location=location,
                    )
                )
        return results

    def _parse_pyproject_toml(self, relative_path: str) -> list[DeclaredDependency]:
        try:
            raw_text = self._permissions.safe_read_text(relative_path)
            data = tomllib.loads(raw_text)
        except _READ_ERRORS:
            return []

        results: list[DeclaredDependency] = []
        seen: set[str] = set()

        project_deps = data.get("project", {}).get("dependencies", [])
        if isinstance(project_deps, list):
            for entry in project_deps:
                if not isinstance(entry, str):
                    continue
                name, version = _pip_name(entry)
                if not name or name in seen:
                    continue
                seen.add(name)
                results.append(
                    DeclaredDependency(
                        name=name,
                        ecosystem="pip",
                        version_spec=version,
                        manifest_location=_locate_list_entry_line(raw_text, entry, relative_path),
                    )
                )

        for group_entries in data.get("dependency-groups", {}).values():
            if not isinstance(group_entries, list):
                continue
            for entry in group_entries:
                # PEP 735 group entries are either a plain requirement
                # string or a {include-group = "..."} table referencing
                # another group -- the latter names a group, not a
                # package, so it's skipped rather than parsed as one.
                if not isinstance(entry, str):
                    continue
                name, version = _pip_name(entry)
                if not name or name in seen:
                    continue
                seen.add(name)
                results.append(
                    DeclaredDependency(
                        name=name,
                        ecosystem="pip",
                        version_spec=version,
                        manifest_location=_locate_list_entry_line(raw_text, entry, relative_path),
                    )
                )

        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        if isinstance(poetry_deps, dict):
            for name, spec in poetry_deps.items():
                lowered = name.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                poetry_version: str | None
                if isinstance(spec, str):
                    poetry_version = spec
                elif isinstance(spec, dict):
                    poetry_version = spec.get("version")
                else:
                    poetry_version = None
                results.append(
                    DeclaredDependency(
                        name=lowered,
                        ecosystem="pip",
                        version_spec=poetry_version,
                        manifest_location=_locate_key_line(raw_text, name, relative_path),
                    )
                )
        return results

    def _parse_requirements_txt(self, relative_path: str) -> list[DeclaredDependency]:
        try:
            content = self._permissions.safe_read_text(relative_path)
        except _READ_ERRORS:
            return []

        results: list[DeclaredDependency] = []
        seen: set[str] = set()
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            name, version = _pip_name(line)
            if not name or name in seen:
                continue
            seen.add(name)
            results.append(
                DeclaredDependency(
                    name=name,
                    ecosystem="pip",
                    version_spec=version,
                    manifest_location=SourceLocation(
                        file_path=relative_path, start_line=line_number, end_line=line_number
                    ),
                )
            )
        return results

    def _parse_go_mod(self, relative_path: str) -> list[DeclaredDependency]:
        try:
            content = self._permissions.safe_read_text(relative_path)
        except _READ_ERRORS:
            return []

        results: list[DeclaredDependency] = []
        seen: set[str] = set()
        in_require_block = False
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("require") and line.endswith("("):
                in_require_block = True
                continue
            if in_require_block and line == ")":
                in_require_block = False
                continue

            entry: str | None = None
            if in_require_block:
                entry = line
            elif line.startswith("require "):
                entry = line[len("require ") :].strip()
            if entry is None:
                continue

            parts = entry.split()
            if len(parts) < 2:
                continue
            name, version = parts[0], parts[1]
            if name in seen:
                continue
            seen.add(name)
            results.append(
                DeclaredDependency(
                    name=name,
                    ecosystem="go",
                    version_spec=version,
                    manifest_location=SourceLocation(
                        file_path=relative_path, start_line=line_number, end_line=line_number
                    ),
                )
            )
        return results


def _locate_key_line(raw_text: str, key: str, file_path: str) -> SourceLocation:
    """Best-effort line lookup for a JSON/TOML key by scanning raw text for
    its first quoted occurrence — json/tomllib give no line numbers.
    First occurrence only: if the same key legitimately appears twice
    (e.g. once in "dependencies", once in "devDependencies"), this points
    at the first one, a documented simplification rather than a claim of
    exhaustive provenance."""
    needle = f'"{key}"'
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        if needle in line:
            return SourceLocation(file_path=file_path, start_line=line_number, end_line=line_number)
    return SourceLocation(file_path=file_path, start_line=1, end_line=1)


def _locate_list_entry_line(raw_text: str, entry: str, file_path: str) -> SourceLocation:
    """Line lookup for a TOML/JSON list entry (a `[project.dependencies]`
    or `[dependency-groups]` string), searching for the entry's own
    quoted text rather than just the parsed package name. A version
    specifier attached to the entry — the overwhelmingly common case —
    means the bare name is rarely a literal substring of the source
    line: `"fastapi"` does not appear inside `"fastapi>=0.115"`, so
    `_locate_key_line(raw_text, "fastapi", ...)` silently fell back to
    line 1 for nearly every real `[project.dependencies]` entry before
    this existed. First occurrence only, same simplification as
    `_locate_key_line`."""
    needle = f'"{entry}"'
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        if needle in line:
            return SourceLocation(file_path=file_path, start_line=line_number, end_line=line_number)
    return SourceLocation(file_path=file_path, start_line=1, end_line=1)
