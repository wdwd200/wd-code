import json
from pathlib import Path

from tests.fakes import FakeModelClient, run_agent_loop_with_inputs
from wdcode.core.conversation import Conversation
from wdcode.tools import create_default_registry


def test_run_agent_loop_outputs_final_answer_without_tools():
    conversation = Conversation()
    client = FakeModelClient(
        [
            {
                "role": "assistant",
                "content": "done",
            }
        ]
    )

    outputs, errors = run_agent_loop_with_inputs(
        client,
        ["hello"],
        conversation=conversation,
        tool_registry=None,
    )

    assert errors == []
    assert "\nAssistant> done" in outputs
    assert conversation.messages[-1] == {"role": "assistant", "content": "done"}
    assert len(client.calls) == 1
    assert client.calls[0]["tools"] is None


def test_run_agent_loop_executes_tool_call_and_records_tool_result():
    project_root = Path(__file__).resolve().parents[1]
    conversation = Conversation()
    client = FakeModelClient(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "list_files",
                            "arguments": json.dumps({"path": "tests"}),
                        },
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "listed",
            },
        ]
    )

    outputs, errors = run_agent_loop_with_inputs(
        client,
        ["list the tests directory"],
        conversation=conversation,
        tool_registry=create_default_registry(project_root),
    )

    tool_message = next(message for message in conversation.messages if message["role"] == "tool")
    tool_content = json.loads(tool_message["content"])

    assert errors == []
    assert "\nAssistant> listed" in outputs
    assert len(client.calls) == 2
    assert client.calls[0]["tools"]
    assert any(message["role"] == "assistant" and message.get("tool_calls") for message in conversation.messages)
    assert tool_message["tool_call_id"] == "call_1"
    assert tool_message["name"] == "list_files"
    assert tool_content["ok"] is True
    assert "entries" in tool_content["data"]
    assert tool_content["error"] is None
    assert isinstance(tool_content["metadata"], dict)


def test_run_agent_loop_records_unified_failure_for_bad_tool_arguments():
    project_root = Path(__file__).resolve().parents[1]
    conversation = Conversation()
    client = FakeModelClient(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_bad",
                        "type": "function",
                        "function": {
                            "name": "list_files",
                            "arguments": "{bad json",
                        },
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "handled",
            },
        ]
    )

    outputs, errors = run_agent_loop_with_inputs(
        client,
        ["call a tool with invalid arguments"],
        conversation=conversation,
        tool_registry=create_default_registry(project_root),
    )

    tool_message = next(message for message in conversation.messages if message["role"] == "tool")
    tool_content = json.loads(tool_message["content"])

    assert errors == []
    assert "\nAssistant> handled" in outputs
    assert tool_content["ok"] is False
    assert tool_content["data"] is None
    assert "Invalid tool arguments" in tool_content["error"]
    assert isinstance(tool_content["metadata"], dict)
