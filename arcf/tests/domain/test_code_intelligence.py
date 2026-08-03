import pytest
from pydantic import ValidationError

from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)


def _location() -> SourceLocation:
    return SourceLocation(file_path="a.py", start_line=1, end_line=3)


def test_symbol_defaults() -> None:
    symbol = Symbol(
        id="a.py::Foo#1",
        name="Foo",
        qualified_name="Foo",
        kind=SymbolKind.CLASS,
        file_path="a.py",
        location=_location(),
    )
    assert symbol.base_names == []
    assert symbol.parent_id is None


def test_symbol_is_frozen() -> None:
    symbol = Symbol(
        id="a.py::Foo#1",
        name="Foo",
        qualified_name="Foo",
        kind=SymbolKind.CLASS,
        file_path="a.py",
        location=_location(),
    )
    with pytest.raises(ValidationError):
        symbol.name = "Bar"


def test_call_reference_allows_none_caller() -> None:
    call = CallReference(
        caller_id=None, callee_name="foo", file_path="a.py", location=_location()
    )
    assert call.caller_id is None


def test_import_reference_defaults() -> None:
    imp = ImportReference(source_file="a.py", raw_module="os", location=_location())
    assert imp.imported_names == []
    assert imp.resolved_file_path is None


def test_file_analysis_defaults() -> None:
    analysis = FileAnalysis(file_path="a.py", language="python")
    assert analysis.symbols == []
    assert analysis.calls == []
    assert analysis.imports == []
    assert analysis.parse_errors == []


def test_symbol_kind_values() -> None:
    assert {kind.value for kind in SymbolKind} == {"class", "function", "method", "interface"}
