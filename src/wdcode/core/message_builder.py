def build_model_messages(conversation, context=None):
    messages = conversation.as_messages()
    recovery_summary_text = _recovery_summary_text(getattr(conversation, "recovery_summary", None))
    context_text = getattr(context, "text", "")
    if not recovery_summary_text and not context_text:
        return messages

    extra_messages = []
    if recovery_summary_text:
        extra_messages.append(
            {
                "role": "system",
                "content": f"# Session Recovery Summary\n\n{recovery_summary_text}",
            }
        )
    if context_text:
        extra_messages.append(
            {
                "role": "system",
                "content": context_text,
            }
        )

    if messages and messages[0].get("role") == "system":
        return [messages[0], *extra_messages, *messages[1:]]
    return [*extra_messages, *messages]


def _recovery_summary_text(recovery_summary):
    if not recovery_summary:
        return ""
    if isinstance(recovery_summary, dict):
        return str(recovery_summary.get("summary") or "")
    if hasattr(recovery_summary, "summary"):
        return str(recovery_summary.summary)
    return str(recovery_summary)
