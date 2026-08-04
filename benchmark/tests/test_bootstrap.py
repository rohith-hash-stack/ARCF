from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmark.bootstrap import build_runtime
from benchmark.config import BenchmarkSettings


def _settings(tmp_path: Path) -> BenchmarkSettings:
    return BenchmarkSettings(
        clone_root=str(tmp_path / "clones"),
        store_path=str(tmp_path / "runs.db"),
        execution_ledger_db_path=str(tmp_path / "ledger.db"),
    )


def test_build_runtime_omits_local_runner_when_ollama_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"models": []})

    monkeypatch.setattr("benchmark.local_slm.ollama_provider.httpx.get", fake_get)

    runtime = build_runtime(_settings(tmp_path))

    assert runtime.local_slm_unavailable_reason is not None
    assert runtime.controller._arcf_local_runner is None


def test_build_runtime_wires_local_runner_when_candidate_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"models": [{"name": "qwen2.5:1.5b-instruct"}]},
        )

    monkeypatch.setattr("benchmark.local_slm.ollama_provider.httpx.get", fake_get)

    runtime = build_runtime(_settings(tmp_path))

    assert runtime.local_slm_unavailable_reason is None
    assert runtime.controller._arcf_local_runner is not None
    assert runtime.controller._arcf_local_runner._slm_model == "ollama_chat/qwen2.5:1.5b-instruct"


def test_build_runtime_direct_and_remote_runners_always_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"models": []})

    monkeypatch.setattr("benchmark.local_slm.ollama_provider.httpx.get", fake_get)

    runtime = build_runtime(_settings(tmp_path))

    assert runtime.controller._direct_runner is not None
    assert runtime.controller._arcf_runner is not None
