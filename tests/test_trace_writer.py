import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from wdcode.trace import TraceWriter


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


def test_trace_writer_writes_jsonl_events():
    with local_trace_path() as trace_path:
        writer = TraceWriter(trace_path)

        writer.write_event("example", {"message": "hello"})

        events = read_jsonl(trace_path)
        assert len(events) == 1
        assert events[0]["event_type"] == "example"
        assert events[0]["timestamp"]
        assert events[0]["payload"] == {"message": "hello"}


def test_trace_writer_redacts_sensitive_fields_recursively():
    with local_trace_path() as trace_path:
        writer = TraceWriter(trace_path)

        writer.write_event(
            "credentials",
            {
                "api_key": "fake-api-key-value",
                "nested": {
                    "access_token": "fake-token-value",
                    "items": [
                        {"password": "fake-password-value"},
                        {"safe": "visible"},
                    ],
                },
            },
        )

        event = read_jsonl(trace_path)[0]
        assert event["payload"]["api_key"] == "[REDACTED]"
        assert event["payload"]["nested"]["access_token"] == "[REDACTED]"
        assert event["payload"]["nested"]["items"][0]["password"] == "[REDACTED]"
        assert event["payload"]["nested"]["items"][1]["safe"] == "visible"
        assert "fake-api-key-value" not in trace_path.read_text(encoding="utf-8")
        assert "fake-token-value" not in trace_path.read_text(encoding="utf-8")
