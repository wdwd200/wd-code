import json
from pathlib import Path

from wdcode.core.conversation import Conversation
from wdcode.core.tool_loop import run_tool_loop
from wdcode.tools import create_default_registry

from tests.fakes import FakeModelClient


def test_run_tool_loop_returns_final_answer_without_tools():
    conversation = Conversation()
    conversation.add_user_message("hello")
    client = FakeModelClient(
        [
            {
                "role": "assistant",
                "content": "done",
            }
        ]
    )

    result = run_tool_loop(client=client, conversation=conversation, tool_registry=None)

    assert result == "done"
    assert conversation.messages[-1] == {"role": "assistant", "content": "done"}
    assert len(client.calls) == 1
    assert client.calls[0]["tools"] is None


def test_run_tool_loop_executes_tool_call_and_records_tool_result():
    project_root = Path(__file__).resolve().parents[1]
    conversation = Conversation()
    conversation.add_user_message("list the tests directory")
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

    result = run_tool_loop(
        client=client,
        conversation=conversation,
        tool_registry=create_default_registry(project_root),
    )

    tool_message = next(message for message in conversation.messages if message["role"] == "tool")
    tool_content = json.loads(tool_message["content"])

    assert result == "listed"
    assert len(client.calls) == 2
    assert client.calls[0]["tools"]
    assert any(message["role"] == "assistant" and message.get("tool_calls") for message in conversation.messages)
    assert tool_message["tool_call_id"] == "call_1"
    assert tool_message["name"] == "list_files"
    assert tool_content["ok"] is True
    assert "entries" in tool_content["data"]
    assert tool_content["error"] is None
    assert isinstance(tool_content["metadata"], dict)


def test_run_tool_loop_records_unified_failure_for_bad_tool_arguments():
    project_root = Path(__file__).resolve().parents[1]
    conversation = Conversation()
    conversation.add_user_message("call a tool with invalid arguments")
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

    result = run_tool_loop(
        client=client,
        conversation=conversation,
        tool_registry=create_default_registry(project_root),
    )

    tool_message = next(message for message in conversation.messages if message["role"] == "tool")
    tool_content = json.loads(tool_message["content"])

    assert result == "handled"
    assert tool_content["ok"] is False
    assert tool_content["data"] is None
    assert "Invalid tool arguments" in tool_content["error"]
    assert isinstance(tool_content["metadata"], dict)
