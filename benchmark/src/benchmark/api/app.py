"""FastAPI app factory for the benchmark tool.

Object wiring itself lives in bootstrap.py:build_runtime, shared with
cli.py so the API and the CLI build the identical runtime. A factory,
not a module-level `app = FastAPI()`, so tests can build an app against
a temp store path without touching the real one.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from benchmark.api.routes import router
from benchmark.bootstrap import build_runtime
from benchmark.config import BenchmarkSettings, get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: BenchmarkSettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    runtime = build_runtime(settings)

    app = FastAPI(title="ARCF Benchmark", version="0.1.0")
    app.state.settings = runtime.settings
    app.state.repository_loader = runtime.repository_loader
    app.state.controller = runtime.controller
    app.state.store = runtime.store
    app.state.ledger_recorder = runtime.ledger_recorder
    app.state.local_slm_unavailable_reason = runtime.local_slm_unavailable_reason

    app.include_router(router)
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


app = create_app()
