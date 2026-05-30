from pathlib import Path

from wdcode.tools import create_default_registry


def test_default_registry_contains_current_file_tools():
    project_root = Path(__file__).resolve().parents[1]
    registry = create_default_registry(project_root)
    tool_names = {tool.name for tool in registry.list_tools()}

    assert "list_files" in tool_names
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "edit_file" in tool_names
    assert "search_files" in tool_names
    assert "run_command" not in tool_names
