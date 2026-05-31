from pathlib import Path

from wdcode.tools.command import run_command


def test_run_command_executes_allowed_command_without_api_key():
    project_root = Path(__file__).resolve().parents[1]

    result = run_command(project_root, {"command": "python -m compileall tests", "timeout": 30})

    assert result["ok"] is True
    assert result["command"] == "python -m compileall tests"
    assert result["exit_code"] == 0
    assert isinstance(result["stdout"], str)
    assert isinstance(result["stderr"], str)
    assert isinstance(result["duration_ms"], int)


def test_run_command_policy_block_does_not_execute():
    project_root = Path(__file__).resolve().parents[1]

    result = run_command(project_root, {"command": "git push", "timeout": 30})

    assert result["ok"] is False
    assert result["exit_code"] is None
    assert "error" in result


def test_run_command_timeout_returns_failure():
    project_root = Path(__file__).resolve().parents[1]

    result = run_command(project_root, {"command": "python -m pytest tests", "timeout": 0.001})

    assert result["ok"] is False
    assert result["exit_code"] is None
    assert "timed out" in result["error"]


def test_run_command_cwd_cannot_escape_project_root():
    project_root = Path(__file__).resolve().parents[1]

    result = run_command(project_root, {"command": "python -m compileall tests", "cwd": ".."})

    assert result["ok"] is False
    assert "Path traversal" in result["error"]
