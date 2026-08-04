"""Deterministic Evidence Contract (ARCF v2.3 retrieval-context
stabilization patch, Change 2; extended by the repository debugging
routing fix's own Change 2).

Defines, per task_type, the fixed set of evidence categories that must be
collected before generation proceeds, and the glob patterns that identify
candidate files for each category. Matching is pure fnmatch against
RepositoryScanner's already-computed relative paths (the same matching
primitive workspace/permissions.py uses for sensitive-file detection) — no
model reasoning, no ranking, no confidence scoring.

Each category caps how many of its matches are kept (max_files) so a
pattern like "tests/**" matching hundreds of files can't blow up the
package on its own — Change 4's "compact, not the whole repository"
constraint is enforced here, at the source, not downstream.

REPOSITORY_DEBUGGING_EVIDENCE_CONTRACT is deliberately built the same way
as DOCUMENTATION_EVIDENCE_CONTRACT: one flat, ecosystem-spanning pattern
list per category, matched uniformly regardless of what language or test
framework the repository turns out to use. There is no per-framework
branch anywhere in this module (no "if playwright: ... elif pytest: ...")
— broad *coverage* across ecosystems (Maven/Gradle/npm/pnpm/yarn/pip/
poetry/cargo/go modules/.NET, JUnit/Cypress/Selenium/Robot Framework/
Playwright/Pytest) is achieved by listing each ecosystem's own
conventional filenames once, not by special-casing any of them in code.
"""

import fnmatch
from dataclasses import dataclass
from pathlib import PurePosixPath

from workspace.scanner import ScannedFile


@dataclass(frozen=True)
class EvidenceCategory:
    name: str
    patterns: tuple[str, ...]
    max_files: int = 5


DOCUMENTATION_EVIDENCE_CONTRACT: tuple[EvidenceCategory, ...] = (
    EvidenceCategory(
        name="dependency manifest",
        patterns=(
            "package.json",
            "requirements*.txt",
            "pyproject.toml",
            "setup.py",
            "Pipfile",
            "go.mod",
            "pom.xml",
            "build.gradle*",
        ),
        max_files=3,
    ),
    EvidenceCategory(
        name="test framework/configuration",
        patterns=(
            "playwright.config.*",
            "pytest.ini",
            "tox.ini",
            "jest.config.*",
            "vitest.config.*",
            "conftest.py",
            "phpunit.xml*",
            "karma.conf.*",
        ),
        max_files=3,
    ),
    EvidenceCategory(
        name="test directories",
        patterns=("tests/**", "test/**", "e2e/**", "__tests__/**", "spec/**"),
        max_files=8,
    ),
    EvidenceCategory(
        name="CI/workflow files",
        patterns=(
            ".github/workflows/*",
            ".gitlab-ci.yml",
            "azure-pipelines.yml",
            ".circleci/config.yml",
        ),
        max_files=3,
    ),
    EvidenceCategory(
        name="project structure",
        patterns=("README*", "src/**"),
        max_files=5,
    ),
)

REPOSITORY_DEBUGGING_EVIDENCE_CONTRACT: tuple[EvidenceCategory, ...] = (
    EvidenceCategory(
        name="project metadata",
        patterns=(
            "package.json",
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "requirements*.txt",
            "Pipfile",
            "poetry.lock",
            "Cargo.toml",
            "go.mod",
            "go.sum",
            "pom.xml",
            "build.gradle*",
            "settings.gradle*",
            "*.csproj",
            "*.sln",
            "*.fsproj",
            "Gemfile",
            "composer.json",
            "mix.exs",
            "pnpm-workspace.yaml",
            "lerna.json",
            "nx.json",
            "turbo.json",
        ),
        max_files=5,
    ),
    EvidenceCategory(
        name="build/workspace configuration",
        patterns=(
            "Makefile",
            "Dockerfile",
            "docker-compose*.yml",
            "tsconfig*.json",
            "webpack.config.*",
            "vite.config.*",
            "rollup.config.*",
            "babel.config.*",
            ".babelrc*",
            "Rakefile",
            "build.xml",
        ),
        max_files=5,
    ),
    EvidenceCategory(
        name="test framework/configuration",
        patterns=(
            "pytest.ini",
            "tox.ini",
            "conftest.py",
            "jest.config.*",
            "vitest.config.*",
            "karma.conf.*",
            "mocha.opts",
            ".mocharc*",
            "playwright.config.*",
            "cypress.config.*",
            "cypress.json",
            "phpunit.xml*",
            "*.robot",
            "testng.xml",
            "junit-platform.properties",
            "*.runsettings",
        ),
        max_files=5,
    ),
    EvidenceCategory(
        name="test directories",
        patterns=(
            "tests/**",
            "test/**",
            "__tests__/**",
            "spec/**",
            "e2e/**",
            "integration/**",
            "features/**",
            "cypress/**",
            "src/test/**",
            "src/tests/**",
        ),
        max_files=10,
    ),
    EvidenceCategory(
        name="test support layer",
        patterns=(
            "page_objects/**",
            "**/page_objects/**",
            "pages/**",
            "**/pages/**",
            "pageobjects/**",
            "**/pageobjects/**",
            "fixtures/**",
            "**/fixtures/**",
            "helpers/**",
            "**/helpers/**",
            "utils/**",
            "**/utils/**",
            "utilities/**",
            "**/utilities/**",
            "support/**",
            "**/support/**",
        ),
        max_files=5,
    ),
    EvidenceCategory(
        name="CI/workflow files",
        patterns=(
            ".github/workflows/*",
            ".gitlab-ci.yml",
            "azure-pipelines.yml",
            ".circleci/config.yml",
            "Jenkinsfile",
            "bitbucket-pipelines.yml",
        ),
        max_files=3,
    ),
    EvidenceCategory(
        name="project structure",
        patterns=("README*", "src/**", "lib/**", "app/**"),
        max_files=5,
    ),
)

_CONTRACTS_BY_TASK_TYPE: dict[str, tuple[EvidenceCategory, ...]] = {
    "repository_documentation": DOCUMENTATION_EVIDENCE_CONTRACT,
    "repository_debugging": REPOSITORY_DEBUGGING_EVIDENCE_CONTRACT,
}


def build_evidence_contract(task_type: str) -> tuple[EvidenceCategory, ...]:
    return _CONTRACTS_BY_TASK_TYPE.get(task_type, ())


def match_evidence(
    files: list[ScannedFile], contract: tuple[EvidenceCategory, ...]
) -> dict[str, list[str]]:
    """Returns {category_name: [relative_path, ...]}, each list capped at
    that category's max_files, in scanner order (already sorted,
    depth-first) so results are stable across runs."""
    matched: dict[str, list[str]] = {}
    for category in contract:
        hits: list[str] = []
        for file in files:
            if len(hits) >= category.max_files:
                break
            if _matches(file.relative_path, category.patterns):
                hits.append(file.relative_path)
        matched[category.name] = hits
    return matched


def _matches(relative_path: str, patterns: tuple[str, ...]) -> bool:
    basename = PurePosixPath(relative_path).name
    return any(
        fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(basename, pattern)
        for pattern in patterns
    )
