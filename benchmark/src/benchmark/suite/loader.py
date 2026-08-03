"""Loads a suite definition file (benchmark/suites/<name>.json) into
SuiteTask objects — data, not code, so adding tasks is a JSON edit."""

import json
from pathlib import Path

from benchmark.suite.models import SuiteTask


def load_suite(path: Path) -> list[SuiteTask]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [SuiteTask.model_validate(task) for task in data["tasks"]]
