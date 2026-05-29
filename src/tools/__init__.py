from tools.files import create_file_tools
from tools.registry import ToolRegistry


def create_default_registry(project_root):
    registry = ToolRegistry()
    for tool in create_file_tools(project_root):
        registry.register(tool)
    return registry
