"""End-to-end HTTP tests for POST /contracts/{id}/grounded-execution
(architecture closure, 2026-08-16) -- the canonical entry point,
constructed through the real create_app() composition root, real
TestClient, only litellm.acompletion faked. Same convention as
tests/interfaces/test_context_package_route.py.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import litellm
import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from shared.config import Settings

_INTENT_PAYLOAD: dict[str, object] = {
    "intent_summary": "add input validation",
    "domain": "backend",
    "task": "feature",
    "entities": ["authenticate"],
    "constraints": [],
    "assumptions": [],
    "self_reported_confidence": 0.9,
    "suggested_clarifying_questions": [],
}
_UNDERSTANDING_PAYLOAD: dict[str, object] = {
    "summary": "auth.py defines authenticate, called from login.py.",
    "key_relationships": ["login.py -> auth.py"],
}
_GENERATION_CONTENT = "Modified `auth.py` to add a null check."


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


@pytest.fixture
def patched_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        messages = kwargs.get("messages", [])
        prompt = messages[0]["content"] if messages else ""  # type: ignore[index]
        if "Dependency relationships among the selected files:" in prompt:
            return _fake_response(_GENERATION_CONTENT)
        if "key_relationships" in prompt:
            return _fake_response(json.dumps(_UNDERSTANDING_PAYLOAD))
        return _fake_response(json.dumps(_INTENT_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)


def _build_client(tmp_path: Path, **settings_overrides: object) -> TestClient:
    defaults: dict[str, object] = {
        "api_keys_raw": "testkey:alice",
        "rate_limit_capacity": 100,
        "rate_limit_refill_per_second": 100.0,
        "cost_guardrail_max_usd": 10.0,
        "contract_store_path": str(tmp_path / "contracts.db"),
        "context_resolution_store_path": str(tmp_path / "context_resolutions.db"),
    }
    defaults.update(settings_overrides)
    settings = Settings(**defaults)  # type: ignore[arg-type]
    return TestClient(create_app(settings))


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (repo / "login.py").write_text(
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )
    return repo


def test_grounded_execution_missing_credentials_rejected(
    tmp_path: Path, patched_llm: None
) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/contracts/00000000-0000-0000-0000-000000000000/grounded-execution",
        json={},
    )
    assert response.status_code == 401


def test_grounded_execution_unknown_contract_returns_404(
    tmp_path: Path, patched_llm: None
) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/contracts/00000000-0000-0000-0000-000000000000/grounded-execution",
        json={},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 404


def test_grounded_execution_full_pipeline_reaches_generated_verified_answer(
    tmp_path: Path, patched_llm: None
) -> None:
    """The definitive end-to-end proof: a single HTTP call, starting from
    only a contract_id, reaches a real generated + verified answer --
    the exact connection (Context -> Generation) the architecture audit
    found completely missing from the deployed API."""
    repo = _make_repo(tmp_path)
    client = _build_client(tmp_path)

    created = client.post(
        "/api/v1/contracts",
        json={"raw_request": "Please add input validation to the greeting handler"},
        headers={"X-API-Key": "testkey"},
    )
    assert created.status_code == 200
    contract_id = created.json()["contract_id"]

    response = client.post(
        f"/api/v1/contracts/{contract_id}/grounded-execution",
        json={"target_names": ["authenticate"], "workspace_root": str(repo)},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    body = response.json()
    result = body["result"]

    assert result["final_status"] == "success"
    assert result["artifact"]["content"] == _GENERATION_CONTENT
    assert result["verification"]["status"] == "sufficient"
    assert result["recovery_attempts"] == 0
    assert result["strategy_used"] == "classic"
    assert body["remaining_budget_usd"] < 10.0
    # 2026-08-17 hardening: internal/raw LLM call content (including any
    # discarded attempts and SLM-2's internal notes) must not leak into
    # the client-facing response -- it's still recorded in the ledger.
    assert "llm_responses" not in result

    # Real ledger entry, real production store -- observable execution,
    # not just an HTTP response nobody persists.
    ledger_response = client.get(
        f"/api/v1/executions/{result['request_id']}", headers={"X-API-Key": "testkey"}
    )
    assert ledger_response.status_code == 200
    assert ledger_response.json()["contract_id"] == contract_id


def test_grounded_execution_cost_guardrail_rejects_tight_budget(
    tmp_path: Path, patched_llm: None
) -> None:
    """2026-08-17 hardening: previously untested entirely -- confirms the
    pre-flight guardrail (now scaled to the real worst-case call count,
    not just one short-prompt call) actually rejects a request when the
    configured budget genuinely can't cover it."""
    repo = _make_repo(tmp_path)
    db_path = str(tmp_path / "contracts.db")

    setup_client = _build_client(tmp_path, contract_store_path=db_path)
    created = setup_client.post(
        "/api/v1/contracts",
        json={"raw_request": "Please add input validation to the greeting handler"},
        headers={"X-API-Key": "testkey"},
    )
    contract_id = created.json()["contract_id"]

    tight_client = _build_client(
        tmp_path, contract_store_path=db_path, cost_guardrail_max_usd=0.0000001
    )
    response = tight_client.post(
        f"/api/v1/contracts/{contract_id}/grounded-execution",
        json={"target_names": ["authenticate"], "workspace_root": str(repo)},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 402


def test_cost_guardrail_rejects_budget_the_undercounted_formula_would_have_passed(
    tmp_path: Path, patched_llm: None
) -> None:
    """G-new-1 (2026-08-17 independent verification report): the
    pre-2026-08-17 formula assumed a worst case of 4 real LLM calls
    ("2 per attempt x up to 2 attempts"). Traced against the actual
    implementation (SLM-2's own parse-retries, each internally retried by
    LiteLLMClient, plus generation's own LiteLLMClient retries, x
    recovery passes), the real worst case at this project's defaults is
    18. A budget sized to comfortably cover the OLD estimate but not the
    real one must now be rejected -- proving the fix changed actual
    guardrail behavior, not just a comment."""
    from infrastructure.cost import CostEstimator

    estimator = CostEstimator()
    max_tokens = 2000
    prompt_tokens_per_call = min(max_tokens, 8000)

    old_worst_case_calls = 4  # the pre-fix formula's flat assumption
    old_estimate = estimator.estimate(
        "word " * prompt_tokens_per_call,
        "gpt-4o-mini",
        assumed_completion_tokens=800 * old_worst_case_calls,
    )
    new_worst_case_calls = (2 * 3 + 3) * (1 + 1)  # traced formula at this project's defaults
    assert new_worst_case_calls == 18
    new_estimate = estimator.estimate(
        "word " * (prompt_tokens_per_call * new_worst_case_calls),
        "gpt-4o-mini",
        assumed_completion_tokens=800 * new_worst_case_calls,
    )
    assert new_estimate.estimated_cost_usd > old_estimate.estimated_cost_usd

    budget = (old_estimate.estimated_cost_usd + new_estimate.estimated_cost_usd) / 2

    repo = _make_repo(tmp_path)
    db_path = str(tmp_path / "contracts.db")
    setup_client = _build_client(tmp_path, contract_store_path=db_path)
    created = setup_client.post(
        "/api/v1/contracts",
        json={"raw_request": "Please add input validation to the greeting handler"},
        headers={"X-API-Key": "testkey"},
    )
    contract_id = created.json()["contract_id"]

    client = _build_client(tmp_path, contract_store_path=db_path, cost_guardrail_max_usd=budget)
    response = client.post(
        f"/api/v1/contracts/{contract_id}/grounded-execution",
        json={
            "target_names": ["authenticate"],
            "workspace_root": str(repo),
            "max_tokens": max_tokens,
        },
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 402


def test_grounded_execution_without_workspace_returns_400(
    tmp_path: Path, patched_llm: None
) -> None:
    client = _build_client(tmp_path)
    created = client.post(
        "/api/v1/contracts",
        json={"raw_request": "Please add input validation to the greeting handler"},
        headers={"X-API-Key": "testkey"},
    )
    contract_id = created.json()["contract_id"]

    response = client.post(
        f"/api/v1/contracts/{contract_id}/grounded-execution",
        json={"target_names": ["authenticate"]},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 400


def test_grounded_execution_with_nonexistent_workspace_root_returns_400(
    tmp_path: Path, patched_llm: None
) -> None:
    """G-new-7 (2026-08-17 independent verification report): distinct
    negative path from the "no workspace at all" case above --
    workspace_root is PROVIDED but doesn't exist on disk. Verifies the
    actual contract for this case (WorkspacePathError ->  400 at the real
    HTTP boundary the orchestrator's own docstring documents, not an
    invented validation rule)."""
    client = _build_client(tmp_path)
    created = client.post(
        "/api/v1/contracts",
        json={"raw_request": "Please add input validation to the greeting handler"},
        headers={"X-API-Key": "testkey"},
    )
    contract_id = created.json()["contract_id"]

    response = client.post(
        f"/api/v1/contracts/{contract_id}/grounded-execution",
        json={
            "target_names": ["authenticate"],
            "workspace_root": str(tmp_path / "this_path_does_not_exist"),
        },
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 400


def test_grounded_execution_llm_invocation_error_propagates_as_502(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-new-7 (2026-08-17 independent verification report): LLM error
    propagation was genuinely untested at the actual public boundary.
    Verifies the real end-to-end HTTP semantics -- a permanent provider
    failure during the one unwrapped LLM call in the pipeline
    (FinalGenerationRunner.generate(), see grounded_execution.py's own
    except clause) surfaces as a real 502 with a real error detail, not
    just an internal exception asserted in isolation."""

    async def failing_acompletion(**kwargs: object) -> SimpleNamespace:
        messages = kwargs.get("messages", [])
        prompt = messages[0]["content"] if messages else ""  # type: ignore[index]
        if "Dependency relationships among the selected files:" in prompt:
            raise RuntimeError("simulated permanent provider outage")
        if "key_relationships" in prompt:
            return _fake_response(json.dumps(_UNDERSTANDING_PAYLOAD))
        return _fake_response(json.dumps(_INTENT_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", failing_acompletion)

    repo = _make_repo(tmp_path)
    client = _build_client(tmp_path)
    created = client.post(
        "/api/v1/contracts",
        json={"raw_request": "Please add input validation to the greeting handler"},
        headers={"X-API-Key": "testkey"},
    )
    contract_id = created.json()["contract_id"]

    response = client.post(
        f"/api/v1/contracts/{contract_id}/grounded-execution",
        json={"target_names": ["authenticate"], "workspace_root": str(repo)},
        headers={"X-API-Key": "testkey"},
    )

    assert response.status_code == 502
    assert "simulated permanent provider outage" in response.json()["detail"]
