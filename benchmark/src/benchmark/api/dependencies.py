"""FastAPI dependency wiring — fetches singletons off app.state, built
once in app.create_app(), same pattern as ARCF's own dependencies.py.
"""

from fastapi import Request

from benchmark.config import BenchmarkSettings
from benchmark.controller import BenchmarkController
from benchmark.repository import RepositoryLoader
from benchmark.storage import BenchmarkStore


def get_settings(request: Request) -> BenchmarkSettings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_repository_loader(request: Request) -> RepositoryLoader:
    return request.app.state.repository_loader  # type: ignore[no-any-return]


def get_controller(request: Request) -> BenchmarkController:
    return request.app.state.controller  # type: ignore[no-any-return]


def get_store(request: Request) -> BenchmarkStore:
    return request.app.state.store  # type: ignore[no-any-return]


def get_local_slm_unavailable_reason(request: Request) -> str | None:
    return request.app.state.local_slm_unavailable_reason  # type: ignore[no-any-return]
