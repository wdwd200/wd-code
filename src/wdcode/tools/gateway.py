from pathlib import Path

from wdcode.security.tool_guard import prepare_tool_request
from wdcode.tools.result import ToolResult


class ToolGateway:
    def __init__(self, registry, project_root=None, approval_mode="auto"):
        self.registry = registry
        self.project_root = Path(project_root or registry.project_root).resolve()
        self.approval_mode = approval_mode

    def schemas(self):
        return self.registry.schemas()

    def handle(self, tool_call):
        request = prepare_tool_request(
            tool_call=tool_call,
            registry=self.registry,
            project_root=self.project_root,
            approval_mode=self.approval_mode,
        )
        if not request.allowed:
            return self._failure(
                request.reason,
                tool_name=request.tool_name,
                stage=request.stage,
                dry_run=request.dry_run,
            )

        try:
            data = request.tool.execute(request.arguments)
            return ToolResult.success(
                data,
                tool_name=request.tool_name,
                stage="execution",
                dry_run=False,
                approval_mode=self.approval_mode,
            )
        except Exception as exc:
            return self._failure(str(exc), tool_name=request.tool_name, stage="execution")

    def _failure(self, error, tool_name="", stage="execution", dry_run=False):
        return ToolResult.failure(
            error,
            tool_name=tool_name,
            stage=stage,
            dry_run=dry_run,
            approval_mode=self.approval_mode,
        )
