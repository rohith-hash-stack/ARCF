from pathlib import Path

from code_intelligence.drp.taxonomy import build_taxonomy
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner


def _build_index(tmp_path: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    return engine.build_index(tmp_path, scan.files)


def _write(tmp_path: Path, relative_path: str, content: str) -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_small_repo_stays_as_a_single_subsystem_by_default(tmp_path: Path) -> None:
    # Well under the real _MAX_FILES_PER_SUBSYSTEM threshold — splitting
    # a handful of files into per-directory subsystems would only dilute
    # each one's vocabulary for no benefit, so the default behavior is
    # to NOT split when there's nothing to gain from it.
    _write(tmp_path, "main.py", "def entry():\n    pass\n")
    _write(tmp_path, "pkg/server/watcher.py", "def watch():\n    pass\n")
    _write(tmp_path, "pkg/client/api.py", "def call():\n    pass\n")

    taxonomy = build_taxonomy(_build_index(tmp_path))

    assert set(taxonomy.nodes) == {""}
    assert set(taxonomy.files_in("")) == {
        "main.py",
        "pkg/server/watcher.py",
        "pkg/client/api.py",
    }


def test_splits_into_top_and_second_level_when_forced(tmp_path: Path) -> None:
    _write(tmp_path, "main.py", "def entry():\n    pass\n")
    _write(tmp_path, "pkg/server/watcher.py", "def watch():\n    pass\n")
    _write(tmp_path, "pkg/client/api.py", "def call():\n    pass\n")

    # threshold=0 forces every directory with any children to split —
    # exercises the recursive mechanism without needing 50+ real files.
    taxonomy = build_taxonomy(_build_index(tmp_path), max_files_per_subsystem=0)

    assert set(taxonomy.nodes) == {"", "pkg/server", "pkg/client"}
    assert taxonomy.subsystem_of("main.py") == ""
    assert taxonomy.subsystem_of("pkg/server/watcher.py") == "pkg/server"
    assert taxonomy.subsystem_of("pkg/client/api.py") == "pkg/client"


def test_splits_deeper_than_two_levels_when_a_subtree_still_has_too_many_files(
    tmp_path: Path,
) -> None:
    # Mirrors the real Django/SQLAlchemy/vLLM cases: a package boundary
    # that sits three directories deep must become its own subsystem
    # once its parent's pooled file count crosses the threshold — not
    # get stuck at whatever depth a fixed cap would have stopped at.
    for i in range(3):
        _write(tmp_path, f"lib/pkg/orm/strategy{i}.py", f"def s{i}():\n    pass\n")
    for i in range(3):
        _write(tmp_path, f"lib/pkg/sql/compiler{i}.py", f"def c{i}():\n    pass\n")

    taxonomy = build_taxonomy(_build_index(tmp_path), max_files_per_subsystem=3)

    assert "lib/pkg/orm" in taxonomy.nodes
    assert "lib/pkg/sql" in taxonomy.nodes
    assert "lib/pkg" not in taxonomy.nodes  # split away, not registered itself
    assert taxonomy.subsystem_of("lib/pkg/orm/strategy0.py") == "lib/pkg/orm"
    assert taxonomy.subsystem_of("lib/pkg/sql/compiler0.py") == "lib/pkg/sql"


def test_stops_splitting_once_a_subtree_is_small_enough(tmp_path: Path) -> None:
    # lib/pkg has 6 files total (over threshold=3, so it splits), but
    # each of its two children has only 3 files (at, not over, the
    # threshold) — those children must NOT split further.
    for i in range(3):
        _write(tmp_path, f"lib/pkg/orm/a{i}.py", f"def a{i}():\n    pass\n")
        _write(tmp_path, f"lib/pkg/orm/deep/b{i}.py", f"def b{i}():\n    pass\n")

    taxonomy = build_taxonomy(_build_index(tmp_path), max_files_per_subsystem=3)

    # lib/pkg/orm itself has 3 direct + 3 in orm/deep = 6, over
    # threshold, so it splits further into orm/deep; but orm/deep (3
    # files, at the threshold, not over it) does not split again.
    assert "lib/pkg/orm/deep" in taxonomy.nodes
    assert taxonomy.subsystem_of("lib/pkg/orm/deep/b0.py") == "lib/pkg/orm/deep"


def test_direct_files_at_a_splitting_directory_still_get_a_home(tmp_path: Path) -> None:
    for i in range(3):
        _write(tmp_path, f"lib/pkg/orm/s{i}.py", f"def s{i}():\n    pass\n")
    for i in range(3):
        _write(tmp_path, f"lib/pkg/sql/c{i}.py", f"def c{i}():\n    pass\n")
    _write(tmp_path, "lib/pkg/__init__.py", "")

    taxonomy = build_taxonomy(_build_index(tmp_path), max_files_per_subsystem=3)

    # lib/pkg splits (too many files pooled across its children), but it
    # still owns its OWN direct file (__init__.py isn't inside orm/ or
    # sql/) — it must be registered too, not lost.
    assert "lib/pkg" in taxonomy.nodes
    assert taxonomy.subsystem_of("lib/pkg/__init__.py") == "lib/pkg"


def test_forced_splitting_registers_a_files_own_directory_when_nothing_deeper_exists(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "pkg/server/internal/deep.py", "def deep():\n    pass\n")

    # threshold=0 forces splitting at every level that has somewhere to
    # split into — a single file with no sibling directories bottoms out
    # at its own exact directory, which has no children left to split.
    taxonomy = build_taxonomy(_build_index(tmp_path), max_files_per_subsystem=0)

    assert taxonomy.subsystem_of("pkg/server/internal/deep.py") == "pkg/server/internal"
    assert "pkg/server/internal/deep.py" in taxonomy.files_in("pkg/server/internal")


def test_a_file_resolves_to_its_nearest_registered_ancestor_not_its_own_directory(
    tmp_path: Path,
) -> None:
    # pkg/server has enough files to split at threshold=2, but
    # pkg/server/internal/deep.py is the ONLY file under internal/ — that
    # single-file subtree (1 file, not over threshold=2) stays
    # unregistered on its own and resolves up to pkg/server/internal
    # itself once THAT has no further children needing a split, while a
    # sibling with real breadth (pkg/server/handlers/*) does split.
    _write(tmp_path, "pkg/server/internal/deep.py", "def deep():\n    pass\n")
    for i in range(3):
        _write(tmp_path, f"pkg/server/handlers/h{i}.py", f"def h{i}():\n    pass\n")

    # threshold=3, not 2: at 2, handlers/ (3 files, no subdirectories of
    # its own) would exceed the threshold and trigger filename-prefix
    # splitting instead — h0/h1/h2 share no common prefix, so that's a
    # different, real mechanism (see test_taxonomy.py's own dedicated
    # prefix-splitting tests), not what THIS test is about.
    taxonomy = build_taxonomy(_build_index(tmp_path), max_files_per_subsystem=3)

    assert taxonomy.subsystem_of("pkg/server/internal/deep.py") == "pkg/server/internal"
    assert taxonomy.subsystem_of("pkg/server/handlers/h0.py") == "pkg/server/handlers"


def test_package_namespaces_collected_from_dotted_qualified_names(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/server/watcher.py",
        "class Watcher:\n    def poll(self):\n        pass\n",
    )

    taxonomy = build_taxonomy(_build_index(tmp_path), max_files_per_subsystem=0)

    node = taxonomy.nodes["pkg/server"]
    assert "Watcher" in node.package_namespaces


def test_taxonomy_is_deterministic_across_runs(tmp_path: Path) -> None:
    _write(tmp_path, "a/one.py", "def a():\n    pass\n")
    _write(tmp_path, "b/two.py", "def b():\n    pass\n")
    _write(tmp_path, "c/three.py", "def c():\n    pass\n")

    index = _build_index(tmp_path)
    first = build_taxonomy(index, max_files_per_subsystem=0)
    second = build_taxonomy(index, max_files_per_subsystem=0)

    assert list(first.nodes) == list(second.nodes)
    assert first.file_to_subsystem == second.file_to_subsystem


def test_flat_oversized_directory_splits_by_filename_prefix(tmp_path: Path) -> None:
    # Mirrors the real Consul case: agent/consul is a flat Go package —
    # 175 files, no subdirectories at all. catalog_endpoint.go,
    # catalog_endpoint_ce.go, and catalog_endpoint_test.go share the
    # "catalog" prefix; acl_replication.go and acl_test.go share "acl".
    # (Written as .py here only because this file's _build_index helper
    # registers PythonLanguageAnalyzer — the splitting logic itself
    # never looks at language, only filenames.)
    for name in ["catalog_endpoint.py", "catalog_endpoint_ce.py", "catalog_endpoint_test.py"]:
        _write(tmp_path, f"agent/consul/{name}", "def x():\n    pass\n")
    for name in ["acl_replication.py", "acl_test.py"]:
        _write(tmp_path, f"agent/consul/{name}", "def y():\n    pass\n")

    taxonomy = build_taxonomy(_build_index(tmp_path), max_files_per_subsystem=3)

    assert "agent/consul" not in taxonomy.nodes
    assert "agent/consul::catalog" in taxonomy.nodes
    assert "agent/consul::acl" in taxonomy.nodes
    assert taxonomy.subsystem_of("agent/consul/catalog_endpoint.py") == "agent/consul::catalog"
    assert taxonomy.subsystem_of("agent/consul/catalog_endpoint_ce.py") == "agent/consul::catalog"
    assert taxonomy.subsystem_of("agent/consul/acl_test.py") == "agent/consul::acl"
    assert set(taxonomy.files_in("agent/consul::catalog")) == {
        "agent/consul/catalog_endpoint.py",
        "agent/consul/catalog_endpoint_ce.py",
        "agent/consul/catalog_endpoint_test.py",
    }


def test_direct_files_of_a_splitting_directory_are_also_prefix_clustered(
    tmp_path: Path,
) -> None:
    # A real Consul run found this exact shape: agent/consul has 175
    # files sitting flat in it AND one small real subdirectory
    # (autopilotevents/) — a directory splitting by real subdirectory
    # must ALSO prefix-cluster its own oversized set of direct files,
    # not fall back to dumping all of them into one flat node just
    # because a subdirectory happened to exist too.
    for name in ["catalog_endpoint.py", "catalog_endpoint_ce.py", "catalog_endpoint_test.py"]:
        _write(tmp_path, f"agent/consul/{name}", "def x():\n    pass\n")
    for name in ["acl_replication.py", "acl_test.py"]:
        _write(tmp_path, f"agent/consul/{name}", "def y():\n    pass\n")
    _write(tmp_path, "agent/consul/state/catalog.py", "def z():\n    pass\n")

    taxonomy = build_taxonomy(_build_index(tmp_path), max_files_per_subsystem=3)

    assert "agent/consul" not in taxonomy.nodes
    assert "agent/consul::catalog" in taxonomy.nodes
    assert "agent/consul::acl" in taxonomy.nodes
    assert "agent/consul/state" in taxonomy.nodes
    assert taxonomy.subsystem_of("agent/consul/catalog_endpoint.py") == "agent/consul::catalog"
    assert taxonomy.subsystem_of("agent/consul/state/catalog.py") == "agent/consul/state"


def test_flat_directory_where_every_file_shares_one_prefix_does_not_split(
    tmp_path: Path,
) -> None:
    # All four files reduce to the same prefix ("acl") — clustering
    # wouldn't subdivide anything, so it's skipped, the same way a
    # directory with no subdirectories at all is left alone.
    for name in ["acl.py", "acl_ce.py", "acl_test.py", "acl_endpoint.py"]:
        _write(tmp_path, f"agent/consul/{name}", "def x():\n    pass\n")

    taxonomy = build_taxonomy(_build_index(tmp_path), max_files_per_subsystem=3)

    assert "agent/consul" in taxonomy.nodes
    assert taxonomy.subsystem_of("agent/consul/acl.py") == "agent/consul"


def test_prefix_split_taxonomy_is_deterministic(tmp_path: Path) -> None:
    names = ["catalog_endpoint.py", "catalog_endpoint_ce.py", "acl_replication.py", "acl_test.py"]
    for name in names:
        _write(tmp_path, f"agent/consul/{name}", "def x():\n    pass\n")

    index = _build_index(tmp_path)
    first = build_taxonomy(index, max_files_per_subsystem=3)
    second = build_taxonomy(index, max_files_per_subsystem=3)

    assert list(first.nodes) == list(second.nodes)
    assert first.file_to_subsystem == second.file_to_subsystem


def test_depth_cap_guarantees_termination_on_a_deeply_nested_tree(tmp_path: Path) -> None:
    deep_path = "/".join(f"d{i}" for i in range(12)) + "/leaf.py"
    _write(tmp_path, deep_path, "def leaf():\n    pass\n")

    # Should not recurse forever or raise despite 12 real directory
    # levels and a threshold of 0 (forces splitting at every level it's
    # allowed to).
    taxonomy = build_taxonomy(_build_index(tmp_path), max_files_per_subsystem=0)

    assert taxonomy.subsystem_of(deep_path.replace("\\", "/")) is not None
    assert max(node.depth for node in taxonomy.nodes.values()) <= 6
