import json


def validate_tool_call(tool_call):
    if not isinstance(tool_call, dict):
        return "Tool call must be an object."
    if not isinstance(tool_call.get("id"), str) or not tool_call.get("id"):
        return "Tool call id must be a non-empty string."

    function = tool_call.get("function")
    if not isinstance(function, dict):
        return "Tool call function must be an object."
    if not isinstance(function.get("name"), str) or not function.get("name"):
        return "Tool function name must be a non-empty string."
    if not isinstance(function.get("arguments"), str):
        return "Tool function arguments must be a JSON string."
    return None


def parse_tool_arguments(tool_call):
    function = tool_call["function"]
    name = function["name"]
    raw_arguments = function["arguments"]

    try:
        return json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {"error": f"Invalid tool arguments for {name}: {raw_arguments}"}


def get_tool_name(tool_call):
    return tool_call["function"]["name"]
