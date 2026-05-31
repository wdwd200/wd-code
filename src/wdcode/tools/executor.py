class ToolExecutor:
    def __init__(self, registry):
        self.registry = registry

    def execute(self, name, arguments):
        try:
            return self.registry.execute(name, arguments)
        except Exception as exc:
            return {"error": str(exc)}
