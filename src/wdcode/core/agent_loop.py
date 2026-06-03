import json
import sys
from dataclasses import replace
from datetime import datetime, timezone

from wdcode.cli.commands import is_exit_command
from wdcode.context.provider import ContextProvider
from wdcode.core.conversation import Conversation
from wdcode.core.failure_recovery import (
    FailureReport,
    RetryPolicy,
    call_with_retries,
    classify_exception,
    failure_report_to_dict,
)
from wdcode.core.message_builder import build_model_messages
from wdcode.core.model_runner import ModelRunner
from wdcode.core.response_router import route_assistant_message
from wdcode.session import (
    CheckpointStore,
    CompressionPolicy,
    SessionRecord,
    build_context_snapshot,
    build_conversation_compression,
    build_file_change_snapshot,
    build_recovery_summary,
    build_tool_call_snapshot,
    build_turn_checkpoint,
    conversation_compression_to_dict,
    create_session_id,
    validate_session_id,
)
from wdcode.tools.gateway import ToolGateway


MAX_TOOL_ROUNDS = 5
MAX_TOOL_CALLS_PER_ROUND = 4
MAX_TOOL_CALLS_PER_REQUEST = 12
DEFAULT_SUMMARY_TRIGGER_MESSAGES = 30
DEFAULT_RECOVERY_KEEP_RECENT_MESSAGES = 12
DEFAULT_MAX_RECOVERY_SUMMARY_CHARS = 4000
_MISSING = object()


class _ToolExecutionFailure(RuntimeError):
    pass


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
    checkpoint_store=None,
    summary_trigger_messages=DEFAULT_SUMMARY_TRIGGER_MESSAGES,
    keep_recent_messages=DEFAULT_RECOVERY_KEEP_RECENT_MESSAGES,
    max_recovery_summary_chars=DEFAULT_MAX_RECOVERY_SUMMARY_CHARS,
    model_retry_policy=None,
    tool_retry_policy=None,
    compression_policy=None,
):
    conversation, session_record = _load_session_conversation(
        conversation=conversation,
        session_store=session_store,
        session_id=session_id,
    )
    checkpoint_store = _resolve_checkpoint_store(session_store, checkpoint_store)
    project_root = getattr(tool_registry, "project_root", None)
    context_provider = context_provider or ContextProvider(
        project_root=project_root
    )
    model_runner = ModelRunner(client)
    tool_gateway = ToolGateway(tool_registry, approval_mode=approval_mode) if tool_registry else None
    model_retry_policy = model_retry_policy or RetryPolicy(max_attempts=2)
    tool_retry_policy = tool_retry_policy or RetryPolicy(
        max_attempts=1,
        retry_tool_errors=False,
    )
    compression_policy = compression_policy or CompressionPolicy()
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
        turn_checkpoint = _create_turn_checkpoint(
            checkpoint_store=checkpoint_store,
            session_record=session_record,
            conversation=conversation,
            user_input=user_input,
            project_root=project_root,
        )
        conversation.add_user_message(user_input)
        latest_failure_report = None

        try:
            assistant_reply = None
            tool_call_count = 0

            for _ in range(max_rounds):
                context = context_provider.build(user_input=user_input, conversation=conversation)
                _refresh_conversation_compression(
                    conversation=conversation,
                    compression_policy=compression_policy,
                )
                turn_checkpoint = _save_checkpoint_update(
                    checkpoint_store=checkpoint_store,
                    checkpoint=turn_checkpoint,
                    context_snapshot=build_context_snapshot(context),
                    metadata_updates={
                        "stage": "context_built",
                        **_compression_checkpoint_metadata(conversation.compression_summary),
                    },
                )
                messages = build_model_messages(
                    conversation=conversation,
                    context=context,
                    compression_summary=conversation.compression_summary,
                    keep_recent_messages=compression_policy.keep_recent_messages,
                )
                model_result = call_with_retries(
                    lambda: model_runner.call(
                        messages=messages,
                        tools=tool_gateway.schemas() if tool_gateway else None,
                    ),
                    component="model",
                    policy=model_retry_policy,
                    metadata={"stage": "model_call"},
                )
                assistant_message = model_result.value
                latest_failure_report = _latest_report_with_events(
                    latest_failure_report,
                    model_result.report,
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

                turn_checkpoint = _save_checkpoint_update(
                    checkpoint_store=checkpoint_store,
                    checkpoint=turn_checkpoint,
                    tool_call_snapshot=build_tool_call_snapshot(route.tool_calls),
                    metadata_updates={"stage": "tool_calls_observed"},
                )
                conversation.add_assistant_tool_call_message(route.raw_message)
                for tool_call in route.tool_calls:
                    _trace_tool_call(trace_writer, tool_call)

                tool_result = call_with_retries(
                    lambda: _handle_many_tools(
                        tool_gateway=tool_gateway,
                        tool_calls=route.tool_calls,
                        retry_policy=tool_retry_policy,
                    ),
                    component="tool",
                    policy=tool_retry_policy,
                    metadata={
                        "stage": "tool_call",
                        "tool_count": len(route.tool_calls),
                    },
                )
                tool_results = tool_result.value
                latest_failure_report = _latest_report_with_events(
                    latest_failure_report,
                    tool_result.report,
                )
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
        except Exception as exc:
            latest_failure_report = _failure_report_from_exception(
                exc,
                latest_failure_report,
            )
            conversation.rollback(checkpoint)
            _refresh_conversation_compression(
                conversation=conversation,
                compression_policy=compression_policy,
            )
            turn_checkpoint = _save_checkpoint_update(
                checkpoint_store=checkpoint_store,
                checkpoint=turn_checkpoint,
                metadata_updates={
                    "stage": "rolled_back",
                    "rolled_back": True,
                    **_compression_checkpoint_metadata(conversation.compression_summary),
                },
            )
            session_record = _save_session(
                session_store=session_store,
                session_record=session_record,
                conversation=conversation,
                checkpoint=turn_checkpoint,
                rolled_back=True,
                failure_report=latest_failure_report,
                summary_trigger_messages=summary_trigger_messages,
                keep_recent_messages=keep_recent_messages,
                max_recovery_summary_chars=max_recovery_summary_chars,
                compression_policy=compression_policy,
            )
            error_fn(f"Error: {exc}")
            continue

        session_record = _save_session(
            session_store=session_store,
            session_record=session_record,
            conversation=conversation,
            checkpoint=turn_checkpoint,
            rolled_back=False,
            failure_report=latest_failure_report,
            summary_trigger_messages=summary_trigger_messages,
            keep_recent_messages=keep_recent_messages,
            max_recovery_summary_chars=max_recovery_summary_chars,
            compression_policy=compression_policy,
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


def _handle_many_tools(*, tool_gateway, tool_calls, retry_policy):
    tool_results = tool_gateway.handle_many(tool_calls)
    if _should_raise_tool_result_failure(tool_results, retry_policy):
        raise _ToolExecutionFailure(_tool_failure_message(tool_results))
    return tool_results


def _should_raise_tool_result_failure(tool_results, retry_policy):
    if not retry_policy.retry_tool_errors or retry_policy.max_attempts <= 1:
        return False
    return any(
        not result.ok and result.metadata.get("stage") == "execution"
        for result in tool_results
    )


def _tool_failure_message(tool_results):
    for result in tool_results:
        if not result.ok and result.metadata.get("stage") == "execution":
            tool_name = result.metadata.get("tool_name") or "unknown"
            return f"Tool execution failed for {tool_name}: {result.error}"
    return "Tool execution failed."


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
            compression_summary=record.compression_summary,
        )
        if conversation is not None:
            conversation.messages = restored.to_messages()
            conversation.recovery_summary = record.recovery_summary
            conversation.compression_summary = record.compression_summary
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
        compression_summary=None,
    )
    return conversation or Conversation(), record


def _save_session(
    session_store,
    session_record,
    conversation,
    *,
    checkpoint,
    rolled_back,
    failure_report,
    summary_trigger_messages,
    keep_recent_messages,
    max_recovery_summary_chars,
    compression_policy,
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
    _refresh_conversation_compression(
        conversation=conversation,
        compression_policy=compression_policy,
    )
    metadata = dict(session_record.metadata)
    if checkpoint is not None:
        metadata["latest_checkpoint_id"] = checkpoint.checkpoint_id
        if rolled_back:
            metadata["rollback_checkpoint_id"] = checkpoint.checkpoint_id
    if failure_report is not None and failure_report.events:
        _record_failure_metadata(metadata, failure_report, checkpoint=checkpoint)
    record = SessionRecord(
        session_id=session_record.session_id,
        messages=conversation.to_messages(),
        created_at=session_record.created_at,
        updated_at=_utc_now(),
        metadata=metadata,
        recovery_summary=recovery_summary,
        compression_summary=conversation.compression_summary,
    )
    session_store.save(record)
    return record


def _latest_report_with_events(current, candidate):
    if candidate is not None and candidate.events:
        return candidate
    return current


def _failure_report_from_exception(exc, current_report):
    report = getattr(exc, "failure_report", None)
    if isinstance(report, FailureReport):
        return report

    event = classify_exception(
        exc,
        component="runtime",
        attempt=1,
        max_attempts=1,
        metadata={"stage": "agent_loop"},
    )
    existing_events = list(current_report.events) if current_report is not None else []
    metadata = dict(current_report.metadata) if current_report is not None else {}
    metadata["stage"] = "agent_loop"
    return FailureReport(
        events=existing_events + [event],
        final_status="failed",
        metadata=metadata,
    )


def _record_failure_metadata(metadata, failure_report, *, checkpoint):
    last_event = failure_report.events[-1]
    metadata["latest_failure_report"] = failure_report_to_dict(failure_report)
    metadata["latest_failure_component"] = last_event.component
    metadata["latest_failure_category"] = last_event.category
    metadata["latest_failure_retryable"] = last_event.retryable
    metadata["latest_failure_attempts"] = last_event.attempt
    if checkpoint is not None:
        metadata["latest_failure_checkpoint_id"] = checkpoint.checkpoint_id


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


def _refresh_conversation_compression(*, conversation, compression_policy):
    compression = build_conversation_compression(
        conversation.to_messages(),
        recovery_summary=conversation.recovery_summary,
        policy=compression_policy,
    )
    conversation.compression_summary = (
        conversation_compression_to_dict(compression)
        if compression is not None
        else None
    )
    return conversation.compression_summary


def _compression_checkpoint_metadata(compression_summary):
    if not compression_summary:
        return {"compression_summary_present": False}
    return {
        "compression_summary_present": True,
        "compression_source_range": compression_summary.get("source_range") or {},
        "compression_summary_chars": len(str(compression_summary.get("summary") or "")),
    }


def _resolve_checkpoint_store(session_store, checkpoint_store):
    if checkpoint_store is not None:
        return checkpoint_store
    if session_store is None:
        return None
    return CheckpointStore(session_store.root / "checkpoints")


def _create_turn_checkpoint(
    *,
    checkpoint_store,
    session_record,
    conversation,
    user_input,
    project_root,
):
    if checkpoint_store is None or session_record is None:
        return None

    checkpoint = build_turn_checkpoint(
        session_id=session_record.session_id,
        turn_index=_next_turn_index(conversation),
        messages=conversation.to_messages(),
        recovery_summary=conversation.recovery_summary,
        file_change_snapshot=build_file_change_snapshot(project_root),
        metadata={
            "stage": "pre_turn",
            "user_input_preview": _preview_text(user_input),
            "rolled_back": False,
            **_compression_checkpoint_metadata(conversation.compression_summary),
        },
    )
    checkpoint_store.save(checkpoint)
    return checkpoint


def _save_checkpoint_update(
    *,
    checkpoint_store,
    checkpoint,
    context_snapshot=_MISSING,
    tool_call_snapshot=_MISSING,
    metadata_updates=None,
):
    if checkpoint_store is None or checkpoint is None:
        return checkpoint

    metadata = dict(checkpoint.metadata)
    metadata.update(metadata_updates or {})
    updated = replace(
        checkpoint,
        context_snapshot=(
            checkpoint.context_snapshot
            if context_snapshot is _MISSING
            else context_snapshot
        ),
        tool_call_snapshot=(
            checkpoint.tool_call_snapshot
            if tool_call_snapshot is _MISSING
            else tool_call_snapshot
        ),
        metadata=metadata,
    )
    checkpoint_store.save(updated)
    return updated


def _next_turn_index(conversation):
    return sum(1 for message in conversation.as_messages() if message.get("role") == "user") + 1


def _preview_text(text, *, max_chars=500):
    compacted = " ".join(str(text).split())
    if len(compacted) <= max_chars:
        return compacted
    return compacted[:max_chars].rstrip()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()
