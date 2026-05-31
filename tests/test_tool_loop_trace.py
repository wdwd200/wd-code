import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from wdcode.core.conversation import Conversation
from wdcode.core.tool_loop import run_tool_loop
from wdcode.tools import create_default_registry
from wdcode.trace import TraceWriter

from tests.fakes import FakeModelClient


@contextmanager
def local_trace_path():
    temp_root = Path(__file__).resolve().parents[1] / ".test-tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield Path(temp_dir) / "trace.jsonl"
    try:
        temp_root.rmdir()
    except OSError:
        pass


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_run_tool_loop_writes_trace_events_for_tool_round():
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

    with local_trace_path() as trace_path:
        result = run_tool_loop(
            client=client,
            conversation=conversation,
            tool_registry=create_default_registry(project_root),
            trace_writer=TraceWriter(trace_path),
        )

        events = read_jsonl(trace_path)
    event_types = [event["event_type"] for event in events]
    tool_result = next(event for event in events if event["event_type"] == "tool_result")

    assert result == "listed"
    assert event_types == [
        "assistant_message",
        "tool_call",
        "tool_result",
        "assistant_message",
        "final_answer",
    ]
    assert all(event["timestamp"] for event in events)
    assert all("payload" in event for event in events)
    assert events[0]["payload"] == {"content": None, "has_tool_calls": True}
    assert events[1]["payload"] == {
        "tool_call_id": "call_1",
        "name": "list_files",
        "arguments": {"path": "tests"},
    }
    assert tool_result["payload"]["tool_call_id"] == "call_1"
    assert tool_result["payload"]["name"] == "list_files"
    assert tool_result["payload"]["result"]["ok"] is True
    assert "entries" in tool_result["payload"]["result"]["data"]
    assert events[-1]["payload"] == {"content": "listed"}


def test_run_tool_loop_trace_redacts_sensitive_tool_arguments():
    project_root = Path(__file__).resolve().parents[1]
    conversation = Conversation()
    conversation.add_user_message("call a tool with sensitive-looking fields")
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
                            "name": "missing_tool",
                            "arguments": json.dumps(
                                {
                                    "path": "tests",
                                    "api_key": "fake-api-key-value",
                                    "token": "fake-token-value",
                                }
                            ),
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

    with local_trace_path() as trace_path:
        result = run_tool_loop(
            client=client,
            conversation=conversation,
            tool_registry=create_default_registry(project_root),
            trace_writer=TraceWriter(trace_path),
        )

        raw_trace = trace_path.read_text(encoding="utf-8")
        events = read_jsonl(trace_path)
    tool_call = next(event for event in events if event["event_type"] == "tool_call")
    tool_result = next(event for event in events if event["event_type"] == "tool_result")

    assert result == "handled"
    assert tool_call["payload"]["arguments"]["api_key"] == "[REDACTED]"
    assert tool_call["payload"]["arguments"]["token"] == "[REDACTED]"
    assert tool_result["payload"]["result"]["ok"] is False
    assert tool_result["payload"]["result"]["error"]
    assert "fake-api-key-value" not in raw_trace
    assert "fake-token-value" not in raw_trace
