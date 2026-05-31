from pathlib import Path

from wdcode.core.tool_loop import execute_tool_call
from wdcode.tools import create_default_registry
from wdcode.tools.executor import ToolExecutor


def test_tool_executor_executes_registered_tool():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root))

    result = executor.execute("list_files", {"path": "tests"})

    assert "entries" in result


def test_tool_executor_unknown_tool_returns_error():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root))

    result = executor.execute("missing_tool", {})

    assert "error" in result
    assert "Unknown tool" in result["error"]


def test_tool_executor_policy_block_returns_error():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root))

    result = executor.execute("read_file", {"path": "model_config.json"})

    assert "error" in result


def test_tool_executor_executes_run_command_allowed_command():
    project_root = Path(__file__).resolve().parents[1]
    executor = ToolExecutor(create_default_registry(project_root))

    result = executor.execute("run_command", {"command": "python -m compileall tests", "timeout": 30})

    assert result["ok"] is True
    assert result["exit_code"] == 0


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

    assert "entries" in result
