import json
from pathlib import Path

from benchmark.suite.loader import load_suite


def test_loads_tasks_from_json(tmp_path: Path) -> None:
    suite_file = tmp_path / "mini.json"
    suite_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "t1",
                        "category": "repository_understanding",
                        "subcategory": "auth",
                        "repo_key": "arcf",
                        "task_prompt": "explain auth",
                        "expected_grounding": ["auth.py"],
                    }
                ]
            }
        )
    )
    tasks = load_suite(suite_file)
    assert len(tasks) == 1
    assert tasks[0].id == "t1"
    assert tasks[0].expected_grounding == ["auth.py"]


def test_loads_the_real_pilot_suite() -> None:
    pilot_path = Path(__file__).resolve().parents[2] / "suites" / "pilot.json"
    tasks = load_suite(pilot_path)
    assert len(tasks) == 8
    assert {t.repo_key for t in tasks} == {"arcf", "todomvc"}
