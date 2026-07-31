"""Git Repository Discovery (Phase 4 deliverable).

Reads only git metadata (branch, HEAD, remotes, dirty state) via
GitPython — never file contents. search_parent_directories=True means
the discovered repo root can legitimately sit above workspace_root
(a workspace can be a subdirectory of a larger repo); that's expected
and is not a containment violation, unlike scanner.py/framework
detection reading arbitrary file bodies.
"""

from pathlib import Path

from git import InvalidGitRepositoryError, NoSuchPathError, Repo

from domain.workspace import RepositoryMetadata


class GitRepositoryDiscovery:
    def discover(self, workspace_root: Path) -> RepositoryMetadata:
        try:
            repo = Repo(str(workspace_root), search_parent_directories=True)
        except (InvalidGitRepositoryError, NoSuchPathError):
            return RepositoryMetadata(is_git_repo=False)

        try:
            branch: str | None = repo.active_branch.name
        except TypeError:
            branch = None  # detached HEAD

        try:
            head_commit: str | None = repo.head.commit.hexsha
        except ValueError:
            head_commit = None  # no commits yet

        remote_urls = [url for remote in repo.remotes for url in remote.urls]

        try:
            is_dirty = repo.is_dirty(untracked_files=True)
        except ValueError:
            is_dirty = False

        working_tree_dir = repo.working_tree_dir
        return RepositoryMetadata(
            is_git_repo=True,
            root_path=str(working_tree_dir) if working_tree_dir is not None else None,
            current_branch=branch,
            head_commit=head_commit,
            remote_urls=remote_urls,
            is_dirty=is_dirty,
        )
