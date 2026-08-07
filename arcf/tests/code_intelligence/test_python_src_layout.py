from code_intelligence.python_src_layout import resolve_with_src_layout


def test_resolves_plain_absolute_import_in_src_layout() -> None:
    files = frozenset({"src/mypackage/utils.py"})
    assert resolve_with_src_layout("mypackage.utils", [], files) == "src/mypackage/utils.py"


def test_resolves_from_import_via_imported_name() -> None:
    files = frozenset({"src/mypackage/utils.py"})
    assert resolve_with_src_layout("mypackage", ["utils"], files) == "src/mypackage/utils.py"


def test_resolves_package_init() -> None:
    files = frozenset({"src/mypackage/__init__.py"})
    assert resolve_with_src_layout("mypackage", [], files) == "src/mypackage/__init__.py"


def test_relative_import_is_never_touched() -> None:
    files = frozenset({"src/mypackage/utils.py"})
    assert resolve_with_src_layout(".utils", [], files) is None


def test_wildcard_import_only_tries_base_module() -> None:
    files = frozenset({"src/mypackage/__init__.py"})
    assert resolve_with_src_layout("mypackage", ["*"], files) == "src/mypackage/__init__.py"


def test_returns_none_when_nothing_matches() -> None:
    files = frozenset({"src/other/utils.py"})
    assert resolve_with_src_layout("mypackage.utils", [], files) is None


def test_returns_none_for_empty_module() -> None:
    files = frozenset({"src/mypackage/utils.py"})
    assert resolve_with_src_layout("", [], files) is None
