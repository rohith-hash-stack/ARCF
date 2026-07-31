from pathlib import Path

from workspace.scanner import RepositoryScanner


def test_scan_finds_files_and_skips_noise_dirs(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")

    result = RepositoryScanner().scan(tmp_path)
    relative_paths = {f.relative_path for f in result.files}

    assert "src/main.py" in relative_paths
    assert not any(p.startswith("node_modules") for p in relative_paths)
    assert not any(p.startswith(".git") for p in relative_paths)
    assert result.truncated is False


def test_scan_truncates_at_max_files(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"file_{i}.txt").write_text("x")

    result = RepositoryScanner(max_files=3).scan(tmp_path)
    assert len(result.files) == 3
    assert result.truncated is True


def test_scan_records_extension_and_size(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("print(1)")

    result = RepositoryScanner().scan(tmp_path)
    file = next(f for f in result.files if f.relative_path == "a.py")
    assert file.extension == ".py"
    assert file.size_bytes > 0
