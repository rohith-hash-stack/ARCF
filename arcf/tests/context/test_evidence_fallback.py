from pathlib import Path

from context.evidence_fallback import build_repository_summary, expand_with_evidence
from domain.context_package import PackagedFile
from domain.context_resolution import ContextResolutionResult, FileReference, TokenEstimate
from workspace.scanner import RepositoryScanner


def _empty_result(repository_root: str) -> ContextResolutionResult:
    return ContextResolutionResult(
        workspace_id="ws-1",
        contract_id="c-1",
        repository_root=repository_root,
        language="unknown",
        confidence=0.0,
        token_estimate=TokenEstimate(
            raw_context_tokens=0, selected_context_tokens=0, compression_ratio=0.0
        ),
        resolution_reason="No target names provided; nothing to resolve.",
    )


def _write(tmp_path: Path, relative_path: str, content: str = "content\n") -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_leaves_non_empty_resolution_untouched(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", "{}")
    result = _empty_result(str(tmp_path)).model_copy(
        update={
            "candidate_files": [
                FileReference(
                    file_path="auth.py",
                    reason="defines authenticate",
                    language="python",
                    token_count=5,
                )
            ]
        }
    )
    scan = RepositoryScanner().scan(tmp_path)

    expanded = expand_with_evidence(result, scan.files, tmp_path, "repository_documentation")

    assert expanded is result


def test_falls_back_to_evidence_contract_when_empty(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", '{"name": "demo"}')
    _write(tmp_path, "playwright.config.ts", "export default {};\n")
    _write(tmp_path, "tests/e2e/login.spec.ts", "test('login', () => {});\n")
    _write(tmp_path, ".github/workflows/regression.yml", "name: regression\n")
    _write(tmp_path, "README.md", "# Demo\n")
    scan = RepositoryScanner().scan(tmp_path)

    expanded = expand_with_evidence(
        _empty_result(str(tmp_path)), scan.files, tmp_path, "repository_documentation"
    )

    assert len(expanded.candidate_files) > 0
    file_paths = {ref.file_path for ref in expanded.candidate_files}
    assert "package.json" in file_paths
    assert "playwright.config.ts" in file_paths
    assert "tests/e2e/login.spec.ts" in file_paths
    assert ".github/workflows/regression.yml" in file_paths
    assert "README.md" in file_paths
    assert all(ref.reason.startswith("evidence: ") for ref in expanded.candidate_files)
    assert all(ref.token_count > 0 for ref in expanded.candidate_files)
    assert "Retrieval retry" in expanded.resolution_reason


def test_falls_back_to_root_level_files_when_evidence_contract_matches_nothing(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "notes.txt", "just some notes\n")
    _write(tmp_path, "config.cfg", "[section]\n")
    scan = RepositoryScanner().scan(tmp_path)

    expanded = expand_with_evidence(
        _empty_result(str(tmp_path)), scan.files, tmp_path, "repository_documentation"
    )

    assert len(expanded.candidate_files) > 0
    assert all(ref.reason == "evidence: repository tree" for ref in expanded.candidate_files)


def test_unrecognized_task_type_still_falls_back_to_root_level(tmp_path: Path) -> None:
    """expand_with_evidence trusts its caller (code_intelligence/service.py
    only invokes it when RepositoryScopeClassifier already said
    repository_scope=True) — it does not itself re-validate task_type, so
    an unrecognized one (no matching evidence contract) still reaches the
    root-level fallback tier rather than silently doing nothing."""
    _write(tmp_path, "package.json", "{}")
    scan = RepositoryScanner().scan(tmp_path)
    result = _empty_result(str(tmp_path))

    expanded = expand_with_evidence(result, scan.files, tmp_path, "unscoped")

    assert len(expanded.candidate_files) > 0
    assert expanded.candidate_files[0].reason == "evidence: repository tree"


def test_build_repository_summary_lists_evidence_categories() -> None:
    files = [
        PackagedFile(
            file_path="package.json",
            content="{}",
            relevance_score=0.3,
            reason="evidence: dependency manifest",
            token_count=5,
            truncated=False,
        ),
        PackagedFile(
            file_path="tests/e2e/login.spec.ts",
            content="test",
            relevance_score=0.3,
            reason="evidence: test directories",
            token_count=5,
            truncated=False,
        ),
        PackagedFile(
            file_path="auth.py",
            content="def authenticate(): ...",
            relevance_score=1.0,
            reason="defines authenticate",
            token_count=5,
            truncated=False,
        ),
    ]

    summary = build_repository_summary(files)

    assert summary.startswith("Repository summary:")
    assert "- dependency manifest: package.json" in summary
    assert "- test directories: tests/e2e/login.spec.ts" in summary
    assert "auth.py" not in summary


def test_repository_debugging_falls_back_to_its_own_evidence_contract(tmp_path: Path) -> None:
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    _write(tmp_path, "tests/test_login.py", "def test_login():\n    assert True\n")
    _write(tmp_path, "utils/test_helpers.py", "def make_user():\n    ...\n")
    _write(tmp_path, ".github/workflows/ci.yml", "name: ci\n")
    scan = RepositoryScanner().scan(tmp_path)

    expanded = expand_with_evidence(
        _empty_result(str(tmp_path)), scan.files, tmp_path, "repository_debugging"
    )

    file_paths = {ref.file_path for ref in expanded.candidate_files}
    assert "pytest.ini" in file_paths
    assert "tests/test_login.py" in file_paths
    assert "utils/test_helpers.py" in file_paths
    assert "detected" not in expanded.resolution_reason  # sanity: no stray placeholder text


def test_query_referenced_file_is_prioritized_and_tagged(tmp_path: Path) -> None:
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    _write(tmp_path, "tests/test_login.py", "def test_login():\n    assert True\n")
    _write(tmp_path, "src/auth/login.py", "def login():\n    ...\n")
    scan = RepositoryScanner().scan(tmp_path)

    expanded = expand_with_evidence(
        _empty_result(str(tmp_path)),
        scan.files,
        tmp_path,
        "repository_debugging",
        raw_request="I'm seeing a failing test in `test_login.py`, please diagnose it",
    )

    file_paths = {ref.file_path for ref in expanded.candidate_files}
    assert "tests/test_login.py" in file_paths
    referenced = next(
        ref for ref in expanded.candidate_files if ref.file_path == "tests/test_login.py"
    )
    assert referenced.reason == "references: query-referenced"
    # baseline evidence-contract categories are still present alongside it
    assert "pytest.ini" in file_paths
    assert "query-referenced" in expanded.resolution_reason


def test_query_referenced_file_alone_does_not_suppress_evidence_contract(tmp_path: Path) -> None:
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    _write(tmp_path, "src/widgets/checkout.py", "def checkout():\n    ...\n")
    scan = RepositoryScanner().scan(tmp_path)

    expanded = expand_with_evidence(
        _empty_result(str(tmp_path)),
        scan.files,
        tmp_path,
        "repository_debugging",
        raw_request="Diagnose the failure in checkout.py",
    )

    file_paths = {ref.file_path for ref in expanded.candidate_files}
    assert "src/widgets/checkout.py" in file_paths
    assert "pytest.ini" in file_paths


def test_expansion_sets_dominant_language_from_matched_files(tmp_path: Path) -> None:
    _write(tmp_path, "requirements.txt", "flask\n")
    _write(tmp_path, "tests/test_api.py", "def test_api():\n    assert True\n")
    _write(tmp_path, "tests/test_more.py", "def test_more():\n    assert True\n")
    scan = RepositoryScanner().scan(tmp_path)

    expanded = expand_with_evidence(
        _empty_result(str(tmp_path)), scan.files, tmp_path, "repository_debugging"
    )

    assert expanded.language == "python"


def test_no_match_at_all_returns_result_unchanged(tmp_path: Path) -> None:
    result = _empty_result(str(tmp_path))
    expanded = expand_with_evidence(result, [], tmp_path, "repository_debugging")
    assert expanded is result


def test_build_repository_summary_includes_query_referenced_files() -> None:
    files = [
        PackagedFile(
            file_path="tests/test_login.py",
            content="def test_login(): ...",
            relevance_score=0.8,
            reason="references: query-referenced",
            token_count=5,
            truncated=False,
        ),
        PackagedFile(
            file_path="pytest.ini",
            content="[pytest]",
            relevance_score=0.3,
            reason="evidence: test framework/configuration",
            token_count=5,
            truncated=False,
        ),
    ]

    summary = build_repository_summary(files)

    assert "- query-referenced: tests/test_login.py" in summary
    assert "- test framework/configuration: pytest.ini" in summary


def test_build_repository_summary_empty_when_no_evidence_files() -> None:
    files = [
        PackagedFile(
            file_path="auth.py",
            content="def authenticate(): ...",
            relevance_score=1.0,
            reason="defines authenticate",
            token_count=5,
            truncated=False,
        )
    ]
    assert build_repository_summary(files) == ""
