import json
from pathlib import Path

from workspace.dependency_manifest import DependencyManifestParser
from workspace.permissions import PermissionManager
from workspace.scanner import RepositoryScanner


def _parse(tmp_path: Path):
    scan = RepositoryScanner().scan(tmp_path)
    return DependencyManifestParser(PermissionManager(tmp_path)).parse(scan.files)


def test_parses_package_json_dependencies_and_dev_dependencies(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"axios": "^1.7.2"}, "devDependencies": {"vitest": "^2.0.0"}})
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["axios"].ecosystem == "npm"
    assert by_name["axios"].version_spec == "^1.7.2"
    assert by_name["vitest"].version_spec == "^2.0.0"


def test_package_json_dependency_key_appearing_twice_kept_once(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}, "devDependencies": {"react": "^18.0.0"}})
    )
    deps = _parse(tmp_path)
    assert len([d for d in deps if d.name == "react"]) == 1


def test_parses_pyproject_project_dependencies(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["fastapi>=0.115", "pydantic>=2.9"]\n'
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["fastapi"].ecosystem == "pip"
    assert by_name["fastapi"].version_spec == ">=0.115"
    assert by_name["pydantic"].version_spec == ">=2.9"


def test_parses_pyproject_poetry_dependencies_string_and_dict_form(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry.dependencies]\n"
        'requests = "^2.28.0"\n'
        'httpx = { version = "^0.27", extras = ["http2"] }\n'
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["requests"].version_spec == "^2.28.0"
    assert by_name["httpx"].version_spec == "^0.27"


def test_parses_requirements_txt_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "# a comment\n\nrequests>=2.28.0\n-e ./local-pkg\nnumpy\n"
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["requests"].version_spec == ">=2.28.0"
    assert by_name["numpy"].version_spec is None
    assert "local-pkg" not in by_name


def test_parses_go_mod_single_line_and_block_require(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text(
        "module github.com/example/svc\n\n"
        "go 1.22\n\n"
        "require github.com/hashicorp/consul v1.20.0\n\n"
        "require (\n"
        "\tgithub.com/stretchr/testify v1.9.0\n"
        "\tgolang.org/x/sync v0.7.0\n"
        ")\n"
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["github.com/hashicorp/consul"].version_spec == "v1.20.0"
    assert by_name["github.com/hashicorp/consul"].ecosystem == "go"
    assert by_name["github.com/stretchr/testify"].version_spec == "v1.9.0"
    assert by_name["golang.org/x/sync"].version_spec == "v0.7.0"


def test_ignores_malformed_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{not valid json")
    assert _parse(tmp_path) == []


def test_empty_workspace_yields_no_dependencies(tmp_path: Path) -> None:
    assert _parse(tmp_path) == []


def test_manifest_location_points_at_declaring_file(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests>=2.28.0\n")
    deps = _parse(tmp_path)
    assert deps[0].manifest_location.file_path == "requirements.txt"
    assert deps[0].manifest_location.start_line == 1


def test_result_sorted_by_ecosystem_then_name(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("zeta\nalpha\n")
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"beta": "1.0.0"}}))
    deps = _parse(tmp_path)
    assert [(d.ecosystem, d.name) for d in deps] == [
        ("npm", "beta"),
        ("pip", "alpha"),
        ("pip", "zeta"),
    ]


# --- PEP 735 [dependency-groups], found missing by real-repo validation --
# (arcf-di/PROGRESS.md's "real-repo validation" entry: pallets/click
# declares its test/dev dependencies this way, not via
# [project.dependencies] or Poetry's table -- neither of which this
# parser read before this fix, so real pytest/ruff/etc. imports were
# landing UNRESOLVED instead of EXTERNAL for a repo shaped exactly like
# a real, common, modern pyproject.toml.)


def test_parses_dependency_groups(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[dependency-groups]\n"
        'dev = ["ruff", "tox"]\n'
        'tests = ["pytest>=7.0"]\n'
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["ruff"].ecosystem == "pip"
    assert by_name["tox"].version_spec is None
    assert by_name["pytest"].version_spec == ">=7.0"


def test_dependency_groups_include_group_reference_is_skipped_not_guessed(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[dependency-groups]\n"
        'dev = ["ruff"]\n'
        'combo = [{include-group = "dev"}, "black"]\n'
    )
    deps = _parse(tmp_path)
    names = {dep.name for dep in deps}
    assert names == {"ruff", "black"}


def test_dependency_groups_combine_with_project_dependencies(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'dependencies = ["fastapi>=0.115"]\n\n'
        "[dependency-groups]\n"
        'tests = ["pytest"]\n'
    )
    deps = _parse(tmp_path)
    names = {dep.name for dep in deps}
    assert names == {"fastapi", "pytest"}


def test_dependency_groups_same_name_not_duplicated_across_groups(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[dependency-groups]\n"
        'dev = ["pytest"]\n'
        'tests = ["pytest"]\n'
    )
    deps = _parse(tmp_path)
    assert len([d for d in deps if d.name == "pytest"]) == 1


# --- manifest_location precision for [project.dependencies] entries -----
# (a real, previously-unnoticed gap found while fixing the above: the
# bare package name is rarely a literal substring of its own source
# line once a version specifier is attached -- "fastapi" is not a
# substring of "fastapi>=0.115" -- so every such entry silently fell
# back to line 1 rather than pointing at its real line.)


def test_project_dependencies_location_points_at_the_correct_line(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        "dependencies = [\n"
        '    "fastapi>=0.115",\n'
        '    "pydantic>=2.9",\n'
        "]\n"
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["fastapi"].manifest_location.start_line == 3
    assert by_name["pydantic"].manifest_location.start_line == 4
