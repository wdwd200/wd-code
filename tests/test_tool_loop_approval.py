import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from wdcode.core.conversation import Conversation
from wdcode.core.tool_loop import run_tool_loop
from wdcode.tools import create_default_registry

from tests.fakes import FakeModelClient


@contextmanager
def project_temp_dir():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield project_root, Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


def test_run_tool_loop_dry_run_records_blocked_tool_result():
    with project_temp_dir() as (project_root, temp_dir):
        target = temp_dir / "created.txt"
        relative_target = target.relative_to(project_root).as_posix()
        conversation = Conversation()
        conversation.add_user_message("write a file")
        client = FakeModelClient(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_write",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps(
                                    {
                                        "path": relative_target,
                                        "content": "should not be written",
                                    }
                                ),
                            },
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": "blocked",
                },
            ]
        )

        result = run_tool_loop(
            client=client,
            conversation=conversation,
            tool_registry=create_default_registry(project_root),
            approval_mode="dry_run",
        )

        tool_message = next(message for message in conversation.messages if message["role"] == "tool")
        tool_content = json.loads(tool_message["content"])

        assert result == "blocked"
        assert tool_message["tool_call_id"] == "call_write"
        assert tool_message["name"] == "write_file"
        assert tool_content["ok"] is False
        assert "Dry-run" in tool_content["error"]
        assert tool_content["metadata"]["approval_mode"] == "dry_run"
        assert tool_content["metadata"]["dry_run"] is True
        assert tool_content["metadata"]["tool_name"] == "write_file"
        assert not target.exists()
