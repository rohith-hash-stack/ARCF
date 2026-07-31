from workspace.language_detection import LanguageDetector
from workspace.scanner import ScannedFile


def _file(path: str) -> ScannedFile:
    extension = "." + path.rsplit(".", 1)[-1] if "." in path else ""
    return ScannedFile(relative_path=path, extension=extension.lower(), size_bytes=10)


def test_detects_and_ranks_languages() -> None:
    files = [_file("a.py"), _file("b.py"), _file("c.js"), _file("readme.unknownext")]
    stats = LanguageDetector().detect(files)

    assert stats[0].language == "Python"
    assert stats[0].file_count == 2
    languages = {stat.language for stat in stats}
    assert "JavaScript" in languages
    assert sum(stat.file_count for stat in stats) == 3  # unknown extension excluded


def test_percentages_sum_to_roughly_100() -> None:
    files = [_file("a.py"), _file("b.py"), _file("c.js")]
    stats = LanguageDetector().detect(files)
    assert abs(sum(stat.percentage for stat in stats) - 100.0) < 0.1


def test_empty_inventory_returns_empty_list() -> None:
    assert LanguageDetector().detect([]) == []
