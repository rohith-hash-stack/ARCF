"""RepoPool — prepares a fresh, disposable scratch copy of a suite
task's target repository for every single task run.

Two repo kinds today: 'arcf' (this project's own backend, used for
Repository Understanding/Bug Fixing/Refactoring) and 'todomvc'
(microsoft/playwright's examples/todomvc, used for Test Generation).
Each has a ONE-TIME "base" checkout (ensure_arcf_base/ensure_todomvc_base)
and a cheap per-run scratch_copy() that never touches that base or the
real project directories — a task's generated diff, or a bug fixture,
is applied to the scratch copy only. If a run corrupts its scratch
copy, the next run is unaffected; nothing here ever runs `git` against
the actual arcf/ or benchmark/ working trees.
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from workspace.scanner import SKIP_DIRECTORY_NAMES

_TODOMVC_REPO_URL = "https://github.com/microsoft/playwright.git"
_TODOMVC_SPARSE_PATH = "examples/todomvc"


class RepoPoolError(Exception):
    """A base repo isn't prepared yet, or preparing/copying it failed."""


def _ignore_skip_dirs(_dir: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SKIP_DIRECTORY_NAMES}


def _force_rmtree(path: Path) -> None:
    """git clones pack files read-only; plain rmtree fails on Windows
    (PermissionError) trying to delete them. Clear the read-only bit on
    whatever failed to delete, then retry once."""

    def _on_error(func, target_path, _exc_info):  # type: ignore[no-untyped-def]
        os.chmod(target_path, stat.S_IWRITE)
        func(target_path)

    shutil.rmtree(path, onerror=_on_error)


class RepoPool:
    def __init__(self, arcf_root: Path, suite_repos_root: Path) -> None:
        self._arcf_root = arcf_root
        self._suite_repos_root = suite_repos_root
        self._arcf_base = suite_repos_root / "arcf_base"
        self._todomvc_base = suite_repos_root / "todomvc_base"

    @property
    def arcf_venv_python(self) -> Path:
        if sys.platform == "win32":
            return self._arcf_root / ".venv" / "Scripts" / "python.exe"
        return self._arcf_root / ".venv" / "bin" / "python"

    def ensure_arcf_base(self) -> Path:
        """Copies the real arcf/ (excluding .venv/.git/caches) into a
        base checkout once. Cheap enough to always refresh: it reflects
        arcf/'s current state, not a stale snapshot, without ever
        touching arcf/ itself."""
        if self._arcf_base.exists():
            _force_rmtree(self._arcf_base)
        shutil.copytree(self._arcf_root, self._arcf_base, ignore=_ignore_skip_dirs)
        return self._arcf_base

    def ensure_todomvc_base(self) -> Path:
        """One-time network setup: sparse-clones examples/todomvc, then
        `npm install` + `npx playwright install chromium`. Caller is
        responsible for getting explicit user go-ahead before invoking
        this — it downloads a browser binary. Idempotent: skipped if
        the base already has node_modules installed.
        """
        if (self._todomvc_base / "node_modules").exists():
            return self._todomvc_base

        self._suite_repos_root.mkdir(parents=True, exist_ok=True)
        clone_dir = self._suite_repos_root / "_todomvc_clone"
        if clone_dir.exists():
            _force_rmtree(clone_dir)

        self._run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                   _TODOMVC_REPO_URL, str(clone_dir)])
        self._run(["git", "sparse-checkout", "set", _TODOMVC_SPARSE_PATH], cwd=clone_dir)

        source = clone_dir / _TODOMVC_SPARSE_PATH
        if self._todomvc_base.exists():
            _force_rmtree(self._todomvc_base)
        shutil.copytree(source, self._todomvc_base)
        _force_rmtree(clone_dir)

        self._run(["npm", "install"], cwd=self._todomvc_base)
        self._run(["npx", "playwright", "install", "chromium"], cwd=self._todomvc_base)
        return self._todomvc_base

    def scratch_copy(self, repo_key: str) -> Path:
        base = {"arcf": self._arcf_base, "todomvc": self._todomvc_base}.get(repo_key)
        if base is None:
            raise RepoPoolError(f"Unknown repo_key {repo_key!r}")
        if not base.exists():
            raise RepoPoolError(
                f"Base checkout for {repo_key!r} not prepared — call "
                f"ensure_{repo_key}_base() first."
            )
        scratch_root = Path(tempfile.mkdtemp(prefix=f"arcf-suite-{repo_key}-"))
        scratch_dir = scratch_root / "repo"
        # base checkouts are already filtered (ensure_arcf_base) or have no
        # excluded dirs to begin with (ensure_todomvc_base) — a straight copy.
        shutil.copytree(base, scratch_dir)
        return scratch_dir

    @staticmethod
    def discard(scratch_dir: Path) -> None:
        shutil.rmtree(scratch_dir.parent, ignore_errors=True)

    @staticmethod
    def _run(args: list[str], cwd: Path | None = None) -> None:
        # npm/npx on Windows are .cmd shims — CreateProcess can't exec
        # those directly without going through a shell.
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
            shell=sys.platform == "win32",
        )
        if result.returncode != 0:
            raise RepoPoolError(
                f"Command {' '.join(args)!r} failed (exit {result.returncode}): "
                f"{result.stderr[-2000:]}"
            )
