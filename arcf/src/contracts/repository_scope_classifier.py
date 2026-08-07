"""RepositoryScopeClassifier — deterministic detection of requests that
require whole-repository evidence (ARCF v2.3 retrieval-context
stabilization patch, Change 1; extended for the repository debugging
routing fix's own Change 1).

Sits alongside TaskClassifier (same keyword-substring idiom) but answers a
narrower question TaskClassifier doesn't: not just "what kind of task is
this" but "does completing it require whole-repository evidence, even when
SLM-1 extracted no named symbols to resolve against?" code_intelligence/
service.py uses this signal to decide whether an empty candidate_files
result is a legitimate "nothing relevant" outcome or a retrieval gap that
must be filled via the evidence-contract fallback (see evidence_contract.py
and context/evidence_fallback.py).

Two repository-scoped task types are recognized, checked in this order
(debugging first): "repository_debugging" (a failing test, an exception, a
regression — something concrete needs to be diagnosed, not documented) and
"repository_documentation" (README/architecture/contribution-guideline
requests). A request matching neither is "unscoped". Debugging is checked
first because it is the more specific, higher-signal category — a query
combining debugging and documentation language (unusual, but not
impossible) should still get the evidence contract actually relevant to
"why is this broken," not a documentation-shaped one.
"""

from dataclasses import dataclass

_STRONG_TRIGGERS: tuple[str, ...] = (
    "readme",
    "changelog",
    "contribution guidelines",
    "contributing guidelines",
    "architecture documentation",
    "setup instructions",
    "execution instructions",
    "generate documentation",
    "generate docs",
    "repository documentation",
    "explain repository",
    "explain this repository",
    "explain the repository",
    "summarize test suite",
    "summarize the test suite",
)

_DOCUMENTATION_WORDS: tuple[str, ...] = (
    "document",
    "documentation",
    "docs",
    "explain",
    "summarize",
    "summary",
    "describe",
)

_REPOSITORY_WORDS: tuple[str, ...] = (
    "repository",
    "repo",
    "codebase",
    "project",
    "test suite",
)

# Phrases specific enough to signal a repository-debugging request on their
# own, without needing a separate repository-reference word alongside them
# (e.g. "help me debug this failure" never says "repo" but is still
# unambiguously about diagnosing something in the attached workspace — this
# tool has no other subject a debugging request could be about).
_DEBUGGING_STRONG_TRIGGERS: tuple[str, ...] = (
    "help me debug",
    "help me diagnose",
    "first places to inspect",
    "places to inspect",
    "root cause",
    "is failing",
    "are failing",
    "stack trace",
)

# Debugging ACTION verbs — like _DEBUGGING_STRONG_TRIGGERS, specific
# enough on their own that this tool has no other plausible subject:
# "debug"/"diagnose"/"investigate" almost never mean anything but "debug
# this repository" when asked of a code-context tool (same reasoning
# applied to _DOCUMENTATION_WORDS). Checked unconditionally, no
# co-occurring repository word required.
_DEBUGGING_VERBS: tuple[str, ...] = (
    "debug",
    "diagnose",
    "investigate",
)

# Debugging NOUNS/adjectives — unlike the action verbs above, these
# describe a concept ("an error message", "handle timeout gracefully",
# "the crash log format") that shows up plenty in non-debugging requests
# too (UI copy, feature specs, logging design), so these stay gated
# behind a co-occurring repository-reference word rather than triggering
# on their own.
_DEBUGGING_WORDS: tuple[str, ...] = (
    "failing",
    "failed",
    "error",
    "exception",
    "inspect",
    "trace",
    "stack trace",
    "timeout",
    "assertion",
    "failure",
    "crash",
    "regression",
    "flaky",
    "not working",
    "broken",
    "why is",
    "root cause",
)

_DEBUGGING_REPOSITORY_WORDS: tuple[str, ...] = (
    *_REPOSITORY_WORDS,
    "application",
    "service",
)


@dataclass(frozen=True)
class RepositoryScopeClassification:
    task_type: str
    repository_scope: bool


class RepositoryScopeClassifier:
    def classify(self, text: str) -> RepositoryScopeClassification:
        text_lower = text.lower()

        is_debugging = (
            any(trigger in text_lower for trigger in _DEBUGGING_STRONG_TRIGGERS)
            or any(verb in text_lower for verb in _DEBUGGING_VERBS)
            or (
                any(word in text_lower for word in _DEBUGGING_WORDS)
                and any(word in text_lower for word in _DEBUGGING_REPOSITORY_WORDS)
            )
        )
        if is_debugging:
            return RepositoryScopeClassification(
                task_type="repository_debugging", repository_scope=True
            )

        # No AND-condition against _REPOSITORY_WORDS here, deliberately —
        # same reasoning _DEBUGGING_STRONG_TRIGGERS already establishes for
        # debugging phrases: an explanation verb ("explain"/"describe"/
        # "summarize"/"document") almost never means anything else when
        # asked of this tool, so requiring a co-occurring repository noun
        # just misses conceptual questions ("Explain how X works") that
        # never say "repo"/"codebase" at all.
        is_documentation = any(trigger in text_lower for trigger in _STRONG_TRIGGERS) or any(
            word in text_lower for word in _DOCUMENTATION_WORDS
        )
        if is_documentation:
            return RepositoryScopeClassification(
                task_type="repository_documentation", repository_scope=True
            )

        return RepositoryScopeClassification(task_type="unscoped", repository_scope=False)
