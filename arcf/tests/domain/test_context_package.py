from uuid import uuid4

import pytest
from pydantic import ValidationError

from domain.context_package import ContextPackage, PackagedFile


def _packaged_file() -> PackagedFile:
    return PackagedFile(
        file_path="a.py",
        content="def a(): pass",
        relevance_score=0.9,
        reason="defines a",
        token_count=10,
        truncated=False,
    )


def test_context_package_defaults() -> None:
    package = ContextPackage(
        contract_id="c1",
        workspace_id="ws1",
        context_resolution_id=uuid4(),
        budget_max_tokens=1000,
        budget_used_tokens=0,
        prompt_compression_ratio=0.0,
        excluded_file_count=0,
    )
    assert package.relevant_files == []
    assert package.dependency_chain == []
    assert package.understanding_notes == []


def test_context_package_is_frozen() -> None:
    package = ContextPackage(
        contract_id="c1",
        workspace_id="ws1",
        context_resolution_id=uuid4(),
        budget_max_tokens=1000,
        budget_used_tokens=0,
        prompt_compression_ratio=0.0,
        excluded_file_count=0,
    )
    with pytest.raises(ValidationError):
        package.budget_used_tokens = 5


def test_packaged_file_shape() -> None:
    file = _packaged_file()
    assert file.truncated is False
    assert file.token_count == 10


def test_packaged_file_relevance_score_bounds() -> None:
    with pytest.raises(ValidationError):
        PackagedFile(
            file_path="a.py",
            content="x",
            relevance_score=1.5,
            reason="defines a",
            token_count=1,
            truncated=False,
        )
