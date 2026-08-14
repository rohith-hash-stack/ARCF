"""DependencyManifestParser (ARCF-DI Phase 2) — deterministic per-ecosystem
parsing of declared dependencies from manifest files already located by
ProjectStructureAnalyzer's MANIFEST_FILENAMES.

Deliberately narrow scope for this phase: npm (package.json), pip
(pyproject.toml's [project.dependencies], [dependency-groups] (PEP 735),
Poetry's classic table and native [tool.poetry.group.*.dependencies]
tables, setup.cfg's [options] install_requires/[options.extras_require],
setup.py's literal install_requires/extras_require keyword arguments to
setup(), and requirements.txt), and go (go.mod). Extending to another
ecosystem (Java/Maven, C#/NuGet, Kotlin/
Gradle, Rust/Cargo) means adding one more `_parse_*` method and a filename
branch in `parse()` — nothing else in ARCF-DI's boundary classifier needs
to change, since it only ever consumes the resulting DeclaredDependency
list, never a manifest format directly. An import in a language this
parser has no manifest support for is left for LibraryBoundaryClassifier
to record as UNRESOLVED — never guessed at as EXTERNAL from an unparsed
manifest. Same discipline applies within a supported format: setup.py's
install_requires/extras_require are only read when they're literal
list/tuple-of-string-constants in the source — a value built from a
variable, a file read, or any other computed expression is skipped
rather than guessed at, since evaluating arbitrary setup.py code is both
unsafe and, for a value that isn't a literal, not actually evidence of
anything until it's actually run.

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

import ast
import configparser
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


def _parse_poetry_dep_dict(
    entries: dict[str, object], raw_text: str, relative_path: str, seen: set[str]
) -> list[DeclaredDependency]:
    """Shared dict-shaped parser for both [tool.poetry.dependencies] and
    each [tool.poetry.group.<name>.dependencies] table -- same {name:
    spec} shape either way, where spec is a bare version string or a
    {version = "...", extras = [...]} table."""
    results: list[DeclaredDependency] = []
    for name, spec in entries.items():
        lowered = name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        version: str | None
        if isinstance(spec, str):
            version = spec
        elif isinstance(spec, dict):
            version = spec.get("version")
        else:
            version = None
        results.append(
            DeclaredDependency(
                name=lowered,
                ecosystem="pip",
                version_spec=version,
                manifest_location=_locate_toml_dict_key_line(raw_text, name, relative_path),
            )
        )
    return results


def _is_setup_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "setup"
    if isinstance(func, ast.Attribute):
        return func.attr == "setup"
    return False


def _extract_setup_py_string_list(
    node: ast.expr | None, relative_path: str, seen: set[str]
) -> list[DeclaredDependency]:
    """Reads a setup()/extras_require keyword's value only when it's a
    literal list/tuple of string constants -- the only shape that's
    actually evidence without executing the file. A value assembled from
    a variable, a file read, string concatenation, or anything else
    computed is skipped entirely rather than guessed at."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    results: list[DeclaredDependency] = []
    for element in node.elts:
        if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
            continue
        name, version = _pip_name(element.value)
        if not name or name in seen:
            continue
        seen.add(name)
        results.append(
            DeclaredDependency(
                name=name,
                ecosystem="pip",
                version_spec=version,
                manifest_location=SourceLocation(
                    file_path=relative_path,
                    start_line=element.lineno,
                    end_line=getattr(element, "end_lineno", None) or element.lineno,
                ),
            )
        )
    return results


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
            elif filename == "setup.cfg":
                dependencies += self._parse_setup_cfg(file.relative_path)
            elif filename == "setup.py":
                dependencies += self._parse_setup_py(file.relative_path)
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

        poetry_section = data.get("tool", {}).get("poetry", {})

        poetry_deps = poetry_section.get("dependencies", {})
        if isinstance(poetry_deps, dict):
            results += _parse_poetry_dep_dict(poetry_deps, raw_text, relative_path, seen)

        # Poetry's own native grouped-dependencies syntax --
        # [tool.poetry.group.<name>.dependencies] -- is a second,
        # distinct table shape from both [tool.poetry.dependencies]
        # above and PEP 735's [dependency-groups]: each group is a
        # dict-of-dicts (group name -> {"dependencies": {pkg: spec}}),
        # not a list of requirement strings, so it needs the dict-shaped
        # parser here rather than the list-shaped one used for
        # dependency-groups.
        poetry_groups = poetry_section.get("group", {})
        if isinstance(poetry_groups, dict):
            for group in poetry_groups.values():
                if not isinstance(group, dict):
                    continue
                group_deps = group.get("dependencies", {})
                if isinstance(group_deps, dict):
                    results += _parse_poetry_dep_dict(group_deps, raw_text, relative_path, seen)

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

    def _parse_setup_cfg(self, relative_path: str) -> list[DeclaredDependency]:
        try:
            raw_text = self._permissions.safe_read_text(relative_path)
            parser = configparser.ConfigParser()
            parser.read_string(raw_text)
        except (OSError, ValueError, WorkspacePathError, configparser.Error):
            return []

        entries: list[str] = []
        if parser.has_option("options", "install_requires"):
            entries += parser.get("options", "install_requires").splitlines()
        if parser.has_section("options.extras_require"):
            for _extra_name, value in parser.items("options.extras_require"):
                entries += value.splitlines()

        results: list[DeclaredDependency] = []
        seen: set[str] = set()
        for raw_entry in entries:
            entry = raw_entry.strip()
            if not entry or entry.startswith("#"):
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
                    manifest_location=_locate_bare_text_line(raw_text, entry, relative_path),
                )
            )
        return results

    def _parse_setup_py(self, relative_path: str) -> list[DeclaredDependency]:
        try:
            raw_text = self._permissions.safe_read_text(relative_path)
            tree = ast.parse(raw_text)
        except (OSError, ValueError, WorkspacePathError, SyntaxError):
            return []

        results: list[DeclaredDependency] = []
        seen: set[str] = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_setup_call(node)):
                continue
            for keyword in node.keywords:
                if keyword.arg == "install_requires":
                    results += _extract_setup_py_string_list(keyword.value, relative_path, seen)
                elif keyword.arg == "extras_require" and isinstance(keyword.value, ast.Dict):
                    for value_node in keyword.value.values:
                        results += _extract_setup_py_string_list(value_node, relative_path, seen)
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


def _locate_toml_dict_key_line(raw_text: str, key: str, file_path: str) -> SourceLocation:
    """Line lookup for a TOML dict-table entry (`[tool.poetry.dependencies]`
    / `[tool.poetry.group.*.dependencies]`), where the key is a bare,
    unquoted identifier on its own line (`requests = "^2.28.0"`) --
    unlike `_locate_key_line`'s quoted-substring search, which never
    matches this shape at all and would silently fall back to line 1 for
    every entry."""
    pattern = re.compile(rf'^\s*"?{re.escape(key)}"?\s*=')
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        if pattern.match(line):
            return SourceLocation(file_path=file_path, start_line=line_number, end_line=line_number)
    return SourceLocation(file_path=file_path, start_line=1, end_line=1)


def _locate_bare_text_line(raw_text: str, entry: str, file_path: str) -> SourceLocation:
    """Line lookup for a setup.cfg list entry (`install_requires`/
    `extras_require` values are plain, unquoted lines once configparser
    strips the section's shared indentation) -- a direct substring
    search, no quoting, since setup.cfg's INI format never quotes these."""
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        if entry in line:
            return SourceLocation(file_path=file_path, start_line=line_number, end_line=line_number)
    return SourceLocation(file_path=file_path, start_line=1, end_line=1)
