import json

from wdcode.core.tool_calls import get_tool_name, parse_tool_arguments, validate_tool_call
from wdcode.tools.executor import ToolExecutor
from wdcode.tools.result import ToolResult


MAX_TOOL_ROUNDS = 5
MAX_TOOL_CALLS_PER_ROUND = 4
MAX_TOOL_CALLS_PER_REQUEST = 12


def run_tool_loop(client, conversation, tool_registry, max_rounds=MAX_TOOL_ROUNDS):
    tools = tool_registry.schemas() if tool_registry else None
    tool_executor = ToolExecutor(tool_registry) if tool_registry else None
    tool_call_count = 0
    for _ in range(max_rounds):
        assistant_message = client.chat(conversation.as_messages(), tools=tools)
        content, calls_executed = handle_assistant_message(conversation, assistant_message, tool_executor)
        if content is not None:
            return content
        tool_call_count += calls_executed
        if tool_call_count > MAX_TOOL_CALLS_PER_REQUEST:
            raise RuntimeError("Too many tool calls for one user request.")

    message = "Tool loop stopped before the model returned a final answer."
    conversation.add_assistant_message(message)
    return message


def handle_assistant_message(conversation, assistant_message, tool_executor):
    tool_calls = assistant_message.get("tool_calls") or []
    if not tool_calls:
        content = assistant_message.get("content") or ""
        conversation.add_assistant_message(content)
        return content, 0

    if tool_executor is None:
        raise RuntimeError("Model requested tools, but no tool registry is available.")
    if len(tool_calls) > MAX_TOOL_CALLS_PER_ROUND:
        raise RuntimeError("Too many tool calls in one model response.")

    conversation.add_assistant_tool_call_message(assistant_message)
    for tool_call in tool_calls:
        tool_result = execute_tool_call(tool_executor, tool_call)
        conversation.add_tool_result(
            tool_call_id=tool_call.get("id"),
            name=tool_call.get("function", {}).get("name", ""),
            content=json.dumps(tool_result, ensure_ascii=False),
        )

    return None, len(tool_calls)


def execute_tool_call(tool_executor, tool_call):
    validation_error = validate_tool_call(tool_call)
    if validation_error:
        return ToolResult.failure(validation_error).to_dict()

    arguments = parse_tool_arguments(tool_call)
    if isinstance(arguments, dict) and "error" in arguments:
        return ToolResult.failure(arguments["error"]).to_dict()

    return tool_executor.execute(get_tool_name(tool_call), arguments).to_dict()
