from wdcode.security.approval import check_approval
from wdcode.tools.result import ToolResult


class ToolExecutor:
    def __init__(self, registry, approval_mode="auto"):
        self.registry = registry
        self.approval_mode = approval_mode

    def execute(self, name, arguments):
        approval = check_approval(name, self.approval_mode)
        if not approval.allowed:
            return ToolResult.failure(
                approval.reason,
                approval_mode=self.approval_mode,
                dry_run=approval.dry_run,
                tool_name=name,
            )

        try:
            return ToolResult.success(self.registry.execute(name, arguments))
        except Exception as exc:
            return ToolResult.failure(str(exc))
