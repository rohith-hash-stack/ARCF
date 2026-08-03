from pathlib import Path

import pytest

from benchmark.suite.repo_pool import RepoPool, RepoPoolError


def _fake_arcf_root(tmp_path: Path) -> Path:
    root = tmp_path / "arcf"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mod.py").write_text("x = 1\n")
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "python.exe").write_text("fake")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "junk.pyc").write_text("junk")
    return root


def test_ensure_arcf_base_excludes_venv_and_caches(tmp_path: Path) -> None:
    arcf_root = _fake_arcf_root(tmp_path)
    pool = RepoPool(arcf_root=arcf_root, suite_repos_root=tmp_path / "suite_repos")

    base = pool.ensure_arcf_base()

    assert (base / "src" / "mod.py").exists()
    assert not (base / ".venv").exists()
    assert not (base / "__pycache__").exists()


def test_ensure_arcf_base_refreshes_on_repeat_call(tmp_path: Path) -> None:
    arcf_root = _fake_arcf_root(tmp_path)
    pool = RepoPool(arcf_root=arcf_root, suite_repos_root=tmp_path / "suite_repos")
    pool.ensure_arcf_base()

    (arcf_root / "src" / "new_file.py").write_text("y = 2\n")
    base = pool.ensure_arcf_base()

    assert (base / "src" / "new_file.py").exists()


def test_scratch_copy_is_independent_of_base(tmp_path: Path) -> None:
    arcf_root = _fake_arcf_root(tmp_path)
    pool = RepoPool(arcf_root=arcf_root, suite_repos_root=tmp_path / "suite_repos")
    pool.ensure_arcf_base()

    scratch = pool.scratch_copy("arcf")
    (scratch / "src" / "mod.py").write_text("x = 999\n")

    scratch2 = pool.scratch_copy("arcf")
    assert (scratch2 / "src" / "mod.py").read_text() == "x = 1\n"

    RepoPool.discard(scratch)
    RepoPool.discard(scratch2)


def test_scratch_copy_unknown_repo_key_raises(tmp_path: Path) -> None:
    pool = RepoPool(arcf_root=tmp_path, suite_repos_root=tmp_path / "suite_repos")
    with pytest.raises(RepoPoolError, match="Unknown repo_key"):
        pool.scratch_copy("nonexistent")


def test_scratch_copy_before_base_prepared_raises(tmp_path: Path) -> None:
    pool = RepoPool(arcf_root=tmp_path, suite_repos_root=tmp_path / "suite_repos")
    with pytest.raises(RepoPoolError, match="not prepared"):
        pool.scratch_copy("arcf")


def test_ensure_todomvc_base_skips_network_when_already_installed(tmp_path: Path) -> None:
    pool = RepoPool(arcf_root=tmp_path, suite_repos_root=tmp_path / "suite_repos")
    todomvc_base = tmp_path / "suite_repos" / "todomvc_base"
    (todomvc_base / "node_modules").mkdir(parents=True)
    (todomvc_base / "tests").mkdir()

    result = pool.ensure_todomvc_base()
    assert result == todomvc_base


def test_discard_removes_scratch_dir(tmp_path: Path) -> None:
    arcf_root = _fake_arcf_root(tmp_path)
    pool = RepoPool(arcf_root=arcf_root, suite_repos_root=tmp_path / "suite_repos")
    pool.ensure_arcf_base()
    scratch = pool.scratch_copy("arcf")
    assert scratch.exists()
    RepoPool.discard(scratch)
    assert not scratch.parent.exists()
