import json
from pathlib import Path

from tests.fakes import FakeModelClient, run_agent_loop_with_inputs
from wdcode.core.conversation import Conversation
from wdcode.tools import create_default_registry


def make_tool_call(name="list_files", arguments=None, call_id="call_1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments or {"path": "tests"}),
        },
    }


class RecordingContextProvider:
    def __init__(self):
        self.calls = []

    def build(self, *, user_input, conversation):
        self.calls.append({"user_input": user_input, "conversation": conversation})
        return None


def test_run_agent_loop_builds_context_before_model_call():
    conversation = Conversation()
    context_provider = RecordingContextProvider()
    client = FakeModelClient([{"role": "assistant", "content": "done"}])

    outputs, errors = run_agent_loop_with_inputs(
        client,
        ["hello"],
        conversation=conversation,
        tool_registry=None,
        context_provider=context_provider,
    )

    assert errors == []
    assert "\nAssistant> done" in outputs
    assert context_provider.calls == [{"user_input": "hello", "conversation": conversation}]
    assert client.calls[0]["messages"] == conversation.as_messages()[:-1]


def test_run_agent_loop_stops_when_model_never_returns_final_answer():
    project_root = Path(__file__).resolve().parents[1]
    conversation = Conversation()
    client = FakeModelClient(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [make_tool_call(call_id="call_1")],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [make_tool_call(call_id="call_2")],
            },
        ]
    )

    outputs, errors = run_agent_loop_with_inputs(
        client,
        ["keep listing"],
        conversation=conversation,
        tool_registry=create_default_registry(project_root),
        max_rounds=2,
    )

    message = "Tool loop stopped before the model returned a final answer."
    assert errors == []
    assert f"\nAssistant> {message}" in outputs
    assert conversation.messages[-1] == {"role": "assistant", "content": message}


def test_run_agent_loop_reports_too_many_tool_calls_in_one_response():
    project_root = Path(__file__).resolve().parents[1]
    conversation = Conversation()
    client = FakeModelClient(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    make_tool_call(call_id=f"call_{index}")
                    for index in range(5)
                ],
            }
        ]
    )

    outputs, errors = run_agent_loop_with_inputs(
        client,
        ["call many tools"],
        conversation=conversation,
        tool_registry=create_default_registry(project_root),
    )

    assert "Error: Too many tool calls in one model response." in errors
    assert not any(output.startswith("\nAssistant>") for output in outputs)
    assert conversation.messages == conversation.as_messages()[:1]
