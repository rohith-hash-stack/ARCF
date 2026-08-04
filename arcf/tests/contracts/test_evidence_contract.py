from contracts.evidence_contract import build_evidence_contract, match_evidence
from workspace.scanner import ScannedFile


def _files(*relative_paths: str) -> list[ScannedFile]:
    return [ScannedFile(relative_path=p, extension="", size_bytes=1) for p in relative_paths]


def test_build_evidence_contract_returns_documentation_categories() -> None:
    contract = build_evidence_contract("repository_documentation")
    names = [category.name for category in contract]
    assert names == [
        "dependency manifest",
        "test framework/configuration",
        "test directories",
        "CI/workflow files",
        "project structure",
    ]


def test_build_evidence_contract_returns_empty_for_unknown_task_type() -> None:
    assert build_evidence_contract("bug_fix") == ()


def test_match_evidence_matches_each_category() -> None:
    contract = build_evidence_contract("repository_documentation")
    files = _files(
        "package.json",
        "playwright.config.ts",
        "tests/e2e/login.spec.ts",
        ".github/workflows/regression.yml",
        "README.md",
        "src/index.ts",
        "node_modules/some_dep/index.js",
    )
    matched = match_evidence(files, contract)

    assert matched["dependency manifest"] == ["package.json"]
    assert matched["test framework/configuration"] == ["playwright.config.ts"]
    assert matched["test directories"] == ["tests/e2e/login.spec.ts"]
    assert matched["CI/workflow files"] == [".github/workflows/regression.yml"]
    assert matched["project structure"] == ["README.md", "src/index.ts"]


def test_match_evidence_caps_hits_at_category_max_files() -> None:
    contract = build_evidence_contract("repository_documentation")
    test_files = _files(*(f"tests/test_{i}.py" for i in range(20)))
    matched = match_evidence(test_files, contract)
    assert len(matched["test directories"]) == 8


def test_match_evidence_returns_empty_lists_when_nothing_matches() -> None:
    contract = build_evidence_contract("repository_documentation")
    matched = match_evidence(_files("unrelated/binary.dat"), contract)
    assert all(hits == [] for hits in matched.values())


def test_build_debugging_contract_returns_expected_categories() -> None:
    contract = build_evidence_contract("repository_debugging")
    names = [category.name for category in contract]
    assert names == [
        "project metadata",
        "build/workspace configuration",
        "test framework/configuration",
        "test directories",
        "test support layer",
        "CI/workflow files",
        "project structure",
    ]


def test_debugging_contract_matches_across_ecosystems_without_branching() -> None:
    """One flat pattern match, run once, across a repository that mixes
    conventions from several ecosystems at once — proving there is no
    per-framework branch deciding which patterns even get checked."""
    contract = build_evidence_contract("repository_debugging")
    files = _files(
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "MyApp.csproj",
        "package.json",
        "pytest.ini",
        "cypress.config.ts",
        "e2e/login.cy.ts",
        "tests/test_api.py",
        "src/test/java/AppTest.java",
        "e2e/pages/LoginPage.ts",
        "utils/test_helpers.py",
        ".github/workflows/ci.yml",
        "Jenkinsfile",
        "README.md",
    )
    matched = match_evidence(files, contract)

    assert set(matched["project metadata"]) == {
        "Cargo.toml", "go.mod", "pom.xml", "MyApp.csproj", "package.json",
    }
    assert "pytest.ini" in matched["test framework/configuration"]
    assert "cypress.config.ts" in matched["test framework/configuration"]
    assert "e2e/login.cy.ts" in matched["test directories"]
    assert "tests/test_api.py" in matched["test directories"]
    assert "src/test/java/AppTest.java" in matched["test directories"]
    assert "e2e/pages/LoginPage.ts" in matched["test support layer"]
    assert "utils/test_helpers.py" in matched["test support layer"]
    assert matched["CI/workflow files"] == [".github/workflows/ci.yml", "Jenkinsfile"]
    assert "README.md" in matched["project structure"]


def test_debugging_contract_caps_hits_at_category_max_files() -> None:
    contract = build_evidence_contract("repository_debugging")
    test_files = _files(*(f"tests/test_{i}.py" for i in range(20)))
    matched = match_evidence(test_files, contract)
    assert len(matched["test directories"]) == 10
