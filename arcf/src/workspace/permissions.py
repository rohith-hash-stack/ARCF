"""Permission & Security Manager (Phase 4 deliverable).

The one place that decides whether a path is safe to touch. Every other
module in workspace/ that reads a file (framework_detection.py's
manifest parsing) or enumerates the tree (scanner.py) goes through this
— not `open()` directly — so containment and sensitivity rules can't be
silently bypassed by a new caller forgetting to check. Phase 5's Code
Intelligence Engine, which reads far more file content, is expected to
depend on this same boundary rather than reinvent one.
"""

import fnmatch
from pathlib import Path

from shared.errors import WorkspacePathError

SENSITIVE_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_rsa.*",
    "*credentials*",
    "*.p12",
    "*.pfx",
    "secrets.*",
    "*.secret",
)


class PermissionManager:
    def __init__(self, workspace_root: Path) -> None:
        self._workspace_root = workspace_root.resolve()

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    def resolve_within_workspace(self, path: str | Path) -> Path:
        """Resolve `path` (relative to the workspace root, or absolute) and
        verify it does not escape the workspace root — via `..`, an
        absolute path elsewhere, or a symlink pointing outside it.
        """
        candidate = Path(path)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self._workspace_root / candidate).resolve()
        )
        if resolved != self._workspace_root and self._workspace_root not in resolved.parents:
            raise WorkspacePathError(
                f"Path {path!r} resolves to {resolved}, which escapes workspace root "
                f"{self._workspace_root}"
            )
        return resolved

    def is_sensitive(self, path: str | Path) -> bool:
        name = Path(path).name
        return any(fnmatch.fnmatch(name.lower(), pattern) for pattern in SENSITIVE_PATTERNS)

    def safe_read_text(self, path: str | Path) -> str:
        """Read a file's text content after containment + sensitivity checks.
        Raises WorkspacePathError for both an out-of-bounds path and a
        sensitive one — callers get one exception type to handle either way.
        """
        resolved = self.resolve_within_workspace(path)
        if self.is_sensitive(resolved):
            raise WorkspacePathError(f"Refusing to read sensitive file: {resolved}")
        return resolved.read_text(encoding="utf-8", errors="replace")
