"""Stub Phase 6 consumer — proves ContextResolutionResult is sufficient
on its own to do Phase 6-shaped work.

Real Phase 6 modules should look like this: importing only
domain.context_resolution (and whatever else domain/ offers), never
anything from code_intelligence/. See
tests/code_intelligence/test_phase6_boundary.py, which parses this
file's own import statements to prove that structurally, then runs it
against a real ContextResolutionResult produced by Phase 5.
"""

from domain.context_resolution import ContextResolutionResult


def rank_candidate_files(result: ContextResolutionResult) -> list[str]:
    """A deliberately trivial stand-in for Phase 6's semantic relevance
    ranking: files whose reason is a direct definition sort first, then
    alphabetically. Real Phase 6 would rank via an SLM; this only proves
    the contract carries enough information to do so.
    """
    reason_by_file = {f.file_path: f.reason for f in result.candidate_files}

    def sort_key(file_path: str) -> tuple[bool, str]:
        reason = reason_by_file.get(file_path, "")
        return (not reason.startswith("defines"), file_path)

    return sorted((f.file_path for f in result.candidate_files), key=sort_key)


def summarize(result: ContextResolutionResult) -> str:
    return (
        f"{len(result.candidate_files)} candidate file(s), "
        f"{len(result.entry_points)} entry point(s), "
        f"confidence={result.confidence}, "
        f"compression={result.token_estimate.compression_ratio}"
    )
