import json
import sys
from datetime import datetime, timezone

from wdcode.cli.commands import is_exit_command
from wdcode.context.provider import ContextProvider
from wdcode.core.conversation import Conversation
from wdcode.core.message_builder import build_model_messages
from wdcode.core.model_runner import ModelRunner
from wdcode.core.response_router import route_assistant_message
from wdcode.session import SessionRecord, build_recovery_summary, create_session_id, validate_session_id
from wdcode.tools.gateway import ToolGateway


MAX_TOOL_ROUNDS = 5
MAX_TOOL_CALLS_PER_ROUND = 4
MAX_TOOL_CALLS_PER_REQUEST = 12
DEFAULT_SUMMARY_TRIGGER_MESSAGES = 30
DEFAULT_RECOVERY_KEEP_RECENT_MESSAGES = 12
DEFAULT_MAX_RECOVERY_SUMMARY_CHARS = 4000


def run_agent_loop(
    client,
    tool_registry=None,
    *,
    input_fn=input,
    output_fn=print,
    error_fn=None,
    conversation=None,
    max_rounds=MAX_TOOL_ROUNDS,
    trace_writer=None,
    approval_mode="auto",
    context_provider=None,
    session_store=None,
    session_id=None,
    summary_trigger_messages=DEFAULT_SUMMARY_TRIGGER_MESSAGES,
    keep_recent_messages=DEFAULT_RECOVERY_KEEP_RECENT_MESSAGES,
    max_recovery_summary_chars=DEFAULT_MAX_RECOVERY_SUMMARY_CHARS,
):
    conversation, session_record = _load_session_conversation(
        conversation=conversation,
        session_store=session_store,
        session_id=session_id,
    )
    context_provider = context_provider or ContextProvider(
        project_root=getattr(tool_registry, "project_root", None)
    )
    model_runner = ModelRunner(client)
    tool_gateway = ToolGateway(tool_registry, approval_mode=approval_mode) if tool_registry else None
    error_fn = error_fn or _write_error

    output_fn("Mini CLI Assistant. Type"
              " /exit or /quit to stop.")
    while True:
        try:
            user_input = input_fn("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            output_fn("\nBye.")
            return

        if not user_input:
            continue
        if is_exit_command(user_input):
            output_fn("Bye.")
            return

        checkpoint = conversation.checkpoint()
        conversation.add_user_message(user_input)

        try:
            assistant_reply = None
            tool_call_count = 0

            for _ in range(max_rounds):
                context = context_provider.build(user_input=user_input, conversation=conversation)
                messages = build_model_messages(conversation=conversation, context=context)
                assistant_message = model_runner.call(
                    messages=messages,
                    tools=tool_gateway.schemas() if tool_gateway else None,
                )
                route = route_assistant_message(assistant_message)

                _trace_assistant_message(trace_writer, route)
                if route.is_final:
                    conversation.add_assistant_message(route.content)
                    _write_trace(trace_writer, "final_answer", {"content": route.content})
                    assistant_reply = route.content
                    break

                if tool_gateway is None:
                    raise RuntimeError("Model requested tools, but no tool registry is available.")
                if len(route.tool_calls) > MAX_TOOL_CALLS_PER_ROUND:
                    raise RuntimeError("Too many tool calls in one model response.")

                conversation.add_assistant_tool_call_message(route.raw_message)
                for tool_call in route.tool_calls:
                    _trace_tool_call(trace_writer, tool_call)

                tool_results = tool_gateway.handle_many(route.tool_calls)
                _record_tool_results(
                    conversation=conversation,
                    tool_calls=route.tool_calls,
                    tool_results=tool_results,
                    trace_writer=trace_writer,
                )
                tool_call_count += len(route.tool_calls)
                if tool_call_count > MAX_TOOL_CALLS_PER_REQUEST:
                    raise RuntimeError("Too many tool calls for one user request.")

            if assistant_reply is None:
                assistant_reply = "Tool loop stopped before the model returned a final answer."
                conversation.add_assistant_message(assistant_reply)
                _write_trace(trace_writer, "tool_loop_stopped", {"reason": assistant_reply})
        except RuntimeError as exc:
            conversation.rollback(checkpoint)
            session_record = _save_session(
                session_store=session_store,
                session_record=session_record,
                conversation=conversation,
                summary_trigger_messages=summary_trigger_messages,
                keep_recent_messages=keep_recent_messages,
                max_recovery_summary_chars=max_recovery_summary_chars,
            )
            error_fn(f"Error: {exc}")
            continue

        session_record = _save_session(
            session_store=session_store,
            session_record=session_record,
            conversation=conversation,
            summary_trigger_messages=summary_trigger_messages,
            keep_recent_messages=keep_recent_messages,
            max_recovery_summary_chars=max_recovery_summary_chars,
        )
        output_fn(f"\nAssistant> {assistant_reply}")


def _record_tool_results(conversation, tool_calls, tool_results, trace_writer=None):
    for tool_call, tool_result in zip(tool_calls, tool_results, strict=True):
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


def _write_error(message):
    print(message, file=sys.stderr)


def _trace_tool_arguments(tool_call):
    raw_arguments = tool_call.get("function", {}).get("arguments", "")
    try:
        return json.loads(raw_arguments)
    except json.JSONDecodeError:
        return raw_arguments


def _tool_name(tool_call):
    return tool_call.get("function", {}).get("name", "")


def _load_session_conversation(conversation, session_store, session_id):
    if session_store is None:
        return conversation or Conversation(), None

    if session_id is None:
        session_id = create_session_id()
    else:
        session_id = validate_session_id(session_id)

    record = session_store.load(session_id)
    if record is not None:
        restored = Conversation.from_messages(
            record.messages,
            recovery_summary=record.recovery_summary,
        )
        if conversation is not None:
            conversation.messages = restored.to_messages()
            conversation.recovery_summary = record.recovery_summary
            restored = conversation
        return restored, record

    created_at = _utc_now()
    record = SessionRecord(
        session_id=session_id,
        messages=[],
        created_at=created_at,
        updated_at=created_at,
        metadata={},
        recovery_summary=None,
    )
    return conversation or Conversation(), record


def _save_session(
    session_store,
    session_record,
    conversation,
    *,
    summary_trigger_messages,
    keep_recent_messages,
    max_recovery_summary_chars,
):
    if session_store is None or session_record is None:
        return session_record

    recovery_summary = _build_recovery_summary_dict(
        conversation=conversation,
        summary_trigger_messages=summary_trigger_messages,
        keep_recent_messages=keep_recent_messages,
        max_recovery_summary_chars=max_recovery_summary_chars,
    )
    conversation.recovery_summary = recovery_summary
    record = SessionRecord(
        session_id=session_record.session_id,
        messages=conversation.to_messages(),
        created_at=session_record.created_at,
        updated_at=_utc_now(),
        metadata=session_record.metadata,
        recovery_summary=recovery_summary,
    )
    session_store.save(record)
    return record


def _build_recovery_summary_dict(
    *,
    conversation,
    summary_trigger_messages,
    keep_recent_messages,
    max_recovery_summary_chars,
):
    messages = conversation.to_messages()
    if len(messages) <= summary_trigger_messages:
        return conversation.recovery_summary

    summary = build_recovery_summary(
        messages,
        max_summary_chars=max_recovery_summary_chars,
        keep_recent_messages=keep_recent_messages,
    )
    if summary is None:
        return None
    return {
        "summary": summary.summary,
        "source_message_count": summary.source_message_count,
        "recent_message_count": summary.recent_message_count,
        "metadata": summary.metadata,
    }


def _utc_now():
    return datetime.now(timezone.utc).isoformat()
