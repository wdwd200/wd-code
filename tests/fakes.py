class FakeModelClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        if not self.responses:
            raise AssertionError("FakeModelClient has no responses left")
        return self.responses.pop(0)


class InputSequence:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self, prompt):
        if not self.values:
            raise EOFError
        return self.values.pop(0)


def run_agent_loop_with_inputs(client, inputs, **kwargs):
    from wdcode.core.agent_loop import run_agent_loop

    outputs = []
    errors = []
    run_agent_loop(
        client=client,
        input_fn=InputSequence(inputs),
        output_fn=outputs.append,
        error_fn=errors.append,
        **kwargs,
    )
    return outputs, errors
