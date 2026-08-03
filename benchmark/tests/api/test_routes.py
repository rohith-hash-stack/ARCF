"""Integration tests for the benchmark API — exercises the FULL app.py
wiring (both runners, the real ARCF pipeline classes, the analyzer)
with litellm mocked, matching ARCF's own test pattern. This is what
proves the whole assembly works end-to-end on a controlled response,
complementing the live click-through smoke test (which could only
prove the wiring reaches the LLM boundary, not what happens on success,
since no real provider credentials are configured in this environment).
"""

import json
from pathlib import Path
from types import SimpleNamespace

import litellm
import pytest
from fastapi.testclient import TestClient

from benchmark.api.app import create_app
from benchmark.config import BenchmarkSettings

_INTENT_PAYLOAD = {
    "intent_summary": "fix login bug",
    "domain": "backend",
    "task": "bug_fix",
    "entities": ["authenticate"],
    "constraints": [],
    "assumptions": [],
    "self_reported_confidence": 0.9,
    "suggested_clarifying_questions": [],
}


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


@pytest.fixture
def patched_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        if kwargs.get("response_format") is not None:
            return _fake_response(json.dumps(_INTENT_PAYLOAD))
        return _fake_response("diff --git a/auth.py b/auth.py\n+ fixed")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)


@pytest.fixture
def patched_ollama_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulates a local Ollama daemon with the priority-1 candidate
    installed, without touching a real daemon — hermetic, same
    rationale as patched_llm mocking litellm."""

    def fake_get(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"models": [{"name": "qwen2.5:1.5b-instruct"}]},
        )

    monkeypatch.setattr("benchmark.local_slm.ollama_provider.httpx.get", fake_get)


@pytest.fixture
def patched_ollama_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"models": []})

    monkeypatch.setattr("benchmark.local_slm.ollama_provider.httpx.get", fake_get)


def _build_client(tmp_path: Path) -> TestClient:
    settings = BenchmarkSettings(
        clone_root=str(tmp_path / "clones"), store_path=str(tmp_path / "runs.db")
    )
    return TestClient(create_app(settings))


def _make_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (repo_dir / "login.py").write_text(
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )
    return repo_dir


def test_load_local_repository(tmp_path: Path, patched_llm: None) -> None:
    repo_dir = _make_repo(tmp_path)
    client = _build_client(tmp_path)

    response = client.post(
        "/api/repository/load", json={"source": "local", "path": str(repo_dir)}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["file_count"] == 2
    assert body["is_git_repo"] is False


def test_load_repository_missing_path_returns_400(tmp_path: Path, patched_llm: None) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/repository/load", json={"source": "local", "path": str(tmp_path / "nope")}
    )
    assert response.status_code == 400


def test_run_benchmark_both_modes_end_to_end(tmp_path: Path, patched_llm: None) -> None:
    repo_dir = _make_repo(tmp_path)
    client = _build_client(tmp_path)

    response = client.post(
        "/api/benchmark/run",
        json={
            "repository_root": str(repo_dir),
            "task": "fix the authenticate function",
            "modes": ["direct", "arcf"],
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["direct"]["mode"] == "direct"
    assert body["arcf"]["mode"] == "arcf"
    assert body["direct"]["generated_output"].startswith("diff --git")
    assert body["arcf"]["contract"] is not None
    assert body["arcf"]["context_resolution"] is not None
    assert body["arcf"]["context_package"] is not None
    assert (
        body["arcf"]["context_metrics"]["files_sent_to_llm"]
        <= body["direct"]["context_metrics"]["files_sent_to_llm"]
    )
    assert body["token_reduction_pct"] is not None


def test_run_benchmark_single_mode(tmp_path: Path, patched_llm: None) -> None:
    repo_dir = _make_repo(tmp_path)
    client = _build_client(tmp_path)

    response = client.post(
        "/api/benchmark/run",
        json={"repository_root": str(repo_dir), "task": "fix bug", "modes": ["arcf"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["arcf"] is not None
    assert body["direct"] is None
    assert body["token_reduction_pct"] is None


def test_reports_are_persisted_and_retrievable(tmp_path: Path, patched_llm: None) -> None:
    repo_dir = _make_repo(tmp_path)
    client = _build_client(tmp_path)

    run_response = client.post(
        "/api/benchmark/run",
        json={"repository_root": str(repo_dir), "task": "fix bug", "modes": ["direct"]},
    )
    report_id = run_response.json()["id"]

    list_response = client.get("/api/benchmark/reports")
    assert any(r["id"] == report_id for r in list_response.json())

    get_response = client.get(f"/api/benchmark/reports/{report_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == report_id


def test_get_unknown_report_returns_404(tmp_path: Path, patched_llm: None) -> None:
    client = _build_client(tmp_path)
    response = client.get("/api/benchmark/reports/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_local_slm_status_reports_unavailable_reason(
    tmp_path: Path, patched_llm: None, patched_ollama_unavailable: None
) -> None:
    client = _build_client(tmp_path)
    response = client.get("/api/local-slm/status")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "ollama pull" in body["reason"]


def test_local_slm_status_reports_available(
    tmp_path: Path, patched_llm: None, patched_ollama_available: None
) -> None:
    client = _build_client(tmp_path)
    response = client.get("/api/local-slm/status")
    assert response.json() == {"available": True, "reason": None}


def test_run_benchmark_all_three_modes_end_to_end(
    tmp_path: Path, patched_llm: None, patched_ollama_available: None
) -> None:
    repo_dir = _make_repo(tmp_path)
    client = _build_client(tmp_path)

    response = client.post(
        "/api/benchmark/run",
        json={
            "repository_root": str(repo_dir),
            "task": "fix the authenticate function",
            "modes": ["direct", "arcf", "arcf_local"],
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["direct"]["mode"] == "direct"
    assert body["arcf"]["mode"] == "arcf"
    assert body["arcf_local"]["mode"] == "arcf_local"
    assert body["arcf_local"]["latency_metrics"]["stages"] is not None
    assert body["arcf_local"]["quality_metrics"]["answer_length"] > 0
    assert body["local_vs_remote_latency_reduction_pct"] is not None


def test_run_benchmark_arcf_local_unavailable_returns_502(
    tmp_path: Path, patched_llm: None, patched_ollama_unavailable: None
) -> None:
    repo_dir = _make_repo(tmp_path)
    client = _build_client(tmp_path)

    response = client.post(
        "/api/benchmark/run",
        json={
            "repository_root": str(repo_dir),
            "task": "fix bug",
            "modes": ["arcf_local"],
        },
    )
    assert response.status_code == 502
