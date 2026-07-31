from pathlib import Path

import pytest

from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager


def test_resolve_relative_path_within_workspace(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)")
    manager = PermissionManager(tmp_path)
    resolved = manager.resolve_within_workspace("src/main.py")
    assert resolved == (tmp_path / "src" / "main.py").resolve()


def test_resolve_rejects_path_traversal(tmp_path: Path) -> None:
    manager = PermissionManager(tmp_path)
    with pytest.raises(WorkspacePathError):
        manager.resolve_within_workspace("../outside.txt")


def test_resolve_rejects_absolute_path_outside_workspace(tmp_path: Path) -> None:
    manager = PermissionManager(tmp_path)
    with pytest.raises(WorkspacePathError):
        manager.resolve_within_workspace(tmp_path.parent / "outside.txt")


def test_resolve_allows_workspace_root_itself(tmp_path: Path) -> None:
    manager = PermissionManager(tmp_path)
    assert manager.resolve_within_workspace(".") == tmp_path.resolve()


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".env.local",
        "id_rsa",
        "id_rsa.pub",
        "secrets.yaml",
        "aws_credentials.json",
        "key.pem",
    ],
)
def test_is_sensitive_matches_known_patterns(name: str) -> None:
    manager = PermissionManager(Path("."))
    assert manager.is_sensitive(name) is True


def test_is_sensitive_false_for_normal_file() -> None:
    manager = PermissionManager(Path("."))
    assert manager.is_sensitive("main.py") is False


def test_safe_read_text_reads_normal_file(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("hello world")
    manager = PermissionManager(tmp_path)
    assert manager.safe_read_text("readme.txt") == "hello world"


def test_safe_read_text_refuses_sensitive_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1")
    manager = PermissionManager(tmp_path)
    with pytest.raises(WorkspacePathError):
        manager.safe_read_text(".env")


def test_safe_read_text_refuses_path_escape(tmp_path: Path) -> None:
    manager = PermissionManager(tmp_path)
    with pytest.raises(WorkspacePathError):
        manager.safe_read_text("../escape.txt")
