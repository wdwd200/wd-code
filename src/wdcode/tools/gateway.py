from pathlib import Path

from wdcode.core.tool_calls import get_tool_name, parse_tool_arguments, validate_tool_call
from wdcode.tools.executor import ToolExecutor
from wdcode.tools.result import ToolResult


class ToolGateway:
    def __init__(self, registry, project_root=None, approval_mode="auto"):
        self.registry = registry
        self.project_root = Path(project_root or registry.project_root).resolve()
        self.approval_mode = approval_mode
        self.executor = ToolExecutor(registry, approval_mode=approval_mode)

    def schemas(self):
        return self.registry.schemas()

    def handle(self, tool_call):
        validation_error = validate_tool_call(tool_call)
        tool_name = _safe_tool_name(tool_call)
        if validation_error:
            return self._failure(validation_error, tool_name=tool_name, stage="validation")

        arguments = parse_tool_arguments(tool_call)
        if isinstance(arguments, dict) and "error" in arguments:
            return self._failure(arguments["error"], tool_name=tool_name, stage="parse")

        result = self.executor.execute(get_tool_name(tool_call), arguments)
        return self._with_gateway_metadata(result, tool_name=get_tool_name(tool_call))

    def _failure(self, error, tool_name="", stage="execution", dry_run=False):
        return ToolResult.failure(
            error,
            tool_name=tool_name,
            stage=stage,
            dry_run=dry_run,
            approval_mode=self.approval_mode,
        )

    def _with_gateway_metadata(self, result, tool_name):
        metadata = {
            "tool_name": tool_name,
            "stage": _result_stage(result),
            "dry_run": False,
            "approval_mode": self.approval_mode,
        }
        metadata.update(result.metadata)
        return ToolResult(
            ok=result.ok,
            data=result.data,
            error=result.error,
            metadata=metadata,
        )


def _safe_tool_name(tool_call):
    if not isinstance(tool_call, dict):
        return ""
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return ""
    name = function.get("name")
    return name if isinstance(name, str) else ""


def _result_stage(result):
    if result.metadata.get("dry_run") or result.metadata.get("approval_mode") == "require_approval":
        return "approval"
    if result.ok:
        return "execution"
    return "execution"
