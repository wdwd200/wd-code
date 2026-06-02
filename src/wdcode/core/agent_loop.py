import json
import sys

from wdcode.cli.commands import is_exit_command
from wdcode.context.provider import ContextProvider
from wdcode.core.conversation import Conversation
from wdcode.core.message_builder import build_model_messages
from wdcode.core.model_runner import ModelRunner
from wdcode.core.response_router import route_assistant_message
from wdcode.tools.gateway import ToolGateway


MAX_TOOL_ROUNDS = 5
MAX_TOOL_CALLS_PER_ROUND = 4
MAX_TOOL_CALLS_PER_REQUEST = 12


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

        checkpoint = conversation.checkpoint()
        conversation.add_user_message(user_input)

        try:
            assistant_reply = run_agent_turn(
                client=client,
                conversation=conversation,
                tool_registry=tool_registry,
                user_input=user_input,
            )
        except RuntimeError as exc:
            conversation.rollback(checkpoint)
            print(f"Error: {exc}", file=sys.stderr)
            continue

        print(f"\nAssistant> {assistant_reply}")


def run_agent_turn(
    client,
    conversation,
    tool_registry,
    max_rounds=MAX_TOOL_ROUNDS,
    trace_writer=None,
    approval_mode="auto",
    user_input="",
    context_provider=None,
):
    context_provider = context_provider or ContextProvider()
    model_runner = ModelRunner(client)
    tool_gateway = ToolGateway(tool_registry, approval_mode=approval_mode) if tool_registry else None
    tools = tool_gateway.schemas() if tool_gateway else None
    tool_call_count = 0
    for _ in range(max_rounds):
        context = context_provider.build(user_input=user_input, conversation=conversation)
        messages = build_model_messages(conversation=conversation, context=context)
        assistant_message = model_runner.call(messages=messages, tools=tools)
        route = route_assistant_message(assistant_message)

        _trace_assistant_message(trace_writer, route)
        if route.is_final:
            conversation.add_assistant_message(route.content)
            _write_trace(trace_writer, "final_answer", {"content": route.content})
            return route.content

        calls_executed = _handle_tool_calls(
            conversation=conversation,
            route=route,
            tool_gateway=tool_gateway,
            trace_writer=trace_writer,
        )
        tool_call_count += calls_executed
        if tool_call_count > MAX_TOOL_CALLS_PER_REQUEST:
            raise RuntimeError("Too many tool calls for one user request.")

    message = "Tool loop stopped before the model returned a final answer."
    conversation.add_assistant_message(message)
    _write_trace(trace_writer, "tool_loop_stopped", {"reason": message})
    return message


def _handle_tool_calls(conversation, route, tool_gateway, trace_writer=None):
    if tool_gateway is None:
        raise RuntimeError("Model requested tools, but no tool registry is available.")
    if len(route.tool_calls) > MAX_TOOL_CALLS_PER_ROUND:
        raise RuntimeError("Too many tool calls in one model response.")

    conversation.add_assistant_tool_call_message(route.raw_message)
    for tool_call in route.tool_calls:
        _trace_tool_call(trace_writer, tool_call)

    tool_results = tool_gateway.handle_many(route.tool_calls)
    for tool_call, tool_result in zip(route.tool_calls, tool_results, strict=True):
        tool_result_dict = tool_result.to_dict()
        tool_name = _tool_name(tool_call)
        conversation.add_tool_result(
            tool_call_id=tool_call.get("id"),
            name=tool_name,
            content=json.dumps(tool_result_dict, ensure_ascii=False),
        )
        _write_trace(
            trace_writer,
            "tool_result",
            {
                "tool_call_id": tool_call.get("id"),
                "name": tool_name,
                "result": tool_result_dict,
            },
        )

    return len(route.tool_calls)


def _trace_assistant_message(trace_writer, route):
    _write_trace(
        trace_writer,
        "assistant_message",
        {
            "content": route.raw_message.get("content"),
            "has_tool_calls": bool(route.tool_calls),
        },
    )


def _trace_tool_call(trace_writer, tool_call):
    _write_trace(
        trace_writer,
        "tool_call",
        {
            "tool_call_id": tool_call.get("id"),
            "name": _tool_name(tool_call),
            "arguments": _trace_tool_arguments(tool_call),
        },
    )


def _write_trace(trace_writer, event_type, payload):
    if trace_writer is not None:
        trace_writer.write_event(event_type, payload)


def _trace_tool_arguments(tool_call):
    raw_arguments = tool_call.get("function", {}).get("arguments", "")
    try:
        return json.loads(raw_arguments)
    except json.JSONDecodeError:
        return raw_arguments


def _tool_name(tool_call):
    return tool_call.get("function", {}).get("name", "")
