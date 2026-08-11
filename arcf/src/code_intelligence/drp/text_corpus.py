"""DRP Stage 2a — per-file (and, when a file is large enough, per-symbol)
vocabulary gathering.

One text blob per FILE, not per subsystem/community: a real repository
run against Traefik found that pooling every file in a subsystem into
one directory-wide document systematically favors small, single-purpose
directories over large, correct-but-multi-concern ones — a query about
one specific behavior implemented by a single file (`pkg/server/
configurationwatcher.go`) lost to a small, single-topic directory
(`cmd/`, mostly one file about CLI configuration parsing) purely because
pooling diluted the relevant file's vocabulary across dozens of
unrelated neighbors. Scoring at file granularity and letting Stage 4
aggregate UP from each subsystem's/community's best-matching member
files (instead of down from one pooled document) fixes this at the
source rather than trying to compensate for it with weighting.

`gather_scoring_units` applies the exact same fix one level deeper: a
real SQLAlchemy run found the identical pooling problem recurring
INSIDE a single large file — `orm/strategies.py` defines 17 unrelated
loader-strategy classes (`_LazyLoader`, `_JoinedLoader`,
`_SelectInLoader`, ...) in one file, so `_LazyLoader`'s own precise,
correct docstring ("loads when first accessed") was diluted by the
other 16 classes' entirely different vocabulary — the file lost to a
handful of thin, docstring-heavy re-export modules elsewhere in the
same package purely because THEY weren't diluted by anything. Splitting
a file with many unrelated top-level symbols into one scoring unit per
symbol (its own text range, own docstring, own name) fixes this at the
source the same way `taxonomy.py`'s recursive subsystem splitting does
for directories — small/typical files (most of them) stay as a single
unit, exactly as small subsystems stay unsplit.

Reuses the identifier-level vocabulary already sitting in the existing
IR (`Symbol.name`/`qualified_name`, file basenames, `Symbol.location`
for extracting a symbol's own text range) at zero extra parsing cost.
Comments/docstrings are NOT present anywhere in `CodeIntelligenceIndex`
(confirmed: every LanguageAnalyzer extracts symbols/calls/imports/
decorators only, never comment or string content) — this module does a
second, lightweight, regex-based read of each file via the same
`PermissionManager.safe_read_text` boundary `CodeIntelligenceEngine`
itself uses, rather than teaching any of the six LanguageAnalyzers a
new extraction concern.

Deliberately not a real per-language comment grammar: a handful of
regexes covering '#'/'//' line comments, '/* */' block comments, and
triple-quoted strings catches the vocabulary that matters (English
words in comments/docstrings) across every language ARCF supports
today without importing tree-sitter grammars this module has no
business knowing.

`gather_scoring_units` also returns each unit's own incoming-call count
(`unit_usage`, from the already-built `CallGraph` — no new analysis).
Splitting fixed dilution, but exposed a further real problem: a test
file's functions are DISCOVERED and invoked by a test runner (pytest,
unittest, ...), never called from an explicit call site anywhere in the
source — true of every testing framework's own test suite as much as
anyone else's — so they structurally look like leaves in the call
graph regardless of how relevant their docstrings read. A real
SQLAlchemy run confirmed this precisely: `orm/strategies.py`'s actual
loader classes are each called ~370-400 times from elsewhere in the
codebase, while `test/orm/test_deferred.py`'s test classes mostly sit
in single digits. This is deliberately NOT a `test/`/`tests/` directory
name check — that would misfire on a repository whose own purpose IS
testing (its real implementation could easily live near test-sounding
paths); incoming call count is a purely structural signal that holds
regardless of what the repository is about. The same signal also
explains a second, separately-observed case for free: a file with zero
symbols of its own (a pure re-export/wrapper module) trivially has zero
incoming calls too, since there's nothing in it to call.
"""

from __future__ import annotations

import re
from pathlib import Path

from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.symbol_index import SymbolIndex
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager

# A file this large is not meaningfully "vocabulary" — generated data,
# vendored assets, or a lockfile that happens to share an analyzed
# extension. Skipping comment-scan (not indexing) for outsized files
# keeps Stage 2 bounded without dropping the file from candidate
# retrieval itself, which never depends on this module.
_MAX_COMMENT_SCAN_CHARS = 300_000

# A file with more top-level symbols than this splits into one scoring
# unit per symbol instead of one pooled per-file document. Calibrated
# against a real SQLAlchemy run: the median file with any top-level
# symbols has 5, the 90th percentile has 25; `orm/strategies.py` (the
# file this fix directly targets, confirmed diluted by pooling) has 17
# — comfortably above this threshold, while typical small/medium files
# stay untouched.
_MAX_SYMBOLS_PER_FILE_DOCUMENT = 8

_LINE_COMMENT_RE = re.compile(r"^\s*(?:#|//)\s?(.*)$")
_BLOCK_COMMENT_RE = re.compile(r"/\*(.*?)\*/", re.DOTALL)
_TRIPLE_QUOTE_RE = re.compile(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', re.DOTALL)

_DOC_NAME_RE = re.compile(r"^(readme|changelog|contributing|history)(\.\w+)?$", re.IGNORECASE)
_DOC_EXTENSIONS = frozenset({".md", ".rst", ".txt"})
# Bounds cost on doc-heavy repos (a large docs/ tree) — this corpus only
# feeds word-association learning (pmi_expansion.py), never file
# selection directly, so completeness matters far less than staying
# cheap.
_MAX_DOC_FILES = 200
_MAX_DOC_CHARS_PER_FILE = 50_000


def _extract_comment_and_docstring_text(content: str) -> str:
    content = content[:_MAX_COMMENT_SCAN_CHARS]
    chunks: list[str] = []
    for match in _BLOCK_COMMENT_RE.finditer(content):
        chunks.append(match.group(1))
    for match in _TRIPLE_QUOTE_RE.finditer(content):
        chunks.append(match.group(1) or match.group(2) or "")
    for line in content.splitlines():
        line_match = _LINE_COMMENT_RE.match(line)
        if line_match:
            chunks.append(line_match.group(1))
    return "\n".join(chunks)


def gather_file_text(
    index: CodeIntelligenceIndex, permissions: PermissionManager
) -> dict[str, str]:
    """One raw text blob per file, ready for `tfidf.build_tfidf_index`
    (each file is its own TF-IDF "document" — see module docstring for
    why file granularity, not subsystem/community pooling). Iterates
    `index.file_analyses` in sorted path order so the same index always
    produces byte-identical output."""
    texts: dict[str, str] = {}

    for file_path in sorted(index.file_analyses):
        chunks: list[str] = [Path(file_path).stem]
        analysis = index.file_analyses[file_path]
        for symbol in analysis.symbols:
            chunks.append(symbol.name)
            chunks.append(symbol.qualified_name)

        try:
            content = permissions.safe_read_text(file_path)
        except (OSError, WorkspacePathError):
            content = ""
        if content:
            chunks.append(_extract_comment_and_docstring_text(content))

        texts[file_path] = "\n".join(chunks)

    return texts


def _extract_line_range(content_lines: list[str], start_line: int, end_line: int) -> str:
    """1-indexed, inclusive line range, clamped to the file's actual
    length — `Symbol.location` is produced by tree-sitter against the
    same file content this module independently re-reads, so the range
    should already be valid, but a mismatched/stale read is a text-
    extraction inconvenience here, never a correctness issue worth
    raising over (this module only ever feeds vocabulary, not retrieval
    decisions on its own)."""
    start = max(start_line - 1, 0)
    end = min(end_line, len(content_lines))
    return "\n".join(content_lines[start:end])


def _is_within(
    inner_start: int, inner_end: int, outer_start: int, outer_end: int
) -> bool:
    """Whether the `[inner_start, inner_end]` line range sits entirely
    inside `[outer_start, outer_end]` — used to tell "this child is
    lexically nested in its parent's own source range" (Python: a method
    inside its class body) apart from "this child is declared separately
    from its parent" (Go: a method outside its receiver type's struct
    declaration) — see `gather_scoring_units`'s own use for why that
    distinction matters."""
    return inner_start >= outer_start and inner_end <= outer_end


def _expand_start_for_leading_comment(content_lines: list[str], start_line: int) -> int:
    """Walks backward from a symbol's own 1-indexed `start_line` over a
    contiguous, unbroken block of `#`/`//` line comments directly above
    it — the conventional doc-comment position in languages that
    describe a declaration ABOVE it (Go: `// Register a service...`
    immediately above `func (c *Catalog) Register(...)`) rather than as
    a nested docstring inside it (Python). `Symbol.location.start_line`
    points at the declaration itself, so a plain range extraction from
    it stops exactly short of that comment — a real Consul run found
    `Catalog.Register`'s own doc comment (almost paraphrasing the query
    DRP was trying to match) silently excluded for exactly this reason,
    even after the sibling fix that made the method's range reachable at
    all. Stops at the first non-comment or blank line so it never reaches
    into unrelated code above — a real leading doc comment is always
    contiguous with its declaration, with no blank-line gap."""
    idx = min(start_line - 2, len(content_lines) - 1)  # 0-indexed line above start_line
    while idx >= 0 and _LINE_COMMENT_RE.match(content_lines[idx]):
        idx -= 1
    return idx + 2  # back to 1-indexed, first line of the comment block


def _has_locality(
    index: CodeIntelligenceIndex, caller_file: str, context_file: str
) -> bool:
    """Same locality test `ReferenceResolver.resolve_with_disambiguation`
    already uses (same file / same directory / import-reachable) — see
    `_combined_call_count` for why DRP applies it here too, as a read-side
    filter over `CallGraph`'s own edges rather than any change to
    `CallGraph`/`ReferenceResolver` themselves."""
    if caller_file == context_file:
        return True
    if SymbolIndex.same_package(caller_file, context_file):
        return True
    return (
        caller_file in index.import_graph.imports_of(context_file)
        or context_file in index.import_graph.importers_of(caller_file)
    )


def _combined_call_count(
    index: CodeIntelligenceIndex, symbol_ids: list[str], context_file: str
) -> int:
    """Every recorded caller of any of `symbol_ids` that has real locality
    to `context_file` (the file being scored) — both named-caller call
    sites (`caller_symbols_of`) and module-level/anonymous call sites
    (`caller_files_of`), the same two sources CallGraph itself
    distinguishes, each locality-filtered before counting.

    `CallGraph`/`ReferenceResolver` deliberately resolve an ambiguous name
    to EVERY symbol sharing it (see `reference_resolver.py`'s own module
    docstring: `resolve()`'s "fan-out-to-all-candidates behavior is
    already well tested" and intentionally left that way for CallGraph's
    real purpose, conservative reachability/impact analysis). That's the
    right call for "could this call reach this symbol", but wrong for a
    raw COUNT: a real SQLAlchemy run found three unrelated `__init__`
    methods in one file each credited with an identical 367 "callers" —
    the total count of every `__init__()` call anywhere in the whole
    repository, fanned out to every same-named candidate including these
    three. That inflated count then defeated `tfidf.py`'s own usage-
    confidence dampening (fix #6), which assumes a low count means low
    real usage. Filtering to locality-plausible callers only (the same
    signal `resolve_with_disambiguation` already uses for exactly this
    kind of ambiguity, just applied here as a filter on top of CallGraph's
    already-computed edges rather than a change to CallGraph itself, per
    DRP's isolation discipline) turns this back into a real usage
    estimate without touching shared, already-tested infrastructure."""
    total = 0
    for symbol_id in symbol_ids:
        for caller_id in index.call_graph.caller_symbols_of(symbol_id):
            caller_symbol = index.symbol_index.get(caller_id)
            if caller_symbol is not None and _has_locality(
                index, caller_symbol.file_path, context_file
            ):
                total += 1
        for caller_file in index.call_graph.caller_files_of(symbol_id):
            if _has_locality(index, caller_file, context_file):
                total += 1
    return total


def gather_scoring_units(
    index: CodeIntelligenceIndex,
    permissions: PermissionManager,
    max_symbols_per_file_document: int = _MAX_SYMBOLS_PER_FILE_DOCUMENT,
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, int]]:
    """Returns `(unit_texts, file_to_units, unit_usage)` — the per-file
    document corpus `file_tfidf`/Stage 4 actually score against, now
    split per-symbol for files with too many unrelated top-level symbols
    pooled together (see module docstring). `unit_texts` keys are the
    file path itself for a file that stayed whole, or `symbol.id` for
    one top-level symbol's own unit in a split file — every analyzer's
    own symbol id is already globally unique and already embeds the
    file path (e.g. `"{file}::{qualified_name}#{line}"`), so it doubles
    as the unit key directly rather than needing a second file-path
    prefix. `file_to_units` maps every file to its own constituent unit
    key(s) (always a single-element list for a file that stayed whole)
    so a caller can reconstitute "this file's own best score" from
    whichever units it was split into — see query_router.py's own
    reduction step. `unit_usage` maps each unit to its own combined
    incoming-call count (see module docstring and `tfidf.py`'s usage-
    confidence dampening).

    Iterates `index.file_analyses` in sorted path order, and each split
    file's own top-level symbols in sorted-by-id order, so the same
    index always produces byte-identical output."""
    unit_texts: dict[str, str] = {}
    file_to_units: dict[str, list[str]] = {}
    unit_usage: dict[str, int] = {}

    for file_path in sorted(index.file_analyses):
        analysis = index.file_analyses[file_path]
        top_level_symbols = sorted(
            (symbol for symbol in analysis.symbols if symbol.parent_id is None),
            key=lambda symbol: symbol.id,
        )

        try:
            content = permissions.safe_read_text(file_path)
        except (OSError, WorkspacePathError):
            content = ""
        content = content[:_MAX_COMMENT_SCAN_CHARS]

        if len(top_level_symbols) <= max_symbols_per_file_document:
            chunks: list[str] = [Path(file_path).stem]
            for symbol in analysis.symbols:
                chunks.append(symbol.name)
                chunks.append(symbol.qualified_name)
            if content:
                chunks.append(_extract_comment_and_docstring_text(content))
            unit_texts[file_path] = "\n".join(chunks)
            file_to_units[file_path] = [file_path]
            unit_usage[file_path] = _combined_call_count(
                index, [symbol.id for symbol in analysis.symbols], file_path
            )
            continue

        content_lines = content.splitlines()
        units: list[str] = []
        for symbol in top_level_symbols:
            unit_key = symbol.id
            member_ids = [symbol.id]
            chunks = [symbol.name, symbol.qualified_name]
            parent_start, parent_end = symbol.location.start_line, symbol.location.end_line
            external_child_ids: list[str] = []
            for child in analysis.symbols:
                # Nested members (methods of a class) contribute their own
                # names to their parent's unit rather than becoming
                # further scoring units of their own when the child's own
                # source range is lexically nested inside the parent's
                # (Python: a method inside its class body) — one level of
                # splitting (file -> top-level symbol) is the fix this was
                # scoped to for that case.
                if child.parent_id != symbol.id:
                    continue
                chunks.append(child.name)
                member_ids.append(child.id)
                if _is_within(
                    child.location.start_line, child.location.end_line, parent_start, parent_end
                ):
                    continue
                # A language whose methods are declared OUTSIDE their
                # receiver type's own source range (Go: `func (c *Catalog)
                # Register(...)`, declared separately from `type Catalog
                # struct{...}`) gets a genuine SECOND splitting tier here,
                # one scoring unit per such child — not pooled into the
                # parent's. Pooling was tried first and made things worse:
                # a real Consul run found `Catalog.Register`'s own doc
                # comment ("Register a service and/or check(s) in a node,
                # creating the node if it doesn't exist.") entirely absent
                # from the corpus before this fix, but pooling all 11 of
                # Catalog's methods' comments into Catalog's single unit
                # measurably LOWERED catalog_endpoint.go's real retrieval
                # score anyway — the same dilution fix #3 already prevents
                # at the file level (many methods' unrelated concerns —
                # ACL checks, metrics, hashing — burying Register's own
                # specific vocabulary), just recurring one level deeper.
                # Giving each such child its own unit lets `_file_level_
                # scores`'s existing max-across-a-file's-units reduction
                # surface it undiluted, exactly like every other split
                # unit already works.
                child_start = _expand_start_for_leading_comment(
                    content_lines, child.location.start_line
                )
                child_text = _extract_line_range(
                    content_lines, child_start, child.location.end_line
                )
                child_chunks = [child.name, child.qualified_name]
                if child_text:
                    child_chunks.append(_extract_comment_and_docstring_text(child_text))
                unit_texts[child.id] = "\n".join(child_chunks)
                unit_usage[child.id] = _combined_call_count(index, [child.id], file_path)
                units.append(child.id)
                external_child_ids.append(child.id)
            if external_child_ids:
                # A method dispatched by a framework's own registration
                # table (an RPC handler invoked by name/reflection, not a
                # direct call site) structurally has zero recorded callers
                # no matter how central it is — CallGraph only sees
                # explicit call expressions, and a real Consul run
                # confirmed this hits even the receiver TYPE's own
                # construction (`&Catalog{...}`, a struct literal, isn't a
                # "call" CallGraph tracks either, so the type itself can't
                # be used as a fallback signal). What DOES survive: at
                # least one sibling method on the same receiver usually
                # has real, directly-observed usage (an internal helper
                # call, a test invoking it directly) — real evidence the
                # TYPE as a whole is live, active code, not dead/vestigial
                # — real Consul numbers: 9 of Catalog's 11 methods showed
                # 0 own callers, but `ServiceNodes` (4) and
                # `VirtualIPForService` (6) didn't. A zero-usage sibling
                # borrows the group's max as a confidence FLOOR — never
                # lowers an already-nonzero count, only rescues a fully
                # invisible one from the same dead/vestigial-vs-real
                # ambiguity fix #6 was built to resolve, using the
                # already-existing parent-child structural relationship
                # rather than any new analysis.
                sibling_max = max(unit_usage[child_id] for child_id in external_child_ids)
                if sibling_max > 0:
                    for child_id in external_child_ids:
                        if unit_usage[child_id] == 0:
                            unit_usage[child_id] = sibling_max
            expanded_parent_start = _expand_start_for_leading_comment(content_lines, parent_start)
            symbol_text = _extract_line_range(content_lines, expanded_parent_start, parent_end)
            if symbol_text:
                chunks.append(_extract_comment_and_docstring_text(symbol_text))
            unit_texts[unit_key] = "\n".join(chunks)
            unit_usage[unit_key] = _combined_call_count(index, member_ids, file_path)
            units.append(unit_key)
        file_to_units[file_path] = units

    return unit_texts, file_to_units, unit_usage


def _is_doc_file(file_path: str) -> bool:
    path = Path(file_path)
    if _DOC_NAME_RE.match(path.name):
        return True
    return path.suffix.lower() in _DOC_EXTENSIONS


def gather_doc_prose(
    index: CodeIntelligenceIndex, permissions: PermissionManager
) -> dict[str, str]:
    """Project documentation — README, CHANGELOG, docs/**/*.md, and
    similar — read from `index.skipped_files` (files RepositoryScanner
    found but no LanguageAnalyzer parsed; no new scanning needed).

    Deliberately NOT merged into `gather_file_text`'s corpus and never
    fed into `file_tfidf`/Stage 2: binding a doc paragraph to the one
    specific FILE it's "about" via bag-of-words cosine similarity was
    tried directly against a real repository and found not to work —
    docs describe a whole feature area and share generic vocabulary
    with many related files, not just the correct one, which is exactly
    the dilution failure Stage 2's per-file redesign already fixed for
    code; pooling docs back in would reopen it.

    This corpus exists for a narrower, different purpose:
    `pmi_expansion.py`'s word-association graph needs to learn that,
    say, "restarting" and "reload" tend to appear together SOMEWHERE in
    the repository's own text — which never happens in code comments
    alone when a feature is described in docs but implemented under a
    different vocabulary — without ever needing to know WHICH file that
    association belongs to. Stage 4's existing per-file TF-IDF (already
    proven, unchanged) still does the real file-selection work once the
    expanded query terms come back real and corpus-native."""
    texts: dict[str, str] = {}
    doc_candidates = [path for path in sorted(index.skipped_files) if _is_doc_file(path)]
    for file_path in doc_candidates[:_MAX_DOC_FILES]:
        try:
            content = permissions.safe_read_text(file_path)
        except (OSError, WorkspacePathError):
            continue
        texts[file_path] = content[:_MAX_DOC_CHARS_PER_FILE]

    return texts
