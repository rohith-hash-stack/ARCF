from pathlib import Path

from context.evidence_validator import prune_experimental_candidates, validate_sufficiency
from contracts.evidence_contract import AUTHENTICATION_EVIDENCE_CONTRACT
from domain.context_resolution import (
    ContextResolutionResult,
    DependencyEdge,
    EvidenceTier,
    FileReference,
    OriginStage,
    TokenEstimate,
)
from workspace.scanner import RepositoryScanner


def _write(tmp_path: Path, relative_path: str, content: str = "content\n") -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _result(
    repository_root: str,
    candidate_files: list[FileReference],
    dependency_chain: list[DependencyEdge] | None = None,
) -> ContextResolutionResult:
    return ContextResolutionResult(
        workspace_id="ws-1",
        contract_id="c-1",
        repository_root=repository_root,
        language="python",
        candidate_files=candidate_files,
        dependency_chain=dependency_chain or [],
        confidence=1.0,
        token_estimate=TokenEstimate(
            raw_context_tokens=100,
            selected_context_tokens=sum(f.token_count for f in candidate_files),
            compression_ratio=0.5,
        ),
        resolution_reason="test",
    )


def _ref(
    file_path: str,
    reason: str = "decorated by app.get",
    evidence_tier: EvidenceTier = EvidenceTier.EXPERIMENTAL,
    token_count: int = 10,
) -> FileReference:
    return FileReference(
        file_path=file_path,
        reason=reason,
        language="python",
        token_count=token_count,
        evidence_tier=evidence_tier,
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


def test_expanded_candidates_carry_origin_stage(tmp_path: Path) -> None:
    """Architecture closure (2026-08-17, G15): expansion-added
    FileReferences previously left origin_stage at its None default --
    the one reachable-on-the-default-path gap in OriginStage's own
    docstring claim. Now tagged EVIDENCE_FALLBACK_MATCH, same as
    evidence_fallback.py's own equivalent additions."""
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

    updated, _report = validate_sufficiency(
        result, AUTHENTICATION_EVIDENCE_CONTRACT, scan.files, tmp_path
    )

    added = next(f for f in updated.candidate_files if f.file_path == "auth/login.py")
    assert added.origin_stage == OriginStage.EVIDENCE_FALLBACK_MATCH


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


# -- prune_experimental_candidates (ARCF Phase 7 spike) ---------------------


def test_no_experimental_candidates_is_a_no_op() -> None:
    result = _result(
        "/repo",
        [_ref("primary.py", evidence_tier=EvidenceTier.PRIMARY)],
    )

    updated, report = prune_experimental_candidates(result, "any query")

    assert updated is result
    assert (report.proposed, report.kept, report.pruned) == (0, (), ())


def test_experimental_candidate_kept_via_same_directory_corroboration() -> None:
    result = _result(
        "/repo",
        [
            _ref("app/handlers.py", evidence_tier=EvidenceTier.PRIMARY),
            _ref("app/routes.py", reason="decorated by app.get"),
        ],
    )

    updated, report = prune_experimental_candidates(result, "unrelated query about nothing")

    file_paths = {f.file_path for f in updated.candidate_files}
    assert "app/routes.py" in file_paths
    assert report.kept == ("app/routes.py",)
    assert report.pruned == ()


def test_experimental_candidate_kept_via_dependency_chain_corroboration() -> None:
    result = _result(
        "/repo",
        [
            _ref("core/handlers.py", evidence_tier=EvidenceTier.PRIMARY),
            _ref("other/routes.py", reason="decorated by app.get"),
        ],
        dependency_chain=[DependencyEdge(from_file="core/handlers.py", to_file="other/routes.py")],
    )

    updated, report = prune_experimental_candidates(result, "unrelated query about nothing")

    file_paths = {f.file_path for f in updated.candidate_files}
    assert "other/routes.py" in file_paths
    assert report.pruned == ()


def test_experimental_candidate_kept_via_query_lexical_relevance() -> None:
    result = _result(
        "/repo",
        [
            _ref("core/handlers.py", evidence_tier=EvidenceTier.PRIMARY),
            _ref(
                "far/away/middleware.py",
                reason="decorated by app.middleware",
            ),
        ],
    )

    updated, report = prune_experimental_candidates(result, "Explain the middleware pipeline")

    file_paths = {f.file_path for f in updated.candidate_files}
    assert "far/away/middleware.py" in file_paths
    assert report.pruned == ()


def test_experimental_candidate_pruned_when_neither_corroborated_nor_relevant() -> None:
    result = _result(
        "/repo",
        [
            _ref("core/handlers.py", evidence_tier=EvidenceTier.PRIMARY),
            _ref("far/away/unrelated.py", reason="decorated by some.thing"),
        ],
    )

    updated, report = prune_experimental_candidates(result, "Explain the middleware pipeline")

    file_paths = {f.file_path for f in updated.candidate_files}
    assert "far/away/unrelated.py" not in file_paths
    assert "core/handlers.py" in file_paths
    assert report.pruned == ("far/away/unrelated.py",)
    assert report.proposed == 1


def test_non_experimental_candidates_are_never_touched() -> None:
    result = _result(
        "/repo",
        [
            _ref("core/primary.py", evidence_tier=EvidenceTier.PRIMARY),
            _ref("core/supporting.py", evidence_tier=EvidenceTier.SUPPORTING),
            _ref("far/away/stray.py", reason="decorated by nothing.relevant"),
        ],
    )

    updated, report = prune_experimental_candidates(result, "totally unrelated words here")

    file_paths = {f.file_path for f in updated.candidate_files}
    assert "core/primary.py" in file_paths
    assert "core/supporting.py" in file_paths
    assert "far/away/stray.py" not in file_paths
    assert report.proposed == 1


def test_survivors_beyond_max_are_capped_deterministically() -> None:
    # All corroborated (same directory as the established file) — the cap
    # must still bound how many survive, not just the corroboration check.
    candidates = [
        _ref(f"app/route_{i:02d}.py", reason=f"decorated by app.route{i}")
        for i in range(12)
    ]
    result = _result(
        "/repo",
        [_ref("app/main.py", evidence_tier=EvidenceTier.PRIMARY), *candidates],
    )

    updated, report = prune_experimental_candidates(result, "irrelevant query", max_survivors=3)

    experimental_kept = [
        f.file_path for f in updated.candidate_files if f.evidence_tier is EvidenceTier.EXPERIMENTAL
    ]
    assert len(experimental_kept) == 3
    assert experimental_kept == sorted(experimental_kept)  # deterministic: lowest paths win
    assert len(report.pruned) == 9
    assert report.proposed == 12


def test_pruning_updates_resolution_reason_and_token_estimate() -> None:
    result = _result(
        "/repo",
        [
            _ref("core/handlers.py", evidence_tier=EvidenceTier.PRIMARY, token_count=50),
            _ref("far/away/unrelated.py", reason="decorated by some.thing", token_count=20),
        ],
    )

    updated, _ = prune_experimental_candidates(result, "Explain the middleware pipeline")

    assert "LSE candidate pruning" in updated.resolution_reason
    assert updated.token_estimate.selected_context_tokens == 50
