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


# --- Poetry's native [tool.poetry.group.*.dependencies], found missing --
# by the second round of real-repo validation (arcf-di/PROGRESS.md's
# "stability sweep" entry: python-poetry/poetry itself declares almost
# all of its own dev/test/typing dependencies this way, not via the
# classic [tool.poetry.dependencies] table -- distinct from both that
# table and PEP 735's [dependency-groups], and unread by either.)


def test_parses_poetry_group_dependencies(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry.group.dev.dependencies]\n"
        'pytest = "^7.0"\n'
        'mypy = { version = "^1.0" }\n'
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["pytest"].ecosystem == "pip"
    assert by_name["pytest"].version_spec == "^7.0"
    assert by_name["mypy"].version_spec == "^1.0"


def test_poetry_group_dependencies_combine_across_multiple_groups(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry.group.dev.dependencies]\n"
        'pytest = "^7.0"\n\n'
        "[tool.poetry.group.typing.dependencies]\n"
        'mypy = "^1.0"\n'
    )
    deps = _parse(tmp_path)
    names = {dep.name for dep in deps}
    assert names == {"pytest", "mypy"}


def test_poetry_group_dependency_not_duplicated_when_also_in_classic_table(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry.dependencies]\n"
        'requests = "^2.28.0"\n\n'
        "[tool.poetry.group.dev.dependencies]\n"
        'requests = "^2.28.0"\n'
    )
    deps = _parse(tmp_path)
    assert len([d for d in deps if d.name == "requests"]) == 1


def test_poetry_dependency_location_points_at_its_own_line_not_line_one(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry.dependencies]\n"
        'python = "^3.11"\n'
        'requests = "^2.28.0"\n'
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["requests"].manifest_location.start_line == 3


# --- setup.cfg / setup.py, found missing by the same stability sweep ----
# (httpie/httpie has no pyproject.toml at all -- only setup.py (empty,
# all metadata declared via setuptools' declarative setup.cfg) and
# setup.cfg's [options] install_requires -- so every real external
# import in the repo was UNRESOLVED, not because the classifier is
# wrong but because no parser read either file at all.)


def test_parses_setup_cfg_install_requires(tmp_path: Path) -> None:
    (tmp_path / "setup.cfg").write_text(
        "[options]\n"
        "install_requires =\n"
        "    requests>=2.22.0\n"
        "    charset_normalizer>=2.0.0\n"
        "    six\n"
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["requests"].ecosystem == "pip"
    assert by_name["requests"].version_spec == ">=2.22.0"
    assert by_name["six"].version_spec is None


def test_parses_setup_cfg_extras_require(tmp_path: Path) -> None:
    (tmp_path / "setup.cfg").write_text(
        "[options]\n"
        "install_requires =\n"
        "    requests\n\n"
        "[options.extras_require]\n"
        "dev =\n"
        "    pytest\n"
        "    flake8\n"
    )
    deps = _parse(tmp_path)
    names = {dep.name for dep in deps}
    assert names == {"requests", "pytest", "flake8"}


def test_setup_cfg_location_points_at_its_own_line(tmp_path: Path) -> None:
    (tmp_path / "setup.cfg").write_text(
        "[options]\ninstall_requires =\n    requests>=2.22.0\n    six\n"
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["six"].manifest_location.start_line == 4


def test_setup_cfg_with_no_install_requires_yields_no_dependencies(tmp_path: Path) -> None:
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = example\n")
    assert _parse(tmp_path) == []


def test_parses_setup_py_literal_install_requires_and_extras_require(tmp_path: Path) -> None:
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n\n"
        "setup(\n"
        "    name='example',\n"
        "    install_requires=['requests>=2.22.0', 'six'],\n"
        "    extras_require={'dev': ['pytest', 'flake8']},\n"
        ")\n"
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["requests"].ecosystem == "pip"
    assert by_name["requests"].version_spec == ">=2.22.0"
    assert by_name["six"].version_spec is None
    assert {"pytest", "flake8"} <= set(by_name)


def test_setup_py_skips_non_literal_install_requires_rather_than_guessing(
    tmp_path: Path,
) -> None:
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n\n"
        "with open('requirements.txt') as f:\n"
        "    requires = f.read().splitlines()\n\n"
        "setup(name='example', install_requires=requires)\n"
    )
    assert _parse(tmp_path) == []


def test_setup_py_empty_call_yields_no_dependencies(tmp_path: Path) -> None:
    # Real httpie/httpie shape: all metadata declared via setup.cfg,
    # setup.py itself is just `setup()` with no keyword arguments at all.
    (tmp_path / "setup.py").write_text("from setuptools import setup\n\nsetup()\n")
    assert _parse(tmp_path) == []


def test_setup_py_location_uses_the_actual_ast_line_number(tmp_path: Path) -> None:
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n\n"
        "setup(\n"
        "    name='example',\n"
        "    install_requires=[\n"
        "        'requests>=2.22.0',\n"
        "        'six',\n"
        "    ],\n"
        ")\n"
    )
    deps = _parse(tmp_path)
    by_name = {dep.name: dep for dep in deps}
    assert by_name["requests"].manifest_location.start_line == 6
    assert by_name["six"].manifest_location.start_line == 7
