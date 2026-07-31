import pytest
from pydantic import ValidationError

from domain.execution_context import ExecutionContext, TokenBudget
from domain.principal import Principal


def _principal() -> Principal:
    return Principal(id="alice", auth_method="api_key")


def test_token_budget_starts_with_zero_spend() -> None:
    budget = TokenBudget(max_usd=1.0)
    assert budget.spent_usd == 0.0
    assert budget.spent_tokens == 0
    assert budget.remaining_usd == 1.0


def test_token_budget_spend_returns_new_instance() -> None:
    original = TokenBudget(max_usd=1.0)
    spent = original.spend(usd=0.25, tokens=100)
    assert original.spent_usd == 0.0  # original untouched
    assert spent.spent_usd == 0.25
    assert spent.spent_tokens == 100
    assert spent.remaining_usd == 0.75


def test_token_budget_has_remaining() -> None:
    budget = TokenBudget(max_usd=1.0, spent_usd=0.9)
    assert budget.has_remaining(0.1) is True
    assert budget.has_remaining(0.11) is False


def test_token_budget_is_frozen() -> None:
    budget = TokenBudget(max_usd=1.0)
    with pytest.raises(ValidationError):
        budget.spent_usd = 5.0


def test_execution_context_defaults() -> None:
    context = ExecutionContext(principal=_principal(), budget=TokenBudget(max_usd=1.0))
    assert context.trace_id is None
    assert context.idempotency_key is None
    assert context.metadata == {}
    assert context.budget.spent_usd == 0.0


def test_execution_context_ids_are_unique() -> None:
    a = ExecutionContext(principal=_principal(), budget=TokenBudget(max_usd=1.0))
    b = ExecutionContext(principal=_principal(), budget=TokenBudget(max_usd=1.0))
    assert a.request_id != b.request_id


def test_with_trace_id_returns_new_instance() -> None:
    original = ExecutionContext(principal=_principal(), budget=TokenBudget(max_usd=1.0))
    updated = original.with_trace_id("abc123")
    assert original.trace_id is None
    assert updated.trace_id == "abc123"
    assert updated.request_id == original.request_id


def test_spend_returns_new_context_with_updated_budget() -> None:
    original = ExecutionContext(principal=_principal(), budget=TokenBudget(max_usd=1.0))
    updated = original.spend(usd=0.3, tokens=50)
    assert original.budget.spent_usd == 0.0
    assert updated.budget.spent_usd == 0.3
    assert updated.budget.spent_tokens == 50
    assert updated.request_id == original.request_id


def test_context_is_frozen() -> None:
    context = ExecutionContext(principal=_principal(), budget=TokenBudget(max_usd=1.0))
    with pytest.raises(ValidationError):
        context.trace_id = "not-allowed"
