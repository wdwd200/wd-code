class FakeModelClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        if not self.responses:
            raise AssertionError("FakeModelClient has no responses left")
        return self.responses.pop(0)
