from wdcode.tools.command import create_command_tools
from wdcode.tools.files import create_file_tools
from wdcode.tools.search import create_search_tools
from wdcode.tools.registry import ToolRegistry


def create_default_registry(project_root):
    registry = ToolRegistry(project_root)
    for tool in create_file_tools(project_root):
        registry.register(tool)
    for tool in create_search_tools(project_root):
        registry.register(tool)
    for tool in create_command_tools(project_root):
        registry.register(tool)
    return registry
