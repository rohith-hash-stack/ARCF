from workspace.repository_segmentation import ROOT_SEGMENT, RepositorySegmenter
from workspace.scanner import ScannedFile


def _file(path: str) -> ScannedFile:
    return ScannedFile(relative_path=path, extension="", size_bytes=1)


def _monorepo_files() -> list[ScannedFile]:
    return [
        _file("services/api/pyproject.toml"),
        _file("services/api/app/main.py"),
        _file("services/api/app/auth.py"),
        _file("services/web/package.json"),
        _file("services/web/src/index.ts"),
        _file("README.md"),
    ]


def test_single_repo_has_only_the_root_segment() -> None:
    files = [_file("pyproject.toml"), _file("src/app.py")]
    segmenter = RepositorySegmenter(files)
    assert segmenter.segment_roots == [ROOT_SEGMENT]
    assert segmenter.segment_of("src/app.py") == ROOT_SEGMENT


def test_monorepo_detects_nested_segment_roots() -> None:
    segmenter = RepositorySegmenter(_monorepo_files())
    assert set(segmenter.segment_roots) == {ROOT_SEGMENT, "services/api", "services/web"}


def test_segment_of_resolves_files_to_their_nearest_manifest_directory() -> None:
    segmenter = RepositorySegmenter(_monorepo_files())
    assert segmenter.segment_of("services/api/app/auth.py") == "services/api"
    assert segmenter.segment_of("services/web/src/index.ts") == "services/web"
    assert segmenter.segment_of("README.md") == ROOT_SEGMENT


def test_workspace_config_filenames_also_mark_a_segment() -> None:
    files = [_file("apps/foo/turbo.json"), _file("apps/foo/index.js")]
    segmenter = RepositorySegmenter(files)
    assert segmenter.segment_of("apps/foo/index.js") == "apps/foo"


def test_dominant_segment_picks_the_most_common_segment() -> None:
    segmenter = RepositorySegmenter(_monorepo_files())
    dominant = segmenter.dominant_segment(
        ["services/api/app/main.py", "services/api/app/auth.py", "services/web/src/index.ts"]
    )
    assert dominant == "services/api"


def test_dominant_segment_of_empty_list_is_root() -> None:
    segmenter = RepositorySegmenter(_monorepo_files())
    assert segmenter.dominant_segment([]) == ROOT_SEGMENT
