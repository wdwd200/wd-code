SYSTEM_PROMPT = "You are a concise CLI programming assistant."


class Conversation:
    def __init__(self, system_prompt=SYSTEM_PROMPT):
        self.messages = [
            {
                "role": "system",
                "content": system_prompt,
            }
        ]

    def add_user_message(self, content):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content):
        self.messages.append({"role": "assistant", "content": content})

    def add_assistant_tool_call_message(self, message):
        self.messages.append(
            {
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": list(message.get("tool_calls") or []),
            }
        )

    def add_tool_result(self, tool_call_id, name, content):
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": content,
            }
        )

    def remove_last_message(self):
        if len(self.messages) > 1:
            self.messages.pop()

    def checkpoint(self):
        return len(self.messages)

    def rollback(self, checkpoint):
        if checkpoint < 1:
            checkpoint = 1
        del self.messages[checkpoint:]

    def as_messages(self):
        return list(self.messages)
