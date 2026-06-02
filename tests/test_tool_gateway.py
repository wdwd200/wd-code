import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from wdcode.tools import create_default_registry
from wdcode.tools.base import Tool
from wdcode.tools.gateway import ToolGateway
from wdcode.tools.registry import ToolRegistry


@contextmanager
def project_temp_dir():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield project_root, Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


def make_tool_call(name, arguments, call_id="call_1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
        },
    }


def test_tool_gateway_exposes_registry_schemas():
    project_root = Path(__file__).resolve().parents[1]
    gateway = ToolGateway(create_default_registry(project_root))

    tool_names = {schema["function"]["name"] for schema in gateway.schemas()}

    assert "list_files" in tool_names
    assert "read_file" in tool_names
    assert "run_command" in tool_names


def test_tool_gateway_handles_successful_tool_call():
    project_root = Path(__file__).resolve().parents[1]
    gateway = ToolGateway(create_default_registry(project_root))

    result = gateway.handle(make_tool_call("list_files", {"path": "tests"}))

    assert result.ok is True
    assert "entries" in result.data
    assert result.metadata["tool_name"] == "list_files"
    assert result.metadata["stage"] == "execution"


def test_tool_gateway_wraps_invalid_arguments_as_tool_result():
    project_root = Path(__file__).resolve().parents[1]
    gateway = ToolGateway(create_default_registry(project_root))

    result = gateway.handle(make_tool_call("list_files", "{bad json"))

    assert result.ok is False
    assert "Invalid tool arguments" in result.error
    assert result.metadata["tool_name"] == "list_files"
    assert result.metadata["stage"] == "parse"


def test_tool_gateway_wraps_unknown_tool_as_tool_result():
    project_root = Path(__file__).resolve().parents[1]
    gateway = ToolGateway(create_default_registry(project_root))

    result = gateway.handle(make_tool_call("missing_tool", {}))

    assert result.ok is False
    assert "Unknown tool" in result.error
    assert result.metadata["tool_name"] == "missing_tool"
    assert result.metadata["stage"] == "lookup"


def test_tool_gateway_wraps_tool_execution_exception_as_tool_result():
    project_root = Path(__file__).resolve().parents[1]
    registry = ToolRegistry(project_root)

    def failing_tool(arguments):
        raise RuntimeError("tool failed")

    registry.register(
        Tool(
            name="list_files",
            description="Failing tool.",
            parameters={"type": "object"},
            execute=failing_tool,
        )
    )
    gateway = ToolGateway(registry)

    result = gateway.handle(make_tool_call("list_files", {"path": "tests"}))

    assert result.ok is False
    assert "tool failed" in result.error
    assert result.metadata["tool_name"] == "list_files"
    assert result.metadata["stage"] == "execution"


def test_tool_gateway_dry_run_blocks_write_without_creating_file():
    with project_temp_dir() as (project_root, temp_dir):
        target = temp_dir / "created.txt"
        gateway = ToolGateway(
            create_default_registry(project_root),
            approval_mode="dry_run",
        )

        result = gateway.handle(
            make_tool_call(
                "write_file",
                {
                    "path": target.relative_to(project_root).as_posix(),
                    "content": "do not write",
                },
            )
        )

        assert result.ok is False
        assert result.metadata["tool_name"] == "write_file"
        assert result.metadata["stage"] == "approval"
        assert result.metadata["dry_run"] is True
        assert result.metadata["approval_mode"] == "dry_run"
        assert not target.exists()
