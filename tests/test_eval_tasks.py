import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from wdcode.eval.tasks import (
    EvalTask,
    eval_result_to_dict,
    eval_task_to_dict,
    run_eval_task,
)
from wdcode.validation.loop import ValidationLoopReport


@pytest.fixture
def tmp_path():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


def make_task(**overrides):
    values = {
        "task_id": "task-1",
        "name": "Import smoke",
        "prompt": "Keep imports working.",
        "validation_commands": ["python -m pytest tests/test_imports.py"],
        "metadata": {"owner": "tests"},
    }
    values.update(overrides)
    return EvalTask(**values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", ""),
        ("name", ""),
        ("prompt", ""),
        ("validation_commands", []),
    ],
)
def test_eval_task_rejects_empty_required_fields(field, value):
    with pytest.raises(ValueError):
        make_task(**{field: value})


def test_eval_task_rejects_empty_validation_command():
    with pytest.raises(ValueError, match="non-empty"):
        make_task(validation_commands=[""])


def test_run_eval_task_uses_validation_loop_without_llm(monkeypatch, tmp_path):
    calls = []

    def fake_run_validation_loop(project_root, commands=None, policy=None, trace_writer=None):
        calls.append(
            {
                "project_root": project_root,
                "commands": commands,
                "policy": policy,
                "trace_writer": trace_writer,
            }
        )
        return ValidationLoopReport(
            ok=True,
            attempts=1,
            validation_reports=[{"ok": True, "results": []}],
            repair_requests=[],
            final_status="passed",
            metadata={"commands": list(commands or [])},
        )

    monkeypatch.setattr("wdcode.eval.tasks.run_validation_loop", fake_run_validation_loop)

    task = make_task()
    result = run_eval_task(task=task, project_root=tmp_path)

    assert result.ok is True
    assert result.task_id == "task-1"
    assert calls == [
        {
            "project_root": tmp_path,
            "commands": ["python -m pytest tests/test_imports.py"],
            "policy": None,
            "trace_writer": None,
        }
    ]
    assert result.metadata["validation_command_count"] == 1
    assert result.metadata["final_status"] == "passed"
    json.dumps(eval_result_to_dict(result))
    json.dumps(eval_task_to_dict(task))


def test_run_eval_task_reports_validation_failure(monkeypatch, tmp_path):
    def fake_run_validation_loop(project_root, commands=None, policy=None, trace_writer=None):
        return ValidationLoopReport(
            ok=False,
            attempts=1,
            validation_reports=[{"ok": False, "results": []}],
            repair_requests=[],
            final_status="failed",
            metadata={"commands": list(commands or [])},
        )

    monkeypatch.setattr("wdcode.eval.tasks.run_validation_loop", fake_run_validation_loop)

    result = run_eval_task(task=make_task(), project_root=tmp_path)

    assert result.ok is False
    assert result.validation_report["final_status"] == "failed"
