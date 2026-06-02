import json
from pathlib import Path

import pytest

from tests.fakes import FakeModelClient
from wdcode.core.agent_loop import run_agent_turn
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


def test_run_agent_turn_builds_context_before_model_call():
    conversation = Conversation()
    conversation.add_user_message("hello")
    context_provider = RecordingContextProvider()
    client = FakeModelClient([{"role": "assistant", "content": "done"}])

    result = run_agent_turn(
        client=client,
        conversation=conversation,
        tool_registry=None,
        user_input="hello",
        context_provider=context_provider,
    )

    assert result == "done"
    assert context_provider.calls == [{"user_input": "hello", "conversation": conversation}]
    assert client.calls[0]["messages"] == conversation.as_messages()[:-1]


def test_run_agent_turn_stops_when_model_never_returns_final_answer():
    project_root = Path(__file__).resolve().parents[1]
    conversation = Conversation()
    conversation.add_user_message("keep listing")
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

    result = run_agent_turn(
        client=client,
        conversation=conversation,
        tool_registry=create_default_registry(project_root),
        max_rounds=2,
    )

    assert result == "Tool loop stopped before the model returned a final answer."
    assert conversation.messages[-1] == {"role": "assistant", "content": result}


def test_run_agent_turn_rejects_too_many_tool_calls_in_one_response():
    project_root = Path(__file__).resolve().parents[1]
    conversation = Conversation()
    conversation.add_user_message("call many tools")
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

    with pytest.raises(RuntimeError, match="Too many tool calls in one model response"):
        run_agent_turn(
            client=client,
            conversation=conversation,
            tool_registry=create_default_registry(project_root),
        )
