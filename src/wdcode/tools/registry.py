from wdcode.security.tool_policy import check_tool_permission


class ToolRegistry:
    def __init__(self, project_root):
        self._tools = {}
        self.project_root = project_root

    def register(self, tool):
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name):
        return self._tools.get(name)

    def list_tools(self):
        return list(self._tools.values())

    def schemas(self):
        return [tool.to_openai_schema() for tool in self.list_tools()]

    def execute(self, name, arguments):
        tool = self.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")

        permission = check_tool_permission(name, arguments, self.project_root)
        if not permission.allowed:
            raise ValueError(permission.reason)

        return tool.execute(permission.normalized_arguments)
