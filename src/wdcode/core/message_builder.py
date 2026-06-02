def build_model_messages(conversation, context=None):
    messages = conversation.as_messages()
    context_text = getattr(context, "text", "")
    if not context_text:
        return messages

    context_message = {
        "role": "system",
        "content": context_text,
    }
    if messages and messages[0].get("role") == "system":
        return [messages[0], context_message, *messages[1:]]
    return [context_message, *messages]
