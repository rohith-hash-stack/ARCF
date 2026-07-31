import pytest
from pydantic import ValidationError

from domain.code_intelligence import SymbolKind
from domain.context_resolution import (
    CallEdge,
    ContextResolutionResult,
    DependencyEdge,
    FileReference,
    SymbolReference,
    TokenEstimate,
)


def _token_estimate() -> TokenEstimate:
    return TokenEstimate(
        raw_context_tokens=1000, selected_context_tokens=100, compression_ratio=0.1
    )


def test_result_defaults() -> None:
    result = ContextResolutionResult(
        workspace_id="ws",
        contract_id="c1",
        repository_root="/repo",
        language="python",
        confidence=0.9,
        token_estimate=_token_estimate(),
        resolution_reason="test",
    )
    assert result.candidate_files == []
    assert result.impacted_symbols == []
    assert result.dependency_chain == []
    assert result.call_chain == []
    assert result.entry_points == []


def test_result_is_frozen() -> None:
    result = ContextResolutionResult(
        workspace_id="ws",
        contract_id="c1",
        repository_root="/repo",
        language="python",
        confidence=0.9,
        token_estimate=_token_estimate(),
        resolution_reason="test",
    )
    with pytest.raises(ValidationError):
        result.confidence = 0.1


def test_confidence_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        ContextResolutionResult(
            workspace_id="ws",
            contract_id="c1",
            repository_root="/repo",
            language="python",
            confidence=1.5,
            token_estimate=_token_estimate(),
            resolution_reason="test",
        )


def test_ids_are_unique_per_result() -> None:
    kwargs = dict(
        workspace_id="ws",
        contract_id="c1",
        repository_root="/repo",
        language="python",
        confidence=0.9,
        token_estimate=_token_estimate(),
        resolution_reason="test",
    )
    a = ContextResolutionResult(**kwargs)  # type: ignore[arg-type]
    b = ContextResolutionResult(**kwargs)  # type: ignore[arg-type]
    assert a.id != b.id


def test_file_reference_shape() -> None:
    ref = FileReference(file_path="a.py", reason="defines foo", language="python", token_count=42)
    assert ref.file_path == "a.py"


def test_symbol_reference_reuses_symbol_kind() -> None:
    ref = SymbolReference(
        symbol_id="a.py::foo",
        name="foo",
        qualified_name="foo",
        kind=SymbolKind.FUNCTION,
        file_path="a.py",
        start_line=1,
        end_line=2,
    )
    assert ref.kind is SymbolKind.FUNCTION


def test_dependency_edge_shape() -> None:
    edge = DependencyEdge(from_file="a.py", to_file="b.py")
    assert edge.from_file == "a.py"
    assert edge.to_file == "b.py"


def test_call_edge_allows_none_caller() -> None:
    edge = CallEdge(caller_symbol_id=None, callee_symbol_id="a.py::foo", file_path="a.py")
    assert edge.caller_symbol_id is None


def test_token_estimate_shape() -> None:
    estimate = _token_estimate()
    assert estimate.raw_context_tokens == 1000
    assert estimate.selected_context_tokens == 100
    assert estimate.compression_ratio == 0.1
