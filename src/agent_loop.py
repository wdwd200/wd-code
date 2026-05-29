import json
import sys

from commands import is_exit_command
from conversation import Conversation


def run_agent_loop(client, tool_registry=None):
    conversation = Conversation()

    print("Mini CLI Assistant. Type"
          " /exit or /quit to stop.")
    while True:
        try:
            user_input = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return

        if not user_input:
            continue
        if is_exit_command(user_input):
            print("Bye.")
            return

        conversation.add_user_message(user_input)

        try:
            assistant_message = client.chat(
                conversation.as_messages(),
                tools=tool_registry.schemas() if tool_registry else None,
            )
            assistant_reply = handle_assistant_message(client, conversation, assistant_message, tool_registry)
        except RuntimeError as exc:
            conversation.remove_last_message()
            print(f"Error: {exc}", file=sys.stderr)
            continue

        print(f"\nAssistant> {assistant_reply}")


def handle_assistant_message(client, conversation, assistant_message, tool_registry):
    tool_calls = assistant_message.get("tool_calls") or []
    if not tool_calls:
        content = assistant_message.get("content") or ""
        conversation.add_assistant_message(content)
        return content

    if tool_registry is None:
        raise RuntimeError("Model requested tools, but no tool registry is available.")

    conversation.add_assistant_tool_call_message(assistant_message)
    for tool_call in tool_calls:
        tool_result = execute_tool_call(tool_registry, tool_call)
        conversation.add_tool_result(
            tool_call_id=tool_call.get("id"),
            name=tool_call.get("function", {}).get("name", ""),
            content=json.dumps(tool_result, ensure_ascii=False),
        )

    final_message = client.chat(conversation.as_messages())
    final_content = final_message.get("content") or ""
    conversation.add_assistant_message(final_content)
    return final_content


def execute_tool_call(tool_registry, tool_call):
    function = tool_call.get("function") or {}
    name = function.get("name")
    raw_arguments = function.get("arguments") or "{}"

    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid tool arguments for {name}: {raw_arguments}") from exc

    try:
        return tool_registry.execute(name, arguments)
    except Exception as exc:
        return {"error": str(exc)}
