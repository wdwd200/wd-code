import json

from wdcode.tools.gateway import ToolGateway
from wdcode.tools.result import ToolResult


class ToolExecutor:
    def __init__(self, registry, approval_mode="auto"):
        self.registry = registry
        self.approval_mode = approval_mode
        self.gateway = ToolGateway(registry, approval_mode=approval_mode)

    def execute(self, name, arguments):
        try:
            raw_arguments = json.dumps(arguments)
        except TypeError as exc:
            return ToolResult.failure(
                f"Tool arguments must be JSON serializable: {exc}",
                approval_mode=self.approval_mode,
                dry_run=False,
                tool_name=name,
                stage="parse",
            )

        return self.gateway.handle(
            {
                "id": "tool_executor_call",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": raw_arguments,
                },
            }
        )
