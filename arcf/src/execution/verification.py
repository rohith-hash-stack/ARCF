"""Deterministic Grounding Verification (architecture closure, Sec. I/§16).

Pure function, no I/O, no LLM call, no embeddings -- checks the two
things the current architecture can honestly support:

1. Was required evidence missing going into generation?
   (ContextResolutionResult.evidence_categories_missing, already
   computed by context/evidence_validator.py -- this function is a new
   *reader* of that field, not a new computation of it.)
2. Does the generated artifact reference a repository file path that
   was never actually retrieved into ContextPackage.relevant_files?
   A deterministic path-token match, not semantic fact-checking.

Deliberately does NOT attempt contradiction/semantic-correctness
detection -- contradictions_checked is always False on the returned
result. See domain/verification_result.py's own docstring for why that
is an explicit, honest limitation rather than a silent omission.

Path-reference extraction/matching (2026-08-17 hardening pass, found by
adversarial re-verification, not the original implementation):
- Matches both "/" and "\\" separated paths (Windows-style references,
  relevant since this project's own dev environment is Windows).
- Also matches a small allowlist of conventional extensionless
  filenames (Dockerfile, Makefile, ...) when preceded by a directory
  segment, and bare filenames (no directory at all) when they carry a
  known common source-file extension -- both gated by allowlists
  specifically to avoid the false-positive risk of a fully-open
  "any word before a dot" or "any two words joined by a slash" pattern
  (e.g. "either/or", "on/off" are common English, not file paths).
- _paths_match no longer does bare, boundary-unaware `str.endswith`
  suffix matching: a real bug (found by the same review) let a
  genuinely fabricated reference like "utils.py" incorrectly match an
  unrelated real packaged file "database_utils.py", because
  "database_utils.py" ends with the substring "utils.py" with no
  path-segment boundary check. Matches now require the shorter path to
  align on a "/" boundary (or be identical), same discipline as the
  existing git-diff a/ b/ prefix-tolerance case.
- Comparison is now case-insensitive (Windows/macOS default
  filesystems are case-insensitive; a differently-cased reference to a
  real packaged file should not be flagged as unsupported).

Absolute-path extraction (2026-08-17, second hardening pass, found by
independent architecture-closure verification): the directory/
extensionless patterns above both open with a negative lookbehind
`(?<![\w/\\])` whose purpose is to stop a match from starting in the
middle of an already-longer path/identifier. That same lookbehind also
made every ABSOLUTE path structurally invisible to extraction -- a Unix
path starts with "/" and a Windows path's first real segment is
preceded by "\" (after the drive letter), both excluded characters --
so a fabricated absolute-path reference to a file that was never
retrieved could pass verification as SUFFICIENT simply because the
extractor never saw it as a reference at all, not because the matching
logic said it was supported. `_ABSOLUTE_PATH_PATTERN`/
`_ABSOLUTE_EXTENSIONLESS_PATTERN` below are dedicated patterns whose
lookbehind excludes only what would make them fire mid-token
(`\w`, `/`, `\\`, `:`) while explicitly allowing the leading root anchor
itself ("/" or "C:\") to open a match. `_paths_match`/`_normalize`
needed no changes for this: an absolute reference that is a real
repository file already matches via the existing "/"-boundary suffix
rule (e.g. "/workspace/src/foo.py" ends with "/src/foo.py", the
packaged relative path) -- only extraction was blind, not matching.

Still explicitly NOT covered, by design (documented, not silently
missing): a bare filename with no directory and no extension (e.g. a
fabricated "LICENSE" with no path prefix at all) is indistinguishable
from an ordinary capitalized word without a much larger allowlist; this
stays a known, accepted limitation rather than chasing every case.
Malformed path-like text that matches none of the patterns below
(truncated paths, stray separators, non-path punctuation) is likewise
never extracted and therefore never flagged -- the same tolerant,
documented posture as every other unrecognized-shape case here, not a
crash or an exception.
"""

import re

from domain.artifact import Artifact
from domain.context_package import ContextPackage
from domain.context_resolution import ContextResolutionResult
from domain.verification_result import GroundingVerificationResult, GroundingVerificationStatus

_EXTENSIONLESS_FILENAMES = (
    "Dockerfile",
    "Makefile",
    "LICENSE",
    "README",
    "CHANGELOG",
    "Procfile",
    "Gemfile",
    "Rakefile",
)

_COMMON_SOURCE_EXTENSIONS = (
    "py",
    "js",
    "jsx",
    "ts",
    "tsx",
    "go",
    "java",
    "kt",
    "rb",
    "rs",
    "c",
    "h",
    "cpp",
    "hpp",
    "cs",
    "json",
    "yaml",
    "yml",
    "toml",
    "md",
    "txt",
    "sql",
    "sh",
    "cfg",
    "ini",
)

_PATH_SEGMENT = r"[A-Za-z0-9_.\-]+"
_DIR_SEP = r"[/\\]"

# A path with at least one directory segment and a real extension.
_DIRECTORY_PATH_PATTERN = re.compile(
    rf"(?<![\w/\\]){_PATH_SEGMENT}(?:{_DIR_SEP}{_PATH_SEGMENT})+\.[A-Za-z0-9]{{1,10}}(?![\w])"
)
# A path with at least one directory segment ending in a known
# extensionless conventional filename.
_EXTENSIONLESS_PATH_PATTERN = re.compile(
    rf"(?<![\w/\\]){_PATH_SEGMENT}(?:{_DIR_SEP}{_PATH_SEGMENT})*{_DIR_SEP}"
    rf"(?:{'|'.join(_EXTENSIONLESS_FILENAMES)})(?![\w])"
)
# A bare filename (no directory) with a known common source extension.
_BARE_FILENAME_PATTERN = re.compile(
    rf"(?<![\w/\\.\-]){_PATH_SEGMENT}\.(?:{'|'.join(_COMMON_SOURCE_EXTENSIONS)})(?![\w])"
)

# Root anchor for an absolute path: a Unix leading "/", or a Windows
# drive letter + ":" + separator ("C:\", "C:/"). Deliberately excludes
# UNC ("\\server\share") -- not a shape this codebase's own file paths
# or generated content have ever been observed to use; adding it would
# widen the false-positive surface (a bare "\\word\word") for no known
# real case.
_DRIVE_ROOT = r"[A-Za-z]:[/\\]"
_ROOT_ANCHOR = rf"(?:{_DRIVE_ROOT}|/)"

# An absolute path -- root anchor, zero or more additional directory
# segments (a root immediately followed by a filename, e.g. "/foo.py",
# is still a legitimate absolute reference), a real extension. Lookbehind
# excludes ":" in addition to \w/\\ so this can't fire partway through
# a drive-root match it should own from its own start ("C:\foo.py" must
# match once, anchored at "C", not again at "\foo.py").
_ABSOLUTE_PATH_PATTERN = re.compile(
    rf"(?<![\w/\\:]){_ROOT_ANCHOR}{_PATH_SEGMENT}(?:{_DIR_SEP}{_PATH_SEGMENT})*"
    rf"\.[A-Za-z0-9]{{1,10}}(?![\w])"
)
# Same root anchor, ending in a known extensionless conventional
# filename instead of a real extension (e.g. "/etc/Dockerfile",
# "C:\repo\Makefile").
_ABSOLUTE_EXTENSIONLESS_PATTERN = re.compile(
    rf"(?<![\w/\\:]){_ROOT_ANCHOR}(?:{_PATH_SEGMENT}{_DIR_SEP})*"
    rf"(?:{'|'.join(_EXTENSIONLESS_FILENAMES)})(?![\w])"
)


def _normalize(path: str) -> str:
    return path.replace("\\", "/").strip("/").lower()


def _paths_match(referenced: str, packaged: str) -> bool:
    a, b = _normalize(referenced), _normalize(packaged)
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


_EXTRACTION_PATTERNS = (
    _ABSOLUTE_PATH_PATTERN,
    _ABSOLUTE_EXTENSIONLESS_PATTERN,
    _DIRECTORY_PATH_PATTERN,
    _EXTENSIONLESS_PATH_PATTERN,
    _BARE_FILENAME_PATTERN,
)


def _extract_referenced_paths(content: str) -> tuple[str, ...]:
    matches: list[str] = []
    for pattern in _EXTRACTION_PATTERNS:
        matches.extend(pattern.findall(content))
    return tuple(dict.fromkeys(matches))


def verify_grounding(
    artifact: Artifact,
    package: ContextPackage,
    resolution: ContextResolutionResult,
) -> GroundingVerificationResult:
    missing_categories = resolution.evidence_categories_missing

    if missing_categories:
        return GroundingVerificationResult(
            status=GroundingVerificationStatus.INSUFFICIENT_EVIDENCE,
            evidence_sufficient=False,
            missing_evidence_categories=missing_categories,
            recovery_eligible=True,
        )

    packaged_paths = tuple(f.file_path for f in package.relevant_files)
    referenced_paths = _extract_referenced_paths(artifact.content)
    unsupported = tuple(
        ref
        for ref in referenced_paths
        if not any(_paths_match(ref, packaged) for packaged in packaged_paths)
    )

    if unsupported:
        return GroundingVerificationResult(
            status=GroundingVerificationStatus.UNSUPPORTED_REFERENCES,
            evidence_sufficient=True,
            unsupported_file_references=unsupported,
            recovery_eligible=True,
        )

    return GroundingVerificationResult(
        status=GroundingVerificationStatus.SUFFICIENT,
        evidence_sufficient=True,
        recovery_eligible=False,
    )
