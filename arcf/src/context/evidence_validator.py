"""EvidenceValidator (ARCF architecture hardening §2) — deterministic
evidence-sufficiency validation.

Distinct from context/evidence_fallback.py, which only fires when
ContextResolver's candidate_files came back completely empty:
`validate_sufficiency` runs whenever a task type has a registered
evidence contract (contracts/evidence_contract.py) and checks whether
the ALREADY-resolved candidate set — however it was assembled, symbol-
based or otherwise — covers each required evidence category. Categories
already covered by a graph-driven candidate are left untouched;
categories with no coverage are expanded via the same deterministic
glob-matching primitive evidence_fallback.py already uses
(`contracts.evidence_contract.match_evidence`), never an LLM call.

The final LLM should never receive an incomplete evidence package when
deterministic expansion can close the gap — but a category that
genuinely has no matching file in the repository (e.g. no CI workflow
exists at all) stays honestly reported as missing rather than
fabricated.
"""

from dataclasses import dataclass
from pathlib import Path

from contracts.evidence_contract import EvidenceCategory, category_matches, match_evidence
from domain.context_resolution import ContextResolutionResult, FileReference
from infrastructure.cost import CostEstimator
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager
from workspace.repository_segmentation import ROOT_SEGMENT, RepositorySegmenter
from workspace.scanner import ScannedFile

_TOKEN_ESTIMATE_MODEL = "gpt-4o-mini"
_READ_ERRORS: tuple[type[Exception], ...] = (OSError, WorkspacePathError)


@dataclass(frozen=True)
class EvidenceSufficiencyReport:
    satisfied: tuple[str, ...]
    missing: tuple[str, ...]


def validate_sufficiency(
    result: ContextResolutionResult,
    contract: tuple[EvidenceCategory, ...],
    files: list[ScannedFile],
    workspace_root: Path,
) -> tuple[ContextResolutionResult, EvidenceSufficiencyReport]:
    """Returns `result` (expanded if needed) plus a report of which
    evidence categories ended up satisfied vs. still missing. A no-op
    (returns `result` unchanged except for the two metadata fields) when
    `contract` is empty — most task types have no registered contract."""
    if not contract:
        return result, EvidenceSufficiencyReport(satisfied=(), missing=())

    existing_paths = [ref.file_path for ref in result.candidate_files]
    already_satisfied = [
        category.name
        for category in contract
        if any(category_matches(path, category) for path in existing_paths)
    ]
    missing_categories = [
        category for category in contract if category.name not in already_satisfied
    ]

    if not missing_categories:
        return (
            result.model_copy(
                update={
                    "evidence_categories_satisfied": tuple(already_satisfied),
                    "evidence_categories_missing": (),
                }
            ),
            EvidenceSufficiencyReport(satisfied=tuple(already_satisfied), missing=()),
        )

    permissions = PermissionManager(workspace_root)
    token_estimator = CostEstimator()

    # ARCF hardening §4 (repository boundary awareness): when the query
    # already has established candidates, scope expansion to the segment
    # they're dominantly in — a monorepo bug-fix in services/api shouldn't
    # pull in services/web's unrelated CI config. No established
    # candidates yet means no segment to scope by, so the full file list
    # is used unfiltered (same as before segmentation existed).
    segmenter = RepositorySegmenter(files)
    dominant_segment = segmenter.dominant_segment(existing_paths)
    if dominant_segment == ROOT_SEGMENT:
        scoped_files = files
    else:
        # Root-level files (shared CI/config with no closer manifest) stay
        # in scope alongside the dominant segment itself — only OTHER
        # segments are excluded.
        scoped_files = [
            file
            for file in files
            if segmenter.segment_of(file.relative_path) in (dominant_segment, ROOT_SEGMENT)
        ]
    matched = match_evidence(scoped_files, tuple(missing_categories))

    seen = set(existing_paths)
    new_refs: list[FileReference] = []
    newly_satisfied: list[str] = []
    still_missing: list[str] = []
    for category in missing_categories:
        category_added = False
        for relative_path in matched.get(category.name, []):
            if relative_path in seen:
                continue
            ref = _to_file_reference(relative_path, category.name, permissions, token_estimator)
            if ref is None:
                continue
            seen.add(relative_path)
            new_refs.append(ref)
            category_added = True
        if category_added:
            newly_satisfied.append(category.name)
        else:
            still_missing.append(category.name)

    satisfied = (*already_satisfied, *newly_satisfied)

    if not new_refs:
        return (
            result.model_copy(
                update={
                    "evidence_categories_satisfied": satisfied,
                    "evidence_categories_missing": tuple(still_missing),
                }
            ),
            EvidenceSufficiencyReport(satisfied=satisfied, missing=tuple(still_missing)),
        )

    all_candidate_files = sorted(
        [*result.candidate_files, *new_refs], key=lambda ref: ref.file_path
    )
    selected_tokens = sum(ref.token_count for ref in all_candidate_files)
    raw_tokens = result.token_estimate.raw_context_tokens
    compression_ratio = round(selected_tokens / raw_tokens, 4) if raw_tokens else 0.0

    updated = result.model_copy(
        update={
            "candidate_files": all_candidate_files,
            "token_estimate": result.token_estimate.model_copy(
                update={
                    "selected_context_tokens": selected_tokens,
                    "compression_ratio": compression_ratio,
                }
            ),
            "resolution_reason": (
                f"{result.resolution_reason} Evidence sufficiency check added "
                f"{len(new_refs)} file(s) to cover: {', '.join(newly_satisfied)}."
            ),
            "evidence_categories_satisfied": satisfied,
            "evidence_categories_missing": tuple(still_missing),
        }
    )
    return updated, EvidenceSufficiencyReport(satisfied=satisfied, missing=tuple(still_missing))


def _to_file_reference(
    relative_path: str,
    category_name: str,
    permissions: PermissionManager,
    token_estimator: CostEstimator,
) -> FileReference | None:
    try:
        content = permissions.safe_read_text(relative_path)
    except _READ_ERRORS:
        return None
    return FileReference(
        file_path=relative_path,
        reason=f"evidence: {category_name}",
        language="unknown",
        token_count=token_estimator.count_tokens(content, _TOKEN_ESTIMATE_MODEL),
    )
