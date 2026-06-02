from wdcode.core.model_runner import ModelRunner


class RecordingClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        return self.response


def test_model_runner_delegates_to_client_chat():
    response = {"role": "assistant", "content": "done"}
    client = RecordingClient(response)
    messages = [{"role": "user", "content": "hello"}]
    tools = [{"type": "function", "function": {"name": "list_files"}}]

    result = ModelRunner(client).call(messages=messages, tools=tools)

    assert result is response
    assert client.calls == [{"messages": messages, "tools": tools}]
