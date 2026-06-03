import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.fakes import FakeModelClient, run_agent_loop_with_inputs
from wdcode.core.conversation import Conversation
from wdcode.core.failure_recovery import RetryPolicy
from wdcode.context.provider import ContextBundle
from wdcode.session import CheckpointStore, CompressionPolicy, SessionStore
from wdcode.tools import create_default_registry
from wdcode.tools.base import Tool
from wdcode.tools.registry import ToolRegistry


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


class SnapshotContextProvider:
    def build(self, *, user_input, conversation):
        return ContextBundle(
            text="# Project Context\n\nSnapshot context",
            metadata={"source": "test"},
        )


class RaisingOnceClient:
    def __init__(self, exc, response):
        self.exc = exc
        self.response = response
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        if len(self.calls) == 1:
            raise self.exc
        return self.response


def make_long_conversation(turn_count=5):
    conversation = Conversation()
    for index in range(turn_count):
        conversation.add_user_message(
            f"old request {index} editing src/wdcode/core/agent_loop.py"
        )
        conversation.add_assistant_message(
            f"old answer {index} covered tests/test_agent_loop_orchestration.py"
        )
    return conversation


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
    assert record.recovery_summary is None


def test_run_agent_loop_saves_checkpoint_for_successful_session_turn():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        conversation = Conversation()
        conversation.add_user_message("old question")
        conversation.add_assistant_message("old answer")
        client = FakeModelClient([{"role": "assistant", "content": "saved"}])

        outputs, errors = run_agent_loop_with_inputs(
            client,
            ["hello"],
            conversation=conversation,
            tool_registry=None,
            context_provider=SnapshotContextProvider(),
            session_store=store,
            session_id="session-checkpoint",
        )

        checkpoint_store = CheckpointStore(session_dir / "checkpoints")
        checkpoints = checkpoint_store.list_for_session("session-checkpoint")
        record = store.load("session-checkpoint")

    assert errors == []
    assert "\nAssistant> saved" in outputs
    assert len(checkpoints) == 1
    assert checkpoints[0].messages == [
        {"role": "system", "content": "You are a concise CLI programming assistant."},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
    ]
    assert checkpoints[0].metadata["user_input_preview"] == "hello"
    assert checkpoints[0].context_snapshot["has_text"] is True
    assert checkpoints[0].context_snapshot["text_preview"].startswith("# Project Context")
    assert record.metadata["latest_checkpoint_id"] == checkpoints[0].checkpoint_id
    assert "rollback_checkpoint_id" not in record.metadata


def test_run_agent_loop_retries_model_timeout_then_completes_turn():
    conversation = Conversation()
    client = RaisingOnceClient(
        TimeoutError("temporary model timeout"),
        {"role": "assistant", "content": "recovered"},
    )

    outputs, errors = run_agent_loop_with_inputs(
        client,
        ["hello"],
        conversation=conversation,
        tool_registry=None,
        model_retry_policy=RetryPolicy(max_attempts=2),
    )

    assert errors == []
    assert "\nAssistant> recovered" in outputs
    assert len(client.calls) == 2
    assert conversation.messages[-1] == {"role": "assistant", "content": "recovered"}


def test_run_agent_loop_records_successful_retry_report_in_session_metadata():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        client = RaisingOnceClient(
            TimeoutError("temporary model timeout"),
            {"role": "assistant", "content": "recovered"},
        )

        outputs, errors = run_agent_loop_with_inputs(
            client,
            ["hello"],
            tool_registry=None,
            session_store=store,
            session_id="session-retry-success",
            model_retry_policy=RetryPolicy(max_attempts=2),
        )

        record = store.load("session-retry-success")

    assert errors == []
    assert "\nAssistant> recovered" in outputs
    assert record is not None
    assert record.metadata["latest_failure_component"] == "model"
    assert record.metadata["latest_failure_category"] == "timeout"
    assert record.metadata["latest_failure_attempts"] == 1
    assert record.metadata["latest_failure_report"]["final_status"] == "success"


def test_run_agent_loop_rolls_back_and_records_model_final_failure_report():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        conversation = Conversation()
        client = FakeModelClient([])

        outputs, errors = run_agent_loop_with_inputs(
            client,
            ["hello"],
            conversation=conversation,
            tool_registry=None,
            context_provider=SnapshotContextProvider(),
            session_store=store,
            session_id="session-model-failure",
            model_retry_policy=RetryPolicy(max_attempts=2),
        )

        checkpoint = CheckpointStore(session_dir / "checkpoints").latest_for_session(
            "session-model-failure"
        )
        record = store.load("session-model-failure")

    assert "Error: FakeModelClient has no responses left" in errors
    assert not any(output.startswith("\nAssistant>") for output in outputs)
    assert conversation.messages == [
        {"role": "system", "content": "You are a concise CLI programming assistant."}
    ]
    assert checkpoint is not None
    assert checkpoint.metadata["rolled_back"] is True
    assert record.metadata["rollback_checkpoint_id"] == checkpoint.checkpoint_id
    assert record.metadata["latest_failure_component"] == "model"
    assert record.metadata["latest_failure_report"]["final_status"] == "failed"
    assert "Traceback" not in json.dumps(record.metadata["latest_failure_report"])


def test_run_agent_loop_final_runtime_failure_keeps_prior_retry_events():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        client = RaisingOnceClient(
            TimeoutError("temporary model timeout"),
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [make_tool_call(call_id="call_requires_tools")],
            },
        )

        outputs, errors = run_agent_loop_with_inputs(
            client,
            ["needs unavailable tool"],
            tool_registry=None,
            session_store=store,
            session_id="session-retry-then-runtime-failure",
            model_retry_policy=RetryPolicy(max_attempts=2),
        )

        record = store.load("session-retry-then-runtime-failure")

    assert "Error: Model requested tools, but no tool registry is available." in errors
    assert not any(output.startswith("\nAssistant>") for output in outputs)
    assert record is not None
    report = record.metadata["latest_failure_report"]
    assert report["final_status"] == "failed"
    assert [event["component"] for event in report["events"]] == ["model", "runtime"]
    assert record.metadata["latest_failure_component"] == "runtime"


def test_run_agent_loop_checkpoint_captures_tool_call_snapshot_before_execution():
    project_root = Path(__file__).resolve().parents[1]
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        client = FakeModelClient(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [make_tool_call(arguments={"path": "tests"}, call_id="call_list")],
                },
                {"role": "assistant", "content": "listed"},
            ]
        )

        outputs, errors = run_agent_loop_with_inputs(
            client,
            ["list tests"],
            tool_registry=create_default_registry(project_root),
            context_provider=SnapshotContextProvider(),
            session_store=store,
            session_id="session-tool-checkpoint",
        )

        checkpoint = CheckpointStore(session_dir / "checkpoints").latest_for_session(
            "session-tool-checkpoint"
        )

    assert errors == []
    assert "\nAssistant> listed" in outputs
    assert checkpoint is not None
    assert checkpoint.tool_call_snapshot == [
        {
            "tool_call_id": "call_list",
            "name": "list_files",
            "arguments_preview": "{\"path\": \"tests\"}",
            "arguments_truncated": False,
        }
    ]
    assert checkpoint.metadata["stage"] == "context_built"


def test_run_agent_loop_default_tool_policy_does_not_retry_execution_failure():
    project_root = Path(__file__).resolve().parents[1]
    registry = ToolRegistry(project_root)
    attempts = []

    def failing_tool(arguments):
        attempts.append(arguments)
        raise RuntimeError("tool failed")

    registry.register(
        Tool(
            name="list_files",
            description="Failing tool.",
            parameters={"type": "object"},
            execute=failing_tool,
        )
    )
    conversation = Conversation()
    client = FakeModelClient(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [make_tool_call(call_id="call_fails")],
            },
            {"role": "assistant", "content": "handled"},
        ]
    )

    outputs, errors = run_agent_loop_with_inputs(
        client,
        ["call failing tool"],
        conversation=conversation,
        tool_registry=registry,
    )

    tool_message = next(message for message in conversation.messages if message["role"] == "tool")
    tool_content = json.loads(tool_message["content"])

    assert errors == []
    assert "\nAssistant> handled" in outputs
    assert len(attempts) == 1
    assert tool_content["ok"] is False
    assert "tool failed" in tool_content["error"]


def test_run_agent_loop_explicit_tool_retry_retries_execution_failure():
    project_root = Path(__file__).resolve().parents[1]
    registry = ToolRegistry(project_root)
    attempts = []

    def flaky_tool(arguments):
        attempts.append(arguments)
        if len(attempts) == 1:
            raise RuntimeError("temporary tool failure")
        return {"status": "ok"}

    registry.register(
        Tool(
            name="list_files",
            description="Flaky tool.",
            parameters={"type": "object"},
            execute=flaky_tool,
        )
    )
    conversation = Conversation()
    client = FakeModelClient(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [make_tool_call(call_id="call_flaky")],
            },
            {"role": "assistant", "content": "handled"},
        ]
    )

    outputs, errors = run_agent_loop_with_inputs(
        client,
        ["call flaky tool"],
        conversation=conversation,
        tool_registry=registry,
        tool_retry_policy=RetryPolicy(max_attempts=2, retry_tool_errors=True),
    )

    tool_message = next(message for message in conversation.messages if message["role"] == "tool")
    tool_content = json.loads(tool_message["content"])

    assert errors == []
    assert "\nAssistant> handled" in outputs
    assert len(attempts) == 2
    assert tool_content["ok"] is True
    assert tool_content["data"] == {"status": "ok"}


def test_run_agent_loop_records_rollback_checkpoint_id_in_session_metadata():
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
            context_provider=SnapshotContextProvider(),
            session_store=store,
            session_id="session-rollback-checkpoint",
        )

        checkpoint = CheckpointStore(session_dir / "checkpoints").latest_for_session(
            "session-rollback-checkpoint"
        )
        record = store.load("session-rollback-checkpoint")

    assert "Error: Model requested tools, but no tool registry is available." in errors
    assert not any(output.startswith("\nAssistant>") for output in outputs)
    assert checkpoint is not None
    assert checkpoint.metadata["rolled_back"] is True
    assert checkpoint.metadata["stage"] == "rolled_back"
    assert record.metadata["latest_checkpoint_id"] == checkpoint.checkpoint_id
    assert record.metadata["rollback_checkpoint_id"] == checkpoint.checkpoint_id
    assert checkpoint.messages == [
        {"role": "system", "content": "You are a concise CLI programming assistant."}
    ]


def test_run_agent_loop_without_session_store_does_not_create_default_checkpoints():
    with temp_session_dir() as session_dir:
        client = FakeModelClient([{"role": "assistant", "content": "done"}])

        outputs, errors = run_agent_loop_with_inputs(
            client,
            ["hello"],
            tool_registry=None,
            context_provider=SnapshotContextProvider(),
        )

    assert errors == []
    assert "\nAssistant> done" in outputs
    assert not (session_dir / "checkpoints").exists()


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
    assert record.recovery_summary is None


def test_run_agent_loop_writes_recovery_summary_for_long_conversation():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        conversation = Conversation()
        for index in range(6):
            conversation.add_user_message(f"old request {index}")
            conversation.add_assistant_message(f"old answer {index}")
        client = FakeModelClient([{"role": "assistant", "content": "new answer"}])

        outputs, errors = run_agent_loop_with_inputs(
            client,
            ["new request"],
            conversation=conversation,
            tool_registry=None,
            session_store=store,
            session_id="session-long",
            summary_trigger_messages=8,
            keep_recent_messages=4,
        )

        record = store.load("session-long")

    assert errors == []
    assert "\nAssistant> new answer" in outputs
    assert record is not None
    assert record.recovery_summary is not None
    assert record.recovery_summary["source_message_count"] == len(record.messages) - 4
    assert record.recovery_summary["recent_message_count"] == 4
    assert "old request 0" in record.recovery_summary["summary"]
    assert record.messages == conversation.to_messages()


def test_run_agent_loop_restores_recovery_summary_into_model_messages():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        conversation = Conversation()
        for index in range(6):
            conversation.add_user_message(f"old request {index}")
            conversation.add_assistant_message(f"old answer {index}")
        first_client = FakeModelClient([{"role": "assistant", "content": "first new answer"}])
        run_agent_loop_with_inputs(
            first_client,
            ["first new request"],
            conversation=conversation,
            tool_registry=None,
            session_store=store,
            session_id="session-recovery-injection",
            summary_trigger_messages=8,
            keep_recent_messages=4,
        )

        second_client = FakeModelClient([{"role": "assistant", "content": "second answer"}])
        outputs, errors = run_agent_loop_with_inputs(
            second_client,
            ["second request"],
            tool_registry=None,
            session_store=store,
            session_id="session-recovery-injection",
            summary_trigger_messages=100,
            keep_recent_messages=4,
        )

    model_messages = second_client.calls[0]["messages"]
    assert errors == []
    assert "\nAssistant> second answer" in outputs
    assert model_messages[0]["role"] == "system"
    assert model_messages[1]["role"] == "system"
    assert model_messages[1]["content"].startswith("# Session Recovery Summary")
    assert "old request 0" in model_messages[1]["content"]


def test_run_agent_loop_saves_recovery_summary_after_rollback_for_long_conversation():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        conversation = Conversation()
        for index in range(6):
            conversation.add_user_message(f"old request {index}")
            conversation.add_assistant_message(f"old answer {index}")
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
            ["request that rolls back"],
            conversation=conversation,
            tool_registry=None,
            session_store=store,
            session_id="session-long-rollback",
            summary_trigger_messages=8,
            keep_recent_messages=4,
        )

        record = store.load("session-long-rollback")

    assert "Error: Model requested tools, but no tool registry is available." in errors
    assert not any(output.startswith("\nAssistant>") for output in outputs)
    assert record is not None
    assert record.messages == conversation.to_messages()
    assert record.recovery_summary is not None
    assert "request that rolls back" not in record.recovery_summary["summary"]


def test_run_agent_loop_compresses_long_conversation_before_model_call():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        conversation = make_long_conversation(turn_count=5)
        full_message_count_before_turn = len(conversation.to_messages())
        client = FakeModelClient([{"role": "assistant", "content": "compressed"}])

        outputs, errors = run_agent_loop_with_inputs(
            client,
            ["new request"],
            conversation=conversation,
            tool_registry=None,
            context_provider=SnapshotContextProvider(),
            session_store=store,
            session_id="session-compression",
            compression_policy=CompressionPolicy(
                trigger_message_count=6,
                keep_recent_messages=4,
            ),
        )

        record = store.load("session-compression")

    model_messages = client.calls[0]["messages"]
    model_contents = [message.get("content") for message in model_messages]

    assert errors == []
    assert "\nAssistant> compressed" in outputs
    assert record is not None
    assert record.compression_summary is not None
    assert record.compression_summary["summary"].startswith("# Compressed Conversation History")
    assert record.messages == conversation.to_messages()
    assert len(record.messages) == full_message_count_before_turn + 2
    assert model_messages[0]["role"] == "system"
    assert model_messages[1]["role"] == "system"
    assert model_messages[1]["content"].startswith("# Compressed Conversation History")
    assert {"role": "system", "content": "# Project Context\n\nSnapshot context"} in model_messages
    assert any(content == "new request" for content in model_contents)
    assert not any(content == "old request 0 editing src/wdcode/core/agent_loop.py" for content in model_contents)
    assert len([message for message in model_messages if message["role"] in {"user", "assistant"}]) == 4


def test_run_agent_loop_compression_works_without_session_store():
    conversation = make_long_conversation(turn_count=4)
    client = FakeModelClient([{"role": "assistant", "content": "compressed"}])

    outputs, errors = run_agent_loop_with_inputs(
        client,
        ["new request"],
        conversation=conversation,
        tool_registry=None,
        context_provider=SnapshotContextProvider(),
        compression_policy=CompressionPolicy(
            trigger_message_count=5,
            keep_recent_messages=3,
        ),
    )

    model_messages = client.calls[0]["messages"]

    assert errors == []
    assert "\nAssistant> compressed" in outputs
    assert conversation.compression_summary is not None
    assert model_messages[1]["content"].startswith("# Compressed Conversation History")
    assert len([message for message in model_messages if message["role"] in {"user", "assistant"}]) == 3


def test_run_agent_loop_saves_rollback_state_compression_summary():
    with temp_session_dir() as session_dir:
        store = SessionStore(session_dir)
        conversation = make_long_conversation(turn_count=5)
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
            ["request that rolls back"],
            conversation=conversation,
            tool_registry=None,
            context_provider=SnapshotContextProvider(),
            session_store=store,
            session_id="session-compression-rollback",
            compression_policy=CompressionPolicy(
                trigger_message_count=6,
                keep_recent_messages=4,
            ),
        )

        checkpoint = CheckpointStore(session_dir / "checkpoints").latest_for_session(
            "session-compression-rollback"
        )
        record = store.load("session-compression-rollback")

    assert "Error: Model requested tools, but no tool registry is available." in errors
    assert not any(output.startswith("\nAssistant>") for output in outputs)
    assert record is not None
    assert record.messages == conversation.to_messages()
    assert "request that rolls back" not in json.dumps(record.messages)
    assert record.compression_summary is not None
    assert checkpoint is not None
    assert checkpoint.metadata["rolled_back"] is True
    assert checkpoint.metadata["compression_summary_present"] is True


def test_run_agent_loop_compression_does_not_break_model_retry():
    conversation = make_long_conversation(turn_count=4)
    client = RaisingOnceClient(
        TimeoutError("temporary model timeout"),
        {"role": "assistant", "content": "recovered"},
    )

    outputs, errors = run_agent_loop_with_inputs(
        client,
        ["new request"],
        conversation=conversation,
        tool_registry=None,
        context_provider=SnapshotContextProvider(),
        model_retry_policy=RetryPolicy(max_attempts=2),
        compression_policy=CompressionPolicy(
            trigger_message_count=5,
            keep_recent_messages=3,
        ),
    )

    assert errors == []
    assert "\nAssistant> recovered" in outputs
    assert len(client.calls) == 2
    assert client.calls[0]["messages"][1]["content"].startswith("# Compressed Conversation History")
    assert client.calls[1]["messages"][1]["content"].startswith("# Compressed Conversation History")
