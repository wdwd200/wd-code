from dataclasses import dataclass

from wdcode.core.tool_calls import get_tool_name, parse_tool_arguments, validate_tool_call
from wdcode.security.approval import check_approval
from wdcode.security.tool_policy import check_tool_permission


@dataclass(frozen=True)
class ToolRequest:
    allowed: bool
    reason: str
    stage: str
    tool_name: str = ""
    arguments: dict | None = None
    tool: object | None = None
    dry_run: bool = False


def prepare_tool_request(tool_call, registry, project_root, approval_mode):
    validation_error = validate_tool_call(tool_call)
    if validation_error:
        return deny(validation_error, stage="validation")

    tool_name = get_tool_name(tool_call)
    arguments = parse_tool_arguments(tool_call)
    if isinstance(arguments, dict) and "error" in arguments:
        return deny(arguments["error"], stage="parse", tool_name=tool_name)

    tool = registry.get(tool_name)
    if tool is None:
        return deny(f"Unknown tool: {tool_name}", stage="lookup", tool_name=tool_name)

    permission = check_tool_permission(tool_name, arguments, project_root)
    if not permission.allowed:
        return deny(permission.reason, stage="policy", tool_name=tool_name)

    approval = check_approval(tool_name, approval_mode)
    if not approval.allowed:
        return deny(
            approval.reason,
            stage="approval",
            tool_name=tool_name,
            arguments=permission.normalized_arguments,
            tool=tool,
            dry_run=approval.dry_run,
        )

    return ToolRequest(
        allowed=True,
        reason="Allowed.",
        stage="execution",
        tool_name=tool_name,
        arguments=permission.normalized_arguments,
        tool=tool,
        dry_run=False,
    )


def deny(reason, stage, tool_name="", arguments=None, tool=None, dry_run=False):
    return ToolRequest(
        allowed=False,
        reason=reason,
        stage=stage,
        tool_name=tool_name,
        arguments=arguments,
        tool=tool,
        dry_run=dry_run,
    )
