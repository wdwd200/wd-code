def build_model_messages(
    conversation,
    context=None,
    *,
    compression_summary=None,
    keep_recent_messages=None,
):
    messages = conversation.as_messages()
    recovery_summary_text = _recovery_summary_text(getattr(conversation, "recovery_summary", None))
    compression_summary = (
        compression_summary
        if compression_summary is not None
        else getattr(conversation, "compression_summary", None)
    )
    compression_summary_text = _compression_summary_text(compression_summary)
    recent_message_count = _compression_keep_recent(
        compression_summary,
        keep_recent_messages=keep_recent_messages,
    )
    context_text = getattr(context, "text", "")
    if not recovery_summary_text and not compression_summary_text and not context_text:
        return messages

    extra_messages = []
    if recovery_summary_text:
        extra_messages.append(
            {
                "role": "system",
                "content": f"# Session Recovery Summary\n\n{recovery_summary_text}",
            }
        )
    if compression_summary_text:
        extra_messages.append(
            {
                "role": "system",
                "content": _format_compression_summary(compression_summary_text),
            }
        )
    if context_text:
        extra_messages.append(
            {
                "role": "system",
                "content": context_text,
            }
        )

    body_messages = messages[1:] if messages and messages[0].get("role") == "system" else messages
    if compression_summary_text and recent_message_count is not None:
        body_messages = body_messages[-recent_message_count:]

    if messages and messages[0].get("role") == "system":
        return [messages[0], *extra_messages, *body_messages]
    return [*extra_messages, *body_messages]


def _recovery_summary_text(recovery_summary):
    if not recovery_summary:
        return ""
    if isinstance(recovery_summary, dict):
        return str(recovery_summary.get("summary") or "")
    if hasattr(recovery_summary, "summary"):
        return str(recovery_summary.summary)
    return str(recovery_summary)


def _compression_summary_text(compression_summary):
    if not compression_summary:
        return ""
    if isinstance(compression_summary, dict):
        return str(compression_summary.get("summary") or "")
    if hasattr(compression_summary, "summary"):
        return str(compression_summary.summary)
    return str(compression_summary)


def _compression_keep_recent(compression_summary, *, keep_recent_messages):
    if keep_recent_messages is not None:
        if keep_recent_messages <= 0:
            raise ValueError("keep_recent_messages must be greater than zero.")
        return keep_recent_messages
    if isinstance(compression_summary, dict):
        value = compression_summary.get("kept_recent_message_count")
        if isinstance(value, int) and value > 0:
            return value
    if hasattr(compression_summary, "kept_recent_message_count"):
        value = compression_summary.kept_recent_message_count
        if isinstance(value, int) and value > 0:
            return value
    return None


def _format_compression_summary(summary_text):
    if summary_text.lstrip().startswith("# Compressed Conversation History"):
        return summary_text
    return f"# Compressed Conversation History\n\n{summary_text}"
