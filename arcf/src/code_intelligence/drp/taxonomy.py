"""DRP Stage 1 — Repository Taxonomy.

Discovers Subsystem Nodes purely from the directory structure already
visible in `CodeIntelligenceIndex.file_analyses` keys (no new filesystem
walk — those paths were already produced by RepositoryScanner) plus the
package/module namespace prefixes already visible in `Symbol.
qualified_name` (already parsed by the language analyzers — no
re-parsing, no per-language logic). Deliberately dictionary-free: a
subsystem's "meaning" comes only from Stage 2's TF-IDF profile built on
top of this structure, never from a name this module hardcodes.

Depth is ADAPTIVE, not fixed at top-level/second-level: a directory is
registered as its own Subsystem Node only once its own (recursive)
subtree file count drops to or below `_MAX_FILES_PER_SUBSYSTEM`, or it
has nowhere left to split into. A fixed two-level cap was tried first
and found, against three independent real repositories, to badly pool
unrelated code together whenever a project's real package boundary sits
deeper than two directories — confirmed directly: `django/db` (123
files) pools `django/db/models/` (45 files, the actual relevant
package) together with `django/db/backends/` (56 files, unrelated
per-vendor driver code) into one blob; `lib/sqlalchemy` (255 files, a
`lib/` wrapper directory over the entire library) pools essentially the
whole codebase together, `lib/sqlalchemy/orm` (38 files) never becoming
its own node; `vllm/v1` (335 files) pools core scheduling, the executor,
the sampler, and worker code together. Traefik's own structure happens
to be exactly two levels deep (`pkg/server/*.go`), which is why this
gap stayed invisible until a differently-shaped repository was tested.
Recursive splitting subsumes the fixed two-level rule as its own special
case (a repository whose subtrees are already small at depth two simply
never needs to split further) while adapting to arbitrary real depth.

Directory splitting alone still has a gap: it only helps when an
oversized directory HAS subdirectories to split into. A real Consul run
found `agent/consul` — 175 Go files sitting flat in one directory, no
subdirectories at all (idiomatic Go: one package, one directory, many
files) — impossible to split by directory regardless of how large it
gets. The actual target file (`catalog_endpoint.go`) scored highest of
any individual file in the whole repository, but its subsystem's
aggregate score was dragged down by 170+ unrelated ACL/leader-election/
snapshot/session files sharing the same flat directory, while a smaller,
topically-focused directory (an integration test suite that exists
specifically to exercise catalog/service/cluster behavior) wasn't
diluted the same way and out-scored it. When a directory is oversized
AND flat (no subdirectories), it splits by filename prefix instead —
Go's own naming convention already groups related files this way
(`catalog_endpoint.go`, `catalog_endpoint_ce.go`, `catalog_endpoint_
test.go` all share the `catalog` prefix, cleanly separated from `acl_*`,
`leader_*`, `server_*`), so this reuses a convention the codebase
already follows rather than inventing a new rule.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from code_intelligence.index import CodeIntelligenceIndex

# A subsystem pooling more files than this splits into its own immediate
# subdirectories instead. Calibrated against real repositories this
# session: 27 files (Traefik's pkg/server, a subsystem that correctly
# resolved a query on its own) and 45/38/15 files (Django's db/models,
# SQLAlchemy's orm, vLLM's core — the actual relevant packages once
# splitting reaches them) all sit comfortably under this value and
# should NOT split further; 123/255/335 files (Django's db, SQLAlchemy's
# lib/sqlalchemy, vLLM's v1 — each confirmed to dilute retrieval by
# pooling unrelated subpackages together) all sit well above it and
# should.
_MAX_FILES_PER_SUBSYSTEM = 50

# Safety cap on recursion depth, not a tuning knob expected to bind in
# practice — real package hierarchies rarely nest this deep, but this
# guarantees termination regardless of how a pathological repository is
# structured.
_MAX_TAXONOMY_DEPTH = 6


def _normalize(file_path: str) -> str:
    return file_path.replace("\\", "/")


def _dir_of(file_path: str) -> str:
    normalized = _normalize(file_path)
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def _ancestors_inclusive(dir_path: str) -> list[str]:
    """`dir_path` itself, then each successive parent, ending with `""`
    (root) — e.g. "a/b/c" -> ["a/b/c", "a/b", "a", ""]."""
    if not dir_path:
        return [""]
    parts = dir_path.split("/")
    return ["/".join(parts[:i]) for i in range(len(parts), 0, -1)] + [""]


def _filename_prefix(file_path: str) -> str:
    """The part of a file's own basename before its first underscore
    (or the whole stem, if there isn't one) — e.g. "catalog_endpoint.go"
    -> "catalog", "acl_replication_test.go" -> "acl". Used only to
    cluster files WITHIN a single oversized, subdirectory-less directory
    (see module docstring) — never touches directories that already have
    real subdirectories to split into."""
    basename = file_path.rsplit("/", 1)[-1]
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    return stem.split("_")[0]


@dataclass
class SubsystemNode:
    path: str
    """Directory path this subsystem represents; `""` for the synthetic
    root subsystem (files with no directory, or under a shallower tree
    than any registered node covers)."""
    depth: int
    """0 = root; otherwise the number of path segments (e.g. "pkg/server"
    is depth 2, "django/db/models" is depth 3) — no longer capped at 2,
    since registration itself is now adaptive."""
    files: list[str] = field(default_factory=list)
    """Relative file paths assigned to this subsystem — the deepest
    registered subsystem containing each file, not necessarily its exact
    parent directory."""
    package_namespaces: set[str] = field(default_factory=set)
    """Qualified-name prefixes (everything before the last `.` segment)
    seen among symbols defined in this subsystem's files — an auxiliary,
    best-effort signal, not load-bearing for routing correctness."""

    @property
    def name(self) -> str:
        return self.path if self.path else "(root)"


@dataclass
class SubsystemTaxonomy:
    nodes: dict[str, SubsystemNode]
    """Keyed by subsystem path (`""` for root)."""
    file_to_subsystem: dict[str, str]
    """Every indexed file's assigned subsystem path."""

    def subsystem_of(self, file_path: str) -> str | None:
        return self.file_to_subsystem.get(_normalize(file_path))

    def files_in(self, subsystem_path: str) -> list[str]:
        node = self.nodes.get(subsystem_path)
        return list(node.files) if node is not None else []


def _register_subsystem_paths(
    file_paths: list[str], max_files_per_subsystem: int
) -> tuple[set[str], dict[str, str]]:
    """Recursively decides which directories (or, for an oversized flat
    directory, which filename-prefix clusters within it) become
    Subsystem Nodes. Starts at root and keeps splitting a directory into
    its own immediate subdirectories as long as its subtree is over
    `max_files_per_subsystem` files and it has real subdirectories to
    split into; a directory over the threshold with NO subdirectories
    splits by filename prefix instead (see module docstring); otherwise
    the directory itself is registered. A directory that splits by real
    subdirectory but still has files sitting directly in it is
    registered too, alongside its children — those files need a home
    regardless of whether the directory as a whole warranted finer
    splitting.

    Returns `(registered_paths, file_to_virtual_owner)` — the second
    dict covers only files that landed in a filename-prefix cluster
    (virtual node path `f"{dir_path}::{prefix}"`, not a real directory),
    since those can't be recovered later by walking `file_path`'s own
    directory ancestors the way every other file's owner can."""
    subtree_file_count: dict[str, int] = defaultdict(int)
    direct_files: dict[str, list[str]] = defaultdict(list)
    children_of: dict[str, set[str]] = defaultdict(set)

    for file_path in file_paths:
        dir_path = _dir_of(file_path)
        direct_files[dir_path].append(file_path)
        ancestors = _ancestors_inclusive(dir_path)
        for ancestor in ancestors:
            subtree_file_count[ancestor] += 1
        for child, parent in zip(ancestors, ancestors[1:], strict=False):
            children_of[parent].add(child)

    registered: set[str] = set()
    file_to_virtual_owner: dict[str, str] = {}

    def register_direct_files(dir_path: str) -> None:
        """Registers `dir_path`'s own DIRECT files (never its
        descendants' — those are each `visit`'s own concern) either as
        `dir_path` itself, or split by filename prefix if there are more
        of them than `max_files_per_subsystem` — regardless of whether
        `dir_path` also has real subdirectories. A real Consul run found
        this matters even for a directory that DOES split by
        subdirectory: `agent/consul` has 175 files sitting flat in it
        AND one small real subdirectory (`autopilotevents/`) — without
        this, all 175 direct files were falling back to one flat
        `agent/consul` node regardless of the subdirectory split,
        because the old code only ever asked "are there any children",
        not "are there too many direct files"."""
        files = direct_files.get(dir_path, [])
        if not files:
            return
        if len(files) <= max_files_per_subsystem:
            registered.add(dir_path)
            return
        clusters: dict[str, list[str]] = defaultdict(list)
        for file_path in sorted(files):
            clusters[_filename_prefix(file_path)].append(file_path)
        if len(clusters) > 1:
            for prefix in sorted(clusters):
                virtual_path = f"{dir_path}::{prefix}"
                registered.add(virtual_path)
                for file_path in clusters[prefix]:
                    file_to_virtual_owner[file_path] = virtual_path
        else:
            # Every file shares the same prefix (or there's only one
            # file) — clustering wouldn't subdivide anything, so
            # there's nothing to gain from it, the same reasoning that
            # keeps a directory with no subdirectories from "splitting"
            # into itself.
            registered.add(dir_path)

    def visit(dir_path: str, depth: int) -> None:
        children = children_of.get(dir_path, set())
        over_threshold = (
            subtree_file_count[dir_path] > max_files_per_subsystem and depth < _MAX_TAXONOMY_DEPTH
        )

        if over_threshold and children:
            register_direct_files(dir_path)
            for child in sorted(children):
                visit(child, depth + 1)
        elif over_threshold and not children:
            register_direct_files(dir_path)
        else:
            registered.add(dir_path)

    visit("", 0)
    return registered, file_to_virtual_owner


def build_taxonomy(
    index: CodeIntelligenceIndex, max_files_per_subsystem: int = _MAX_FILES_PER_SUBSYSTEM
) -> SubsystemTaxonomy:
    """`max_files_per_subsystem` defaults to the empirically-calibrated
    module constant; exposed as a parameter mainly so tests can exercise
    the recursive-splitting mechanism itself against small synthetic
    fixtures without needing 50+ files to trigger it."""
    file_paths = sorted(_normalize(p) for p in index.file_analyses)

    registered_paths, file_to_virtual_owner = _register_subsystem_paths(
        file_paths, max_files_per_subsystem
    )

    # Sorted, not iterated straight off the set: dict/set iteration order
    # over a set built via repeated .add() is not guaranteed stable across
    # runs, and this order becomes SubsystemTaxonomy.nodes' own iteration
    # order — every downstream DRP stage (text corpus gathering, TF-IDF
    # document-frequency counting) walks `nodes` directly, so this is
    # where determinism either holds or breaks for the whole pipeline.
    nodes: dict[str, SubsystemNode] = {
        path: SubsystemNode(path=path, depth=0 if not path else path.count("/") + 1)
        for path in sorted(registered_paths)
    }

    file_to_subsystem: dict[str, str] = {}
    for file_path in file_paths:
        if file_path in file_to_virtual_owner:
            # Landed in a filename-prefix cluster (an oversized, flat,
            # subdirectory-less directory) — not recoverable by walking
            # real directory ancestors, since the owner isn't a real
            # directory at all.
            owner = file_to_virtual_owner[file_path]
        else:
            dir_path = _dir_of(file_path)
            owner = ""
            # Longest registered prefix of dir_path wins — checked from
            # the deepest plausible candidate down to root, so a file
            # several levels deeper than any registered node still
            # resolves to its nearest registered ancestor.
            segments = dir_path.split("/") if dir_path else []
            for depth in range(len(segments), 0, -1):
                candidate = "/".join(segments[:depth])
                if candidate in nodes:
                    owner = candidate
                    break
        file_to_subsystem[file_path] = owner
        nodes[owner].files.append(file_path)

    for file_path, analysis in index.file_analyses.items():
        owner = file_to_subsystem.get(_normalize(file_path))
        if owner is None:
            continue
        for symbol in analysis.symbols:
            if "." in symbol.qualified_name:
                prefix = symbol.qualified_name.rsplit(".", 1)[0]
                nodes[owner].package_namespaces.add(prefix)

    return SubsystemTaxonomy(nodes=nodes, file_to_subsystem=file_to_subsystem)
