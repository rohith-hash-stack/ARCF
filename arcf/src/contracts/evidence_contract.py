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

# ARCF architecture hardening §2 (evidence sufficiency validation): three
# more task-scoped contracts, keyed by context.task_profile.RetrievalTaskType
# values below (not imported here — evidence_contract.py stays a pure
# fnmatch/pattern module with no dependency on context/, matching its
# existing scope). Not imposed as a hard gate the way the two contracts
# above are (see repository_scope_classifier.py) — context/
# evidence_validator.py consults these for ANY task type that has one
# registered, regardless of repository_scope, and expands deterministically
# for whichever categories aren't already satisfied by the resolved
# candidate set.
AUTHENTICATION_EVIDENCE_CONTRACT: tuple[EvidenceCategory, ...] = (
    EvidenceCategory(
        name="credential source",
        patterns=(
            ".env*",
            "*.pem",
            "*credentials*",
            "*secrets*",
            "config/credentials*",
        ),
        max_files=3,
    ),
    EvidenceCategory(
        name="login implementation",
        patterns=("**/*login*", "**/*signin*", "**/*sign_in*"),
        max_files=5,
    ),
    EvidenceCategory(
        name="session persistence",
        patterns=("**/*session*", "**/*token*"),
        max_files=5,
    ),
    EvidenceCategory(
        name="authentication middleware",
        patterns=("**/*middleware*", "**/*auth*"),
        max_files=5,
    ),
    EvidenceCategory(
        name="configuration",
        patterns=("config*.py", "config/**", "settings*.py", "*.env*"),
        max_files=3,
    ),
)

TEST_EXECUTION_EVIDENCE_CONTRACT: tuple[EvidenceCategory, ...] = (
    EvidenceCategory(
        name="package/build manifest",
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
        name="test framework configuration",
        patterns=(
            "pytest.ini",
            "tox.ini",
            "conftest.py",
            "jest.config.*",
            "vitest.config.*",
            "playwright.config.*",
            "phpunit.xml*",
        ),
        max_files=3,
    ),
    EvidenceCategory(
        name="execution scripts",
        patterns=("Makefile", "scripts/**", "run_tests*", "*.sh"),
        max_files=5,
    ),
    EvidenceCategory(
        name="CI workflow",
        patterns=(
            ".github/workflows/*",
            ".gitlab-ci.yml",
            "azure-pipelines.yml",
            ".circleci/config.yml",
        ),
        max_files=3,
    ),
    EvidenceCategory(
        name="environment configuration",
        patterns=(".env*", "docker-compose*.yml", "*.cfg"),
        max_files=3,
    ),
)

CI_EXPLANATION_EVIDENCE_CONTRACT: tuple[EvidenceCategory, ...] = (
    EvidenceCategory(
        name="workflow definition",
        patterns=(
            ".github/workflows/*",
            ".gitlab-ci.yml",
            "azure-pipelines.yml",
            ".circleci/config.yml",
            "Jenkinsfile",
            "bitbucket-pipelines.yml",
        ),
        max_files=5,
    ),
    EvidenceCategory(
        name="build scripts",
        patterns=("Makefile", "build.gradle*", "webpack.config.*", "Dockerfile"),
        max_files=5,
    ),
    EvidenceCategory(
        name="dependency installation",
        patterns=(
            "package.json",
            "requirements*.txt",
            "pyproject.toml",
            "poetry.lock",
            "go.mod",
            "pom.xml",
        ),
        max_files=3,
    ),
    EvidenceCategory(
        name="environment variables",
        patterns=(".env*", "docker-compose*.yml"),
        max_files=3,
    ),
)

_CONTRACTS_BY_TASK_TYPE: dict[str, tuple[EvidenceCategory, ...]] = {
    "repository_documentation": DOCUMENTATION_EVIDENCE_CONTRACT,
    "repository_debugging": REPOSITORY_DEBUGGING_EVIDENCE_CONTRACT,
    "authentication": AUTHENTICATION_EVIDENCE_CONTRACT,
    "test_execution": TEST_EXECUTION_EVIDENCE_CONTRACT,
    "ci_explanation": CI_EXPLANATION_EVIDENCE_CONTRACT,
}


def build_evidence_contract(task_type: str) -> tuple[EvidenceCategory, ...]:
    return _CONTRACTS_BY_TASK_TYPE.get(task_type, ())


_AUTHENTICATION_WORDS: tuple[str, ...] = (
    "authentication",
    "auth",
    "login",
    "log in",
    "session",
    "credential",
    "password",
)
_TEST_EXECUTION_WORDS: tuple[str, ...] = (
    "test execution",
    "run the tests",
    "run tests",
    "test suite",
    "how to test",
    "how do i test",
    "how do we run",
)
_CI_EXPLANATION_WORDS: tuple[str, ...] = (
    "ci/cd",
    "ci pipeline",
    "build pipeline",
    "github actions",
    "continuous integration",
    "continuous deployment",
    "deployment pipeline",
)


def detect_task_type_for_evidence(raw_request: str) -> str | None:
    """Deterministic keyword detection selecting which of the three
    ARCF-hardening evidence contracts (authentication/test_execution/
    ci_explanation) applies to `raw_request`, independent of
    RepositoryScopeClassifier's own two categories. Same keyword-
    substring idiom, checked most-specific-first (CI before test
    execution before authentication, since "test the CI pipeline" reads
    as a CI question first)."""
    text_lower = raw_request.lower()
    if any(word in text_lower for word in _CI_EXPLANATION_WORDS):
        return "ci_explanation"
    if any(word in text_lower for word in _TEST_EXECUTION_WORDS):
        return "test_execution"
    if any(word in text_lower for word in _AUTHENTICATION_WORDS):
        return "authentication"
    return None


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


def category_matches(relative_path: str, category: EvidenceCategory) -> bool:
    """Public single-file check against one category's patterns — used by
    context/evidence_validator.py (ARCF hardening §2) to test whether an
    already-resolved candidate file happens to satisfy a required evidence
    category, without needing a full ScannedFile list."""
    return _matches(relative_path, category.patterns)


def _matches(relative_path: str, patterns: tuple[str, ...]) -> bool:
    basename = PurePosixPath(relative_path).name
    return any(
        fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(basename, pattern)
        for pattern in patterns
    )
