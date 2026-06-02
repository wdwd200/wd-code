import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.fakes import FakeModelClient, run_agent_loop_with_inputs
from wdcode.core.conversation import Conversation
from wdcode.session import SessionStore
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


@contextmanager
def temp_session_dir():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


def test_conversation_can_export_and_restore_messages():
    conversation = Conversation()
    conversation.add_user_message("hello")
    conversation.add_assistant_message("done")

    saved_messages = conversation.to_messages()
    restored = Conversation.from_messages(saved_messages)
    saved_messages[1]["content"] = "mutated"

    assert restored.as_messages() == conversation.as_messages()
    assert conversation.as_messages()[1]["content"] == "hello"


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


def test_run_agent_loop_saves_session_after_successful_user_turn():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        conversation = Conversation()
        client = FakeModelClient([{"role": "assistant", "content": "saved"}])

        outputs, errors = run_agent_loop_with_inputs(
            client,
            ["hello"],
            conversation=conversation,
            tool_registry=None,
            session_store=store,
            session_id="session-success",
        )

        record = store.load("session-success")

    assert errors == []
    assert "\nAssistant> saved" in outputs
    assert record is not None
    assert record.session_id == "session-success"
    assert record.messages == conversation.to_messages()
    assert [message["role"] for message in record.messages] == ["system", "user", "assistant"]


def test_run_agent_loop_restores_existing_session_history():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        first_client = FakeModelClient([{"role": "assistant", "content": "first answer"}])
        run_agent_loop_with_inputs(
            first_client,
            ["first question"],
            tool_registry=None,
            session_store=store,
            session_id="session-restore",
        )

        second_client = FakeModelClient([{"role": "assistant", "content": "second answer"}])
        outputs, errors = run_agent_loop_with_inputs(
            second_client,
            ["second question"],
            tool_registry=None,
            session_store=store,
            session_id="session-restore",
        )
        record = store.load("session-restore")

    model_messages = second_client.calls[0]["messages"]
    assert errors == []
    assert "\nAssistant> second answer" in outputs
    assert any(message == {"role": "user", "content": "first question"} for message in model_messages)
    assert any(message == {"role": "assistant", "content": "first answer"} for message in model_messages)
    assert any(message == {"role": "user", "content": "second question"} for message in model_messages)
    assert record is not None
    assert record.messages[-1] == {"role": "assistant", "content": "second answer"}


def test_run_agent_loop_saves_rolled_back_conversation_after_runtime_error():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        conversation = Conversation()
        client = FakeModelClient(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [make_tool_call(call_id="call_requires_tools")],
                }
            ]
        )

        outputs, errors = run_agent_loop_with_inputs(
            client,
            ["needs a tool"],
            conversation=conversation,
            tool_registry=None,
            session_store=store,
            session_id="session-rollback",
        )

        record = store.load("session-rollback")

    assert "Error: Model requested tools, but no tool registry is available." in errors
    assert not any(output.startswith("\nAssistant>") for output in outputs)
    assert record is not None
    assert record.messages == conversation.to_messages()
    assert record.messages == [{"role": "system", "content": "You are a concise CLI programming assistant."}]
