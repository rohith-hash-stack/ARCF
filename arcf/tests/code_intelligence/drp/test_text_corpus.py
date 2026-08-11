from pathlib import Path

from code_intelligence.drp.text_corpus import gather_scoring_units
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.permissions import PermissionManager
from workspace.scanner import RepositoryScanner


def _build_index(tmp_path: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    return engine.build_index(tmp_path, scan.files)


def _gather(tmp_path: Path, max_symbols_per_file_document: int = 8):
    index = _build_index(tmp_path)
    permissions = PermissionManager(tmp_path)
    return gather_scoring_units(index, permissions, max_symbols_per_file_document)


def _go_gather(tmp_path: Path, max_symbols_per_file_document: int = 8):
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    index = engine.build_index(tmp_path, scan.files)
    permissions = PermissionManager(tmp_path)
    return gather_scoring_units(index, permissions, max_symbols_per_file_document)


def test_small_file_stays_as_a_single_scoring_unit(tmp_path: Path) -> None:
    (tmp_path / "small.py").write_text(
        "def a():\n    pass\n\ndef b():\n    pass\n"
    )

    unit_texts, file_to_units, _unit_usage = _gather(tmp_path)

    assert file_to_units["small.py"] == ["small.py"]
    assert "small.py" in unit_texts


def test_large_file_splits_into_one_unit_per_top_level_symbol(tmp_path: Path) -> None:
    body = "\n\n".join(
        f'class Loader{i}:\n    """Loader number {i}."""\n    pass' for i in range(10)
    )
    (tmp_path / "strategies.py").write_text(body)

    unit_texts, file_to_units, _unit_usage = _gather(tmp_path, max_symbols_per_file_document=8)

    units = file_to_units["strategies.py"]
    assert len(units) == 10
    assert all(u.startswith("strategies.py::") for u in units)
    assert all(u in unit_texts for u in units)


def test_split_units_dont_bleed_into_each_other(tmp_path: Path) -> None:
    # 9 classes forces a split (over the threshold=8); each has a
    # DISTINCT docstring — the whole point of splitting is that class 0's
    # unit contains only class 0's own vocabulary, not classes 1-8's too.
    classes = []
    for i in range(9):
        classes.append(
            f'class Loader{i}:\n    """Handles strategy number {i} specifically."""\n    pass'
        )
    (tmp_path / "strategies.py").write_text("\n\n".join(classes))

    unit_texts, file_to_units, _unit_usage = _gather(tmp_path, max_symbols_per_file_document=8)

    units_by_name = {}
    index = _build_index(tmp_path)
    for symbol in index.file_analyses["strategies.py"].symbols:
        units_by_name[symbol.name] = symbol.id

    loader0_text = unit_texts[units_by_name["Loader0"]]
    assert "strategy" in loader0_text.lower()
    assert "number 0" in loader0_text
    assert "number 1" not in loader0_text
    assert "number 8" not in loader0_text


def test_methods_contribute_to_their_class_unit_not_their_own(tmp_path: Path) -> None:
    classes = []
    for i in range(9):
        classes.append(
            f"class Loader{i}:\n    def distinctive_method_{i}(self):\n        pass"
        )
    (tmp_path / "strategies.py").write_text("\n\n".join(classes))

    unit_texts, file_to_units, _unit_usage = _gather(tmp_path, max_symbols_per_file_document=8)

    index = _build_index(tmp_path)
    symbol_id_by_name = {
        s.name: s.id for s in index.file_analyses["strategies.py"].symbols if s.parent_id is None
    }
    loader0_unit = unit_texts[symbol_id_by_name["Loader0"]]
    assert "distinctive_method_0" in loader0_unit


def test_file_at_exactly_the_threshold_does_not_split(tmp_path: Path) -> None:
    body = "\n\n".join(f"def f{i}():\n    pass" for i in range(8))
    (tmp_path / "exact.py").write_text(body)

    _, file_to_units, _unit_usage = _gather(tmp_path, max_symbols_per_file_document=8)

    assert file_to_units["exact.py"] == ["exact.py"]


def test_gather_scoring_units_is_deterministic(tmp_path: Path) -> None:
    body = "\n\n".join(f'class Loader{i}:\n    """Loader {i}."""\n    pass' for i in range(10))
    (tmp_path / "strategies.py").write_text(body)
    (tmp_path / "small.py").write_text("def a():\n    pass\n")

    first_texts, first_units, first_usage = _gather(tmp_path)
    second_texts, second_units, second_usage = _gather(tmp_path)

    assert first_texts == second_texts
    assert first_units == second_units
    assert first_usage == second_usage


def test_unit_usage_counts_incoming_calls_from_elsewhere(tmp_path: Path) -> None:
    (tmp_path / "impl.py").write_text("def helper():\n    return True\n")
    (tmp_path / "caller_a.py").write_text(
        "from .impl import helper\n\ndef use_it():\n    return helper()\n"
    )
    (tmp_path / "caller_b.py").write_text(
        "from .impl import helper\n\ndef use_it_too():\n    return helper()\n"
    )

    _, _, unit_usage = _gather(tmp_path)

    assert unit_usage["impl.py"] >= 2
    assert unit_usage["caller_a.py"] == 0


def test_unit_usage_excludes_same_named_symbol_with_no_locality(tmp_path: Path) -> None:
    # Two unrelated classes in unrelated packages both define `helper`.
    # ReferenceResolver.resolve() (which CallGraph itself uses, by
    # design — see reference_resolver.py's own module docstring) fans out
    # an ambiguous name to every same-named candidate, so uncorrected,
    # `Bar().helper()` in pkg2 would also count as a "caller" of pkg1's
    # entirely unrelated `Foo.helper`. The locality filter should exclude
    # it: pkg1 and pkg2 share no file, directory, or import relationship.
    (tmp_path / "pkg1").mkdir()
    (tmp_path / "pkg2").mkdir()
    (tmp_path / "pkg1" / "a.py").write_text(
        "class Foo:\n    def helper(self):\n        pass\n"
    )
    (tmp_path / "pkg2" / "b.py").write_text(
        "class Bar:\n    def helper(self):\n        pass\n\n"
        "def use():\n    return Bar().helper()\n"
    )

    _, _, unit_usage = _gather(tmp_path)

    assert unit_usage["pkg1/a.py"] == 0


def test_externally_declared_method_gets_its_own_unit_with_its_doc_comment(
    tmp_path: Path,
) -> None:
    # Go declares methods OUTSIDE their receiver type's own source range
    # (`func (w *Widget) Activate()`, separate from `type Widget
    # struct{...}`), unlike Python where a method is lexically nested
    # inside its class body — a real Consul run found a receiver
    # struct's own methods' doc comments were silently unreachable under
    # this shape (see text_corpus.py's own module docstring). Force a
    # split (9 top-level symbols, over the 8-symbol threshold) so
    # Widget's own unit is scored separately from the rest of the file.
    filler = "\n\n".join(f"func f{i}() {{}}" for i in range(8))
    source = (
        "package app\n\n"
        "type Widget struct {\n\tid int\n}\n\n"
        "// Activate turns the widget on and logs telemetry about the activation event.\n"
        "func (w *Widget) Activate() {\n\tdoStuff()\n}\n\n"
        f"{filler}\n"
    )
    (tmp_path / "widget.go").write_text(source)

    unit_texts, file_to_units, _unit_usage = _go_gather(tmp_path)

    units = file_to_units["widget.go"]
    activate_unit = next(u for u in units if "Widget.Activate#" in u)
    widget_unit = next(u for u in units if "::Widget#" in u)

    assert "Activate turns the widget on" in unit_texts[activate_unit]
    # The parent's own unit must NOT also carry the full comment — that
    # would reintroduce the pooling/dilution regression a real Consul
    # run found (11 methods' comments pooled into one struct unit
    # measurably lowered its real retrieval score) even though it also
    # fixed the original comment-loss bug.
    assert "Activate turns the widget on" not in unit_texts[widget_unit]
    assert "Activate" in unit_texts[widget_unit]


def test_zero_usage_split_method_borrows_a_floor_from_a_used_sibling(
    tmp_path: Path,
) -> None:
    # A framework-dispatched method (invoked by name/reflection through a
    # registration table, e.g. an RPC handler) structurally has zero
    # recorded callers no matter how central it is — CallGraph only sees
    # explicit call expressions. A real Consul run found 9 of a receiver
    # struct's 11 methods showed 0 own callers this way, even though the
    # struct itself was obviously live code. `Dispatched` below simulates
    # that: nothing calls it directly, but its sibling `Called` (same
    # receiver, `Widget`) genuinely is — real evidence `Widget` is live,
    # active code, which `Dispatched` should be able to borrow from.
    filler = "\n\n".join(f"func f{i}() {{}}" for i in range(7))
    source = (
        "package app\n\n"
        "type Widget struct {\n\tid int\n}\n\n"
        "func (w *Widget) Dispatched() {\n\tdoStuff()\n}\n\n"
        "func (w *Widget) Called() {\n\tdoOtherStuff()\n}\n\n"
        "func UseWidget(w *Widget) {\n\tw.Called()\n}\n\n"
        f"{filler}\n"
    )
    (tmp_path / "widget.go").write_text(source)

    _, file_to_units, unit_usage = _go_gather(tmp_path)

    units = file_to_units["widget.go"]
    dispatched_unit = next(u for u in units if "Widget.Dispatched#" in u)
    called_unit = next(u for u in units if "Widget.Called#" in u)

    assert unit_usage[called_unit] > 0
    assert unit_usage[dispatched_unit] == unit_usage[called_unit]
