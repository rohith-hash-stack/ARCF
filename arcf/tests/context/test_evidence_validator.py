from pathlib import Path

from context.evidence_validator import validate_sufficiency
from contracts.evidence_contract import AUTHENTICATION_EVIDENCE_CONTRACT
from domain.context_resolution import ContextResolutionResult, FileReference, TokenEstimate
from workspace.scanner import RepositoryScanner


def _write(tmp_path: Path, relative_path: str, content: str = "content\n") -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _result(repository_root: str, candidate_files: list[FileReference]) -> ContextResolutionResult:
    return ContextResolutionResult(
        workspace_id="ws-1",
        contract_id="c-1",
        repository_root=repository_root,
        language="python",
        candidate_files=candidate_files,
        confidence=1.0,
        token_estimate=TokenEstimate(
            raw_context_tokens=100,
            selected_context_tokens=sum(f.token_count for f in candidate_files),
            compression_ratio=0.5,
        ),
        resolution_reason="test",
    )


def test_empty_contract_is_a_no_op() -> None:
    result = _result("/repo", [])
    updated, report = validate_sufficiency(result, (), [], Path("/repo"))
    assert updated is result
    assert report.satisfied == ()
    assert report.missing == ()


def test_already_satisfied_categories_are_left_untouched(tmp_path: Path) -> None:
    # ".env" itself is a sensitive path (workspace/permissions.py) — it can
    # satisfy "credential source" as an already-present candidate (matched
    # by pattern, no re-read needed) without ever being re-read here.
    _write(tmp_path, ".env", "SECRET=1\n")
    _write(tmp_path, "auth/login.py", "def login():\n    pass\n")
    _write(tmp_path, "auth/session.py", "def make_session():\n    pass\n")
    _write(tmp_path, "auth/middleware.py", "def authenticate_request():\n    pass\n")
    _write(tmp_path, "config.py", "SETTING = 1\n")
    scan = RepositoryScanner().scan(tmp_path)

    result = _result(
        str(tmp_path),
        [
            FileReference(
                file_path=".env",
                reason="evidence: credential source",
                language="unknown",
                token_count=2,
            ),
            FileReference(
                file_path="auth/login.py", reason="defines login", language="python", token_count=5
            ),
            FileReference(
                file_path="auth/session.py",
                reason="defines make_session",
                language="python",
                token_count=5,
            ),
            FileReference(
                file_path="auth/middleware.py",
                reason="defines authenticate_request",
                language="python",
                token_count=5,
            ),
            FileReference(
                file_path="config.py",
                reason="evidence: configuration",
                language="python",
                token_count=3,
            ),
        ],
    )

    updated, report = validate_sufficiency(
        result, AUTHENTICATION_EVIDENCE_CONTRACT, scan.files, tmp_path
    )

    assert set(report.satisfied) == {
        "credential source",
        "login implementation",
        "session persistence",
        "authentication middleware",
        "configuration",
    }
    assert report.missing == ()
    assert updated.candidate_files == result.candidate_files


def test_expands_deterministically_for_missing_categories(tmp_path: Path) -> None:
    _write(tmp_path, "handler.py", "def handle():\n    pass\n")
    _write(tmp_path, "auth/login.py", "def login():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)

    result = _result(
        str(tmp_path),
        [
            FileReference(
                file_path="handler.py", reason="defines handle", language="python", token_count=5
            )
        ],
    )

    updated, report = validate_sufficiency(
        result, AUTHENTICATION_EVIDENCE_CONTRACT, scan.files, tmp_path
    )

    file_paths = {f.file_path for f in updated.candidate_files}
    assert "handler.py" in file_paths
    assert "auth/login.py" in file_paths
    assert "login implementation" in report.satisfied
    assert "session persistence" in report.missing
    assert "authentication middleware" in report.missing


def test_sensitive_credential_files_are_never_read_to_satisfy_a_category(tmp_path: Path) -> None:
    # A ".env" file exists but is NOT already a candidate — expansion must
    # not bypass PermissionManager's sensitive-file boundary to read it,
    # so "credential source" honestly stays missing rather than silently
    # smuggling secret content into the context package.
    _write(tmp_path, "handler.py", "def handle():\n    pass\n")
    _write(tmp_path, ".env", "SECRET=1\n")
    scan = RepositoryScanner().scan(tmp_path)
    result = _result(
        str(tmp_path),
        [
            FileReference(
                file_path="handler.py", reason="defines handle", language="python", token_count=5
            )
        ],
    )

    updated, report = validate_sufficiency(
        result, AUTHENTICATION_EVIDENCE_CONTRACT, scan.files, tmp_path
    )

    assert ".env" not in {f.file_path for f in updated.candidate_files}
    assert "credential source" in report.missing


def test_missing_category_with_no_matching_file_stays_honestly_missing(tmp_path: Path) -> None:
    _write(tmp_path, "handler.py", "def handle():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)
    result = _result(
        str(tmp_path),
        [
            FileReference(
                file_path="handler.py", reason="defines handle", language="python", token_count=5
            )
        ],
    )

    updated, report = validate_sufficiency(
        result, AUTHENTICATION_EVIDENCE_CONTRACT, scan.files, tmp_path
    )

    assert report.satisfied == ()
    assert set(report.missing) == {
        "credential source",
        "login implementation",
        "session persistence",
        "authentication middleware",
        "configuration",
    }
    assert updated.candidate_files == result.candidate_files
    assert updated.evidence_categories_missing == tuple(report.missing)


def test_expansion_stays_within_the_dominant_monorepo_segment(tmp_path: Path) -> None:
    # Two unrelated services, each with its own manifest and its own
    # login implementation. The already-resolved candidate lives in
    # services/api, so expansion must not pull in services/web/login.py.
    _write(tmp_path, "services/api/pyproject.toml", "[project]\nname='api'\n")
    _write(tmp_path, "services/api/handler.py", "def handle():\n    pass\n")
    _write(tmp_path, "services/api/login.py", "def login():\n    pass\n")
    _write(tmp_path, "services/web/package.json", "{}")
    _write(tmp_path, "services/web/login.py", "def login():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)

    result = _result(
        str(tmp_path),
        [
            FileReference(
                file_path="services/api/handler.py",
                reason="defines handle",
                language="python",
                token_count=5,
            )
        ],
    )

    updated, report = validate_sufficiency(
        result, AUTHENTICATION_EVIDENCE_CONTRACT, scan.files, tmp_path
    )

    file_paths = {f.file_path for f in updated.candidate_files}
    assert "services/api/login.py" in file_paths
    assert "services/web/login.py" not in file_paths
    assert "login implementation" in report.satisfied


def test_token_estimate_updated_after_expansion(tmp_path: Path) -> None:
    _write(tmp_path, "handler.py", "def handle():\n    pass\n")
    _write(tmp_path, "auth/login.py", "def login():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)
    result = _result(
        str(tmp_path),
        [
            FileReference(
                file_path="handler.py", reason="defines handle", language="python", token_count=5
            )
        ],
    )

    updated, _ = validate_sufficiency(
        result, AUTHENTICATION_EVIDENCE_CONTRACT, scan.files, tmp_path
    )

    assert (
        updated.token_estimate.selected_context_tokens
        > result.token_estimate.selected_context_tokens
    )
