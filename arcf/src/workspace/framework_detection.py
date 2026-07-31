"""Framework Detection (Phase 4 deliverable).

Deterministic: parses known manifest files (package.json properly via
json, pyproject.toml properly via tomllib, requirements.txt line by
line) into a set of declared dependency names, then matches against a
fixed marker table — plus a handful of marker *files* (manage.py,
next.config.js) that are themselves reliable signals on their own.
All manifest reads go through PermissionManager.safe_read_text, never
open()/Path.read_text() directly.
"""

import json
import re
import tomllib
from pathlib import Path

from domain.workspace import FrameworkCategory, FrameworkMatch
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager
from workspace.scanner import ScannedFile

_DEPENDENCY_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-@/]+")

_READ_ERRORS: tuple[type[Exception], ...] = (OSError, ValueError, WorkspacePathError)

# framework name -> (category, dependency keywords to match, case-insensitive)
FRAMEWORK_DEPENDENCY_MARKERS: dict[str, tuple[FrameworkCategory, tuple[str, ...]]] = {
    "FastAPI": ("web_backend", ("fastapi",)),
    "Django": ("web_backend", ("django",)),
    "Flask": ("web_backend", ("flask",)),
    "Express": ("web_backend", ("express",)),
    "React": ("web_frontend", ("react",)),
    "Vue": ("web_frontend", ("vue",)),
    "Next.js": ("web_frontend", ("next",)),
    "Pytest": ("testing", ("pytest",)),
    "Playwright": ("testing", ("playwright", "@playwright/test")),
    "LangChain": ("ai_orchestration", ("langchain",)),
    "LangGraph": ("ai_orchestration", ("langgraph",)),
}

# framework name -> (category, marker filenames present anywhere in the scan)
FRAMEWORK_MARKER_FILES: dict[str, tuple[FrameworkCategory, tuple[str, ...]]] = {
    "Django": ("web_backend", ("manage.py",)),
    "Next.js": ("web_frontend", ("next.config.js", "next.config.mjs", "next.config.ts")),
    "Playwright": ("testing", ("playwright.config.ts", "playwright.config.js")),
}


def _strip_dependency_name(spec: str) -> str:
    match = _DEPENDENCY_NAME_RE.match(spec.strip())
    return match.group(0).lower() if match else ""


class FrameworkDetector:
    def __init__(self, permissions: PermissionManager) -> None:
        self._permissions = permissions

    def detect(self, files: list[ScannedFile]) -> list[FrameworkMatch]:
        dependency_names = self._collect_dependency_names(files)
        filenames_present = {Path(file.relative_path).name for file in files}

        matches: dict[str, FrameworkMatch] = {}

        for name, (category, keywords) in FRAMEWORK_DEPENDENCY_MARKERS.items():
            evidence = [kw for kw in keywords if kw.lower() in dependency_names]
            if evidence:
                matches[name] = FrameworkMatch(name=name, category=category, evidence=evidence)

        for name, (category, marker_files) in FRAMEWORK_MARKER_FILES.items():
            evidence = [mf for mf in marker_files if mf in filenames_present]
            if evidence:
                existing = matches.get(name)
                prior_evidence = existing.evidence if existing else []
                combined = sorted(set(prior_evidence) | set(evidence))
                matches[name] = FrameworkMatch(name=name, category=category, evidence=combined)

        return sorted(matches.values(), key=lambda match: match.name)

    def _collect_dependency_names(self, files: list[ScannedFile]) -> set[str]:
        names: set[str] = set()
        for file in files:
            filename = Path(file.relative_path).name
            if filename == "package.json":
                names |= self._parse_package_json(file.relative_path)
            elif filename == "pyproject.toml":
                names |= self._parse_pyproject_toml(file.relative_path)
            elif filename in ("requirements.txt", "requirements-dev.txt"):
                names |= self._parse_requirements_txt(file.relative_path)
        return names

    def _parse_package_json(self, relative_path: str) -> set[str]:
        try:
            data = json.loads(self._permissions.safe_read_text(relative_path))
        except _READ_ERRORS:
            return set()
        names: set[str] = set()
        for key in ("dependencies", "devDependencies"):
            deps = data.get(key)
            if isinstance(deps, dict):
                names.update(name.lower() for name in deps)
        return names

    def _parse_pyproject_toml(self, relative_path: str) -> set[str]:
        try:
            data = tomllib.loads(self._permissions.safe_read_text(relative_path))
        except _READ_ERRORS:
            return set()

        names: set[str] = set()
        project_deps = data.get("project", {}).get("dependencies", [])
        if isinstance(project_deps, list):
            names.update(_strip_dependency_name(dep) for dep in project_deps)

        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        if isinstance(poetry_deps, dict):
            names.update(name.lower() for name in poetry_deps)

        return {name for name in names if name}

    def _parse_requirements_txt(self, relative_path: str) -> set[str]:
        try:
            content = self._permissions.safe_read_text(relative_path)
        except _READ_ERRORS:
            return set()

        names: set[str] = set()
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            names.add(_strip_dependency_name(line))
        return {name for name in names if name}
