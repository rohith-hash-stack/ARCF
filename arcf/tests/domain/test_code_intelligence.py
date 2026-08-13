import pytest
from pydantic import ValidationError

from domain.code_intelligence import (
    CallReference,
    CallResolutionConfidence,
    ConfigReference,
    DecoratorReference,
    ExternalLibraryReference,
    FileAnalysis,
    ImportReference,
    ImportResolutionKind,
    Route,
    SourceLocation,
    SQLReference,
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


# --- ARCF-DI Phase 1: evidence-layer schema extensions --------------------
#
# These additive fields/types must not change any behavior for an existing
# consumer that doesn't know about them yet (see the module docstring and
# tests above, which are untouched and still pass). What they add is
# content-derived, self-describing evidence ids, and schema placeholders
# for facts later ARCF-DI phases will populate — never guessed at here.


def test_call_reference_id_is_content_derived_and_reproducible() -> None:
    """Same evidence in -> same id out, across independently constructed
    instances. This is the literal unit-level form of the "byte-identical
    across repeated runs" acceptance test: an id must be a pure function
    of the fields it describes, not of construction order or identity."""
    loc = _location()
    a = CallReference(
        caller_id="a.py::foo#1", callee_name="authenticate", file_path="a.py", location=loc
    )
    b = CallReference(
        caller_id="a.py::bar#9", callee_name="authenticate", file_path="a.py", location=loc
    )
    assert a.id == b.id == "call:a.py::authenticate#1-3"


def test_call_reference_resolution_fields_default_unset() -> None:
    call = CallReference(caller_id=None, callee_name="foo", file_path="a.py", location=_location())
    assert call.resolution_confidence is None
    assert call.candidates == []


def test_call_reference_ambiguous_candidates_preserved_when_set() -> None:
    call = CallReference(
        caller_id=None,
        callee_name="New",
        file_path="a.py",
        location=_location(),
        resolution_confidence=CallResolutionConfidence.AMBIGUOUS_MULTI,
        candidates=["pkg1.go::New#4", "pkg2.go::New#9"],
    )
    assert call.resolution_confidence is CallResolutionConfidence.AMBIGUOUS_MULTI
    assert call.candidates == ["pkg1.go::New#4", "pkg2.go::New#9"]


def test_import_reference_id_and_resolution_fields_default_unset() -> None:
    imp = ImportReference(source_file="a.py", raw_module="axios", location=_location())
    assert imp.id == "import:a.py::axios#1"
    assert imp.resolved_kind is None
    assert imp.resolved_library is None


def test_import_reference_resolved_kind_settable() -> None:
    imp = ImportReference(
        source_file="a.py",
        raw_module="axios",
        location=_location(),
        resolved_kind=ImportResolutionKind.EXTERNAL,
        resolved_library="axios",
    )
    assert imp.resolved_kind is ImportResolutionKind.EXTERNAL
    assert imp.resolved_library == "axios"


def test_decorator_reference_id_is_content_derived() -> None:
    dec = DecoratorReference(
        symbol_id="a.py::handler#5",
        decorator_name="app.route",
        file_path="a.py",
        location=_location(),
    )
    assert dec.id == "decorator:a.py::app.route@a.py::handler#5#1"


def test_external_library_reference_id_and_defaults() -> None:
    ext = ExternalLibraryReference(library_name="axios", manifest_location=_location())
    assert ext.id == "extlib:axios@unpinned"
    assert ext.used_by == []
    assert ext.api_surface_used == []

    pinned = ExternalLibraryReference(
        library_name="axios", library_version="1.7.2", manifest_location=_location()
    )
    assert pinned.id == "extlib:axios@1.7.2"


def test_route_id_reflects_method_and_path() -> None:
    route = Route(
        method="GET",
        path_template="/users/:id",
        handler_symbol_id="a.py::get_user#1",
        location=_location(),
    )
    assert route.id == "route:a.py::GET /users/:id#1"


def test_config_reference_id_and_key() -> None:
    ref = ConfigReference(
        key="DATABASE_URL", referencing_symbol_id="a.py::connect#1", location=_location()
    )
    assert ref.key == "DATABASE_URL"
    assert ref.id == "config:a.py::DATABASE_URL#1"


def test_sql_reference_defaults_not_reconstructed() -> None:
    sql = SQLReference(
        raw_query_text="SELECT * FROM users",
        referencing_symbol_id="a.py::get_users#1",
        location=_location(),
    )
    assert sql.reconstructed is False
    assert sql.tables_referenced == []
    assert sql.id == "sql:a.py#1-3"


def test_new_evidence_types_are_frozen() -> None:
    ext = ExternalLibraryReference(library_name="axios", manifest_location=_location())
    with pytest.raises(ValidationError):
        ext.library_name = "requests"  # type: ignore[misc]


def test_file_analysis_new_evidence_fields_default_empty() -> None:
    """Mirrors decorators' own established rollout pattern: additive,
    empty-by-default, so no existing FileAnalysis consumer is affected."""
    analysis = FileAnalysis(file_path="a.py", language="python")
    assert analysis.external_library_references == []
    assert analysis.routes == []
    assert analysis.config_references == []
    assert analysis.sql_references == []
