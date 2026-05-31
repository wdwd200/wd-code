from wdcode.tools.result import ToolResult


class ToolExecutor:
    def __init__(self, registry):
        self.registry = registry

    def execute(self, name, arguments):
        try:
            return ToolResult.success(self.registry.execute(name, arguments))
        except Exception as exc:
            return ToolResult.failure(str(exc))
