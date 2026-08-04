"""EvidenceFallback (ARCF v2.3 retrieval-context stabilization patch,
Changes 3 & 4; extended by the repository debugging routing fix's own
Changes 3-5) — deterministic retry/search-expansion for repository-scoped
tasks whose symbol-based resolution came back with zero candidate files,
plus the compact prompt summary built from whatever it finds.

Retrieval retry / search expansion: `expand_with_evidence` only ever
fires when ContextResolver already produced an EMPTY candidate_files
list — a resolution that found real symbol-based matches is never
touched or re-ranked. It combines up to three widening tiers:

1. Query-referenced files: if the raw request names a specific file,
   path, or quoted token (e.g. "diagnose the failure in
   `LoginPage.spec.ts`"), and a scanned file matches, that file is
   included with reason="references: query-referenced" — a distinct
   verb from "evidence: <category>" so RelevanceRanker (see its own
   _REASON_WEIGHTS) scores it above the generic evidence categories,
   giving it priority if ContextBudgetManager's token budget can't fit
   everything. This is deliberately additive, not exclusive: a
   query-referenced file supplements the evidence-contract categories
   below rather than replacing them, so the LLM still gets baseline
   diagnostic context (build config, test config) alongside the
   specific file asked about.
2. The task_type's evidence contract (`contracts/evidence_contract.py`)
   matched against the repository's already-scanned file list —
   dependency manifests, test config, test directories, CI workflows,
   project structure. Works for any registered task_type
   (repository_documentation, repository_debugging, ...) without this
   module knowing anything about what's in either contract.
3. If tiers 1+2 together still match nothing (an unusual repository
   layout with none of the contract's patterns present), the
   repository's own root-level files — the "collect repository tree +
   configuration files" last resort both stabilization briefs call
   for — so a repository-scoped task never reaches the final LLM call
   with zero files.

Deterministic context packaging: `build_repository_summary` renders a
short "Repository summary:" block from whichever evidence/reference
categories matched, purely by reading each PackagedFile's `reason`
prefix ("evidence: " or "references: ") — no ranking or scoring, just a
deterministic label lookup.

No model reasoning anywhere in this module, matching RepositoryScopeClassifier
and evidence_contract.py's own constraint.
"""

import re
from collections import Counter
from pathlib import Path

from contracts.evidence_contract import build_evidence_contract, match_evidence
from domain.context_package import PackagedFile
from domain.context_resolution import ContextResolutionResult, FileReference
from infrastructure.cost import CostEstimator
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager
from workspace.scanner import ScannedFile

_TOKEN_ESTIMATE_MODEL = "gpt-4o-mini"
_READ_ERRORS: tuple[type[Exception], ...] = (OSError, WorkspacePathError)
_ROOT_LEVEL_FALLBACK_MAX_FILES = 10
_QUERY_REFERENCE_MAX_FILES = 8
_SUMMARY_PREFIXES: tuple[str, ...] = ("evidence: ", "references: ")

# Filename-like ("LoginPage.spec.ts"), path-like ("src/auth/service"), and
# quoted ("`test_login`") tokens — deliberately just pattern extraction, not
# an attempt to parse the query's grammar; a token that happens not to
# match any scanned file is simply dropped, never treated as an error.
_QUOTED_TOKEN_RE = re.compile(r"[`'\"]([^`'\"]{2,80})[`'\"]")
_FILENAME_TOKEN_RE = re.compile(r"\b[\w][\w./\\-]*\.[A-Za-z0-9]{1,10}\b")
_PATH_TOKEN_RE = re.compile(r"\b[\w-]+(?:/[\w.-]+){1,6}\b")

_LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
    ".cs": "csharp",
    ".go": "go",
    ".kt": "kotlin",
    ".rs": "rust",
    ".rb": "ruby",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".ini": "ini",
    ".cfg": "ini",
    ".gradle": "gradle",
    ".xml": "xml",
}


def expand_with_evidence(
    result: ContextResolutionResult,
    files: list[ScannedFile],
    workspace_root: Path,
    task_type: str,
    raw_request: str = "",
) -> ContextResolutionResult:
    """Returns `result` unchanged unless candidate_files is empty; then
    combines query-referenced files with the evidence contract, falling
    back further to root-level files if both find nothing — or returns
    `result` unchanged if nothing at all matches (a repository-scoped
    task with truly no matching files still fails honestly rather than
    fabricating context)."""
    if result.candidate_files:
        return result

    permissions = PermissionManager(workspace_root)
    token_estimator = CostEstimator()

    referenced_refs = _match_query_referenced_files(
        raw_request, files, permissions, token_estimator
    )
    seen = {ref.file_path for ref in referenced_refs}
    contract_refs = [
        ref
        for ref in _match_evidence_contract(files, task_type, permissions, token_estimator)
        if ref.file_path not in seen
    ]
    new_refs = referenced_refs + contract_refs
    expansion_note = "the evidence contract"
    if referenced_refs and contract_refs:
        expansion_note = "query-referenced file(s) plus the evidence contract"
    elif referenced_refs:
        expansion_note = "query-referenced file(s)"

    if not new_refs:
        new_refs = _root_level_fallback(files, permissions, token_estimator)
        expansion_note = "repository root-level files"

    if not new_refs:
        return result

    selected_tokens = sum(ref.token_count for ref in new_refs)
    raw_tokens = result.token_estimate.raw_context_tokens
    compression_ratio = round(selected_tokens / raw_tokens, 4) if raw_tokens else 0.0
    dominant_language = _dominant_language(new_refs) or result.language

    return result.model_copy(
        update={
            "candidate_files": sorted(new_refs, key=lambda ref: ref.file_path),
            "language": dominant_language,
            "resolution_reason": (
                f"{result.resolution_reason} Retrieval retry: symbol-based resolution found "
                f"no candidate files, so search was expanded via {expansion_note}, "
                f"yielding {len(new_refs)} file(s)."
            ),
            "token_estimate": result.token_estimate.model_copy(
                update={
                    "selected_context_tokens": selected_tokens,
                    "compression_ratio": compression_ratio,
                }
            ),
        }
    )


def _match_query_referenced_files(
    raw_request: str,
    files: list[ScannedFile],
    permissions: PermissionManager,
    token_estimator: CostEstimator,
) -> list[FileReference]:
    tokens = _extract_query_tokens(raw_request)
    if not tokens:
        return []

    refs: list[FileReference] = []
    for file in files:
        if len(refs) >= _QUERY_REFERENCE_MAX_FILES:
            break
        basename = Path(file.relative_path).name.lower()
        path_lower = file.relative_path.lower()
        if not any(token in path_lower or token == basename for token in tokens):
            continue
        ref = _to_file_reference(
            file.relative_path, "references: query-referenced", permissions, token_estimator
        )
        if ref is not None:
            refs.append(ref)
    return refs


def _extract_query_tokens(raw_request: str) -> list[str]:
    tokens: list[str] = []
    for match in _QUOTED_TOKEN_RE.finditer(raw_request):
        tokens.append(match.group(1))
    for match in _FILENAME_TOKEN_RE.finditer(raw_request):
        tokens.append(match.group(0))
    for match in _PATH_TOKEN_RE.finditer(raw_request):
        tokens.append(match.group(0))

    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        normalized = token.strip("./\\").lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def _match_evidence_contract(
    files: list[ScannedFile],
    task_type: str,
    permissions: PermissionManager,
    token_estimator: CostEstimator,
) -> list[FileReference]:
    contract = build_evidence_contract(task_type)
    if not contract:
        return []

    matched = match_evidence(files, contract)
    refs: list[FileReference] = []
    seen: set[str] = set()
    for category in contract:
        for relative_path in matched.get(category.name, []):
            if relative_path in seen:
                continue
            ref = _to_file_reference(
                relative_path, f"evidence: {category.name}", permissions, token_estimator
            )
            if ref is None:
                continue
            seen.add(relative_path)
            refs.append(ref)
    return refs


def _root_level_fallback(
    files: list[ScannedFile],
    permissions: PermissionManager,
    token_estimator: CostEstimator,
) -> list[FileReference]:
    root_level = [file for file in files if "/" not in file.relative_path]
    refs: list[FileReference] = []
    for file in root_level[:_ROOT_LEVEL_FALLBACK_MAX_FILES]:
        ref = _to_file_reference(
            file.relative_path, "evidence: repository tree", permissions, token_estimator
        )
        if ref is not None:
            refs.append(ref)
    return refs


def _to_file_reference(
    relative_path: str,
    reason: str,
    permissions: PermissionManager,
    token_estimator: CostEstimator,
) -> FileReference | None:
    try:
        content = permissions.safe_read_text(relative_path)
    except _READ_ERRORS:
        return None
    return FileReference(
        file_path=relative_path,
        reason=reason,
        language=_language_of(relative_path),
        token_count=token_estimator.count_tokens(content, _TOKEN_ESTIMATE_MODEL),
    )


def _language_of(relative_path: str) -> str:
    extension = Path(relative_path).suffix.lower()
    return _LANGUAGE_BY_EXTENSION.get(extension, "unknown")


def _dominant_language(refs: list[FileReference]) -> str | None:
    languages = [ref.language for ref in refs if ref.language != "unknown"]
    if not languages:
        return None
    return Counter(languages).most_common(1)[0][0]


def build_repository_summary(packaged_files: list[PackagedFile]) -> str:
    """Renders the "Repository summary:" block from whichever packaged
    files carry an "evidence: <category>" or "references: <label>"
    reason (set by `expand_with_evidence`). Returns "" when none do, so
    a normal symbol-based resolution's prompt is unaffected."""
    lines: list[str] = []
    for file in packaged_files:
        for prefix in _SUMMARY_PREFIXES:
            if file.reason.startswith(prefix):
                label = file.reason.removeprefix(prefix)
                lines.append(f"- {label}: {file.file_path}")
                break
    if not lines:
        return ""
    return "Repository summary:\n" + "\n".join(lines)
