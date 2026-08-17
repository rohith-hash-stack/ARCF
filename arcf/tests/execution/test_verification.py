from uuid import uuid4

from domain.artifact import Artifact
from domain.context_package import ContextPackage, PackagedFile
from domain.context_resolution import ContextResolutionResult, TokenEstimate
from domain.enums import ArtifactKind
from domain.verification_result import GroundingVerificationStatus
from execution.verification import verify_grounding


def _resolution(evidence_categories_missing: tuple[str, ...] = ()) -> ContextResolutionResult:
    return ContextResolutionResult(
        workspace_id="workspace-1",
        contract_id="contract-1",
        repository_root="/repo",
        language="python",
        confidence=0.9,
        token_estimate=TokenEstimate(
            raw_context_tokens=50, selected_context_tokens=50, compression_ratio=1.0
        ),
        resolution_reason="defines authenticate",
        evidence_categories_missing=evidence_categories_missing,
    )


def _package(files: list[PackagedFile] | None = None) -> ContextPackage:
    return ContextPackage(
        contract_id="contract-1",
        workspace_id="workspace-1",
        context_resolution_id=uuid4(),
        relevant_files=files
        if files is not None
        else [
            PackagedFile(
                file_path="auth/service.py",
                content="class AuthService: ...",
                relevance_score=1.0,
                reason="defines authenticate",
                token_count=50,
                truncated=False,
            )
        ],
        budget_max_tokens=1000,
        budget_used_tokens=50,
        prompt_compression_ratio=1.0,
        excluded_file_count=0,
    )


def _artifact(content: str) -> Artifact:
    return Artifact(kind=ArtifactKind.CODE_CHANGE, content=content)


def test_sufficient_when_evidence_complete_and_references_match_packaged_files() -> None:
    result = verify_grounding(
        _artifact("Modified `auth/service.py` to add a retry."), _package(), _resolution()
    )

    assert result.status is GroundingVerificationStatus.SUFFICIENT
    assert result.evidence_sufficient is True
    assert result.recovery_eligible is False
    assert result.contradictions_checked is False


def test_insufficient_evidence_takes_priority_and_is_recovery_eligible() -> None:
    result = verify_grounding(
        _artifact("Modified `auth/service.py`."),
        _package(),
        _resolution(evidence_categories_missing=("test framework/configuration",)),
    )

    assert result.status is GroundingVerificationStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence_sufficient is False
    assert result.missing_evidence_categories == ("test framework/configuration",)
    assert result.recovery_eligible is True


def test_unsupported_reference_detected_when_file_never_retrieved() -> None:
    result = verify_grounding(
        _artifact("Modified `auth/service.py` and also `payments/gateway.py`."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.UNSUPPORTED_REFERENCES
    assert result.evidence_sufficient is True
    assert result.unsupported_file_references == ("payments/gateway.py",)
    assert result.recovery_eligible is True


def test_git_diff_path_prefix_is_tolerated_not_flagged_unsupported() -> None:
    result = verify_grounding(
        _artifact("--- a/auth/service.py\n+++ b/auth/service.py\n@@ -1,2 +1,3 @@\n"),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.SUFFICIENT
    assert result.unsupported_file_references == ()


def test_prose_with_no_file_paths_is_sufficient_when_evidence_complete() -> None:
    result = verify_grounding(
        _artifact("This bug is caused by a missing null check in the login flow."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.SUFFICIENT
    assert result.unsupported_file_references == ()


def test_windows_backslash_path_reference_is_extracted_and_checked() -> None:
    """2026-08-17 hardening: the original regex only recognized "/"
    separators, so a fabricated Windows-style path was invisible to
    verification (a real false negative on this project's own dev OS)."""
    result = verify_grounding(
        _artifact(r"Modified src\payments\gateway.py to add retry logic."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.UNSUPPORTED_REFERENCES
    assert result.unsupported_file_references == (r"src\payments\gateway.py",)


def test_windows_backslash_reference_to_a_real_packaged_file_is_supported() -> None:
    result = verify_grounding(
        _artifact(r"Modified auth\service.py to add a null check."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.SUFFICIENT


def test_case_insensitive_reference_to_a_real_packaged_file_is_not_flagged() -> None:
    """2026-08-17 hardening: a differently-cased reference to a real
    packaged file was previously flagged as unsupported (a false
    positive that would waste a real recovery attempt)."""
    result = verify_grounding(
        _artifact("Modified `Auth/Service.py` to add a null check."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.SUFFICIENT


def test_bare_filename_with_known_extension_is_checked_against_packaged_files() -> None:
    result = verify_grounding(
        _artifact("Modified `service.py` and also `gateway.py`."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.UNSUPPORTED_REFERENCES
    assert "gateway.py" in result.unsupported_file_references
    assert "service.py" not in result.unsupported_file_references


def test_extensionless_conventional_filename_with_directory_prefix_is_checked() -> None:
    result = verify_grounding(
        _artifact("Updated `deploy/Dockerfile` to add a build stage."),
        _package(
            [
                PackagedFile(
                    file_path="deploy/Dockerfile",
                    content="FROM python:3.13",
                    relevance_score=1.0,
                    reason="matches deploy config",
                    token_count=10,
                    truncated=False,
                )
            ]
        ),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.SUFFICIENT


def test_absolute_unix_path_to_fabricated_file_is_recognized_and_unsupported() -> None:
    """2026-08-17, second hardening pass (independent verification
    report G-new-2): the original extraction regexes' negative
    lookbehind made every absolute path structurally invisible, so a
    fabricated absolute-path reference passed as SUFFICIENT purely
    because it was never extracted -- not because matching said it was
    supported. This is the exact bug class the report empirically
    reproduced."""
    result = verify_grounding(
        _artifact("The real logic lives in /etc/fabricated_nonexistent.py."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.UNSUPPORTED_REFERENCES
    assert result.unsupported_file_references == ("/etc/fabricated_nonexistent.py",)


def test_absolute_unix_path_prefixing_a_real_packaged_file_is_supported() -> None:
    """A repository-root-prefixed absolute reference to a file that
    really was packaged must not be flagged -- only a genuinely
    unsupported absolute reference should trigger recovery."""
    result = verify_grounding(
        _artifact("Modified `/workspace/repo/auth/service.py` to add a null check."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.SUFFICIENT
    assert result.unsupported_file_references == ()


def test_absolute_windows_drive_path_to_fabricated_file_is_recognized_and_unsupported() -> None:
    result = verify_grounding(
        _artifact(r"See C:\etc\fabricated_nonexistent.py for the implementation."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.UNSUPPORTED_REFERENCES
    assert result.unsupported_file_references == (r"C:\etc\fabricated_nonexistent.py",)


def test_absolute_windows_drive_path_prefixing_a_real_packaged_file_is_supported() -> None:
    result = verify_grounding(
        _artifact(r"Modified `C:\workspace\repo\auth\service.py` to add a null check."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.SUFFICIENT


def test_absolute_path_with_no_intermediate_directory_segment_is_extracted() -> None:
    """Root anchor immediately followed by a filename ("/foo.py") is
    still a legitimate absolute reference, not just root+dir+file."""
    result = verify_grounding(
        _artifact("The entry point is /nonexistent.py"),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.UNSUPPORTED_REFERENCES
    assert result.unsupported_file_references == ("/nonexistent.py",)


def test_absolute_extensionless_conventional_filename_is_recognized() -> None:
    result = verify_grounding(
        _artifact("Updated `/etc/Dockerfile` to add a build stage."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.UNSUPPORTED_REFERENCES
    assert result.unsupported_file_references == ("/etc/Dockerfile",)


def test_absolute_extensionless_conventional_filename_to_real_packaged_file_is_supported() -> None:
    result = verify_grounding(
        _artifact("Updated `/workspace/repo/deploy/Dockerfile` to add a build stage."),
        _package(
            [
                PackagedFile(
                    file_path="deploy/Dockerfile",
                    content="FROM python:3.13",
                    relevance_score=1.0,
                    reason="matches deploy config",
                    token_count=10,
                    truncated=False,
                )
            ]
        ),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.SUFFICIENT


def test_malformed_absolute_looking_text_is_not_extracted_and_does_not_crash() -> None:
    """Documented limitation, not a regression: text shaped like a
    stray root anchor with no real path following it is simply never
    extracted (same tolerant posture as every other unrecognized-shape
    case in this module), never an exception."""
    result = verify_grounding(
        _artifact("The ratio is 3/4 and the path separator is just / by itself."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.SUFFICIENT
    assert result.unsupported_file_references == ()


def test_relative_path_reference_still_regression_free_after_absolute_path_fix() -> None:
    """G17 regression guard: adding absolute-path patterns must not
    change relative-path extraction/matching behavior at all."""
    result = verify_grounding(
        _artifact("Modified `auth/service.py` and also `payments/gateway.py`."),
        _package(),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.UNSUPPORTED_REFERENCES
    assert result.unsupported_file_references == ("payments/gateway.py",)


def test_suffix_match_does_not_cross_a_path_segment_boundary() -> None:
    """2026-08-17 hardening: a real bug let a fabricated reference to
    "utils.py" incorrectly match an unrelated real packaged file
    "database_utils.py", because the old matcher used bare
    str.endswith with no path-segment boundary check."""
    result = verify_grounding(
        _artifact("Modified `utils.py` to add a helper."),
        _package(
            [
                PackagedFile(
                    file_path="database_utils.py",
                    content="def helper(): ...",
                    relevance_score=1.0,
                    reason="defines helper",
                    token_count=10,
                    truncated=False,
                )
            ]
        ),
        _resolution(),
    )

    assert result.status is GroundingVerificationStatus.UNSUPPORTED_REFERENCES
    assert "utils.py" in result.unsupported_file_references
