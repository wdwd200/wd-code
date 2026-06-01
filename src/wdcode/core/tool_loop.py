from wdcode.core.agent_loop import (
    MAX_TOOL_CALLS_PER_REQUEST,
    MAX_TOOL_CALLS_PER_ROUND,
    MAX_TOOL_ROUNDS,
    run_agent_turn,
)
from wdcode.core.tool_calls import get_tool_name, parse_tool_arguments, validate_tool_call
from wdcode.tools.result import ToolResult


run_tool_loop = run_agent_turn


def execute_tool_call(tool_handler, tool_call):
    if hasattr(tool_handler, "handle"):
        return tool_handler.handle(tool_call).to_dict()

    validation_error = validate_tool_call(tool_call)
    if validation_error:
        return ToolResult.failure(validation_error).to_dict()

    arguments = parse_tool_arguments(tool_call)
    if isinstance(arguments, dict) and "error" in arguments:
        return ToolResult.failure(arguments["error"]).to_dict()

    return tool_handler.execute(get_tool_name(tool_call), arguments).to_dict()
