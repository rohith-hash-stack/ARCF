from pathlib import Path

from benchmark.suite.patcher import apply_output_to_repo, parse_file_blocks


def test_parses_single_file_block() -> None:
    text = "### src/a.py\n```\nprint('hi')\n```"
    blocks = parse_file_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].path == "src/a.py"
    assert blocks[0].content == "print('hi')"


def test_parses_multiple_file_blocks() -> None:
    text = "### src/a.py\n```\ncode a\n```\n\n### src/b.py\n```\ncode b\n```"
    blocks = parse_file_blocks(text)
    assert [b.path for b in blocks] == ["src/a.py", "src/b.py"]
    assert [b.content for b in blocks] == ["code a", "code b"]


def test_apply_writes_files_and_reports_applied(tmp_path: Path) -> None:
    text = "### src/new.py\n```\nprint(1)\n```"
    result = apply_output_to_repo(tmp_path, text, protected_path_prefixes=[])
    assert result.applied is True
    assert result.written_paths == ["src/new.py"]
    assert (tmp_path / "src" / "new.py").read_text() == "print(1)\n"


def test_apply_skips_protected_paths(tmp_path: Path) -> None:
    text = "### tests/test_a.py\n```\nassert False\n```"
    result = apply_output_to_repo(tmp_path, text, protected_path_prefixes=["tests/"])
    assert result.applied is False
    assert result.skipped_protected_paths == ["tests/test_a.py"]
    assert not (tmp_path / "tests" / "test_a.py").exists()


def test_apply_with_no_blocks_reports_not_applied(tmp_path: Path) -> None:
    result = apply_output_to_repo(
        tmp_path, "just prose, no file blocks", protected_path_prefixes=[]
    )
    assert result.applied is False
    assert result.written_paths == []


def test_apply_normalizes_backslash_paths(tmp_path: Path) -> None:
    text = "### src\\nested\\file.py\n```\nx = 1\n```"
    result = apply_output_to_repo(tmp_path, text, protected_path_prefixes=[])
    assert result.written_paths == ["src/nested/file.py"]
    assert (tmp_path / "src" / "nested" / "file.py").exists()
