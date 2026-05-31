from pathlib import Path

from wdcode.core.tool_loop import execute_tool_call
from wdcode.tools import create_default_registry
from wdcode.tools.executor import ToolExecutor


def test_tool_executor_executes_registered_tool():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root))

    result = executor.execute("list_files", {"path": "tests"})

    assert result.ok is True
    assert "entries" in result.data


def test_tool_executor_unknown_tool_returns_error():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root))

    result = executor.execute("missing_tool", {})

    assert result.ok is False
    assert "Unknown tool" in result.error


def test_tool_executor_policy_block_returns_error():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root))

    result = executor.execute("read_file", {"path": "model_config.json"})

    assert result.ok is False
    assert result.error


def test_tool_executor_executes_run_command_allowed_command():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root))

    result = executor.execute("run_command", {"command": "python -m compileall tests", "timeout": 30})

    assert result.ok is True
    assert result.data["ok"] is True
    assert result.data["exit_code"] == 0


def test_tool_executor_tool_exception_returns_failure():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root))

    result = executor.execute("read_file", {"path": "missing.txt"})

    assert result.ok is False
    assert "File not found" in result.error


def test_tool_loop_execute_tool_call_returns_json_serializable_result():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root))
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "list_files",
            "arguments": "{\"path\": \"tests\"}",
        },
    }

    result = execute_tool_call(executor, tool_call)

    assert result["ok"] is True
    assert "entries" in result["data"]


def test_tool_loop_execute_tool_call_parse_error_returns_unified_failure():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root))
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "list_files",
            "arguments": "{bad json",
        },
    }

    result = execute_tool_call(executor, tool_call)

    assert result["ok"] is False
    assert "Invalid tool arguments" in result["error"]
