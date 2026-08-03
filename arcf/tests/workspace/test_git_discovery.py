from pathlib import Path

import git

from workspace.git_discovery import GitRepositoryDiscovery


def _init_repo(path: Path) -> git.Repo:
    repo = git.Repo.init(path)
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "Test User")
        writer.set_value("user", "email", "test@example.com")
    (path / "README.md").write_text("hello")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    return repo


def test_non_git_directory_reports_not_a_repo(tmp_path: Path) -> None:
    metadata = GitRepositoryDiscovery().discover(tmp_path)
    assert metadata.is_git_repo is False
    assert metadata.root_path is None


def test_git_repo_reports_branch_and_commit(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    metadata = GitRepositoryDiscovery().discover(tmp_path)

    assert metadata.is_git_repo is True
    assert metadata.head_commit == repo.head.commit.hexsha
    assert metadata.current_branch in ("main", "master")
    assert metadata.is_dirty is False


def test_dirty_working_tree_detected(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "new_file.txt").write_text("uncommitted")

    metadata = GitRepositoryDiscovery().discover(tmp_path)
    assert metadata.is_dirty is True


def test_remote_urls_collected(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    repo.create_remote("origin", "https://example.com/repo.git")

    metadata = GitRepositoryDiscovery().discover(tmp_path)
    assert "https://example.com/repo.git" in metadata.remote_urls
