import copy
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from wdcode.session import (
    CheckpointStore,
    TurnCheckpoint,
    build_context_snapshot,
    build_file_change_snapshot,
    build_tool_call_snapshot,
    build_turn_checkpoint,
    restore_conversation_from_checkpoint,
)


@contextmanager
def temp_checkpoint_dir():
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "test_tmp"
    temp_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as temp_dir:
        yield Path(temp_dir)
    try:
        temp_root.rmdir()
    except OSError:
        pass


class ContextStub:
    def __init__(self, text="", metadata=None):
        self.text = text
        self.metadata = metadata


def make_messages():
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
    ]


def make_recovery_summary():
    return {
        "summary": "# Recovery Summary\n\nEarlier work.",
        "source_message_count": 10,
        "recent_message_count": 2,
        "metadata": {"generated_by": "rule_based"},
    }


def make_checkpoint(session_id="session-a", turn_index=1):
    return build_turn_checkpoint(
        session_id=session_id,
        turn_index=turn_index,
        messages=make_messages(),
        recovery_summary=make_recovery_summary(),
        context_snapshot={"has_text": True, "char_count": 3},
        tool_call_snapshot=[{"tool_call_id": "call_1", "name": "list_files"}],
        file_change_snapshot={"available": False, "reason": "test"},
        metadata={"stage": "pre_turn"},
    )


def test_build_turn_checkpoint_deep_copies_messages():
    messages = make_messages()

    checkpoint = build_turn_checkpoint(
        session_id="session-copy",
        turn_index=1,
        messages=messages,
    )
    messages[1]["content"] = "mutated"

    assert checkpoint.messages[1]["content"] == "hello"


def test_build_turn_checkpoint_rejects_invalid_session_id():
    with pytest.raises(ValueError):
        build_turn_checkpoint(
            session_id="../bad",
            turn_index=1,
            messages=make_messages(),
        )


def test_build_turn_checkpoint_rejects_negative_turn_index():
    with pytest.raises(ValueError, match="turn_index"):
        build_turn_checkpoint(
            session_id="session-a",
            turn_index=-1,
            messages=make_messages(),
        )


def test_checkpoint_store_save_and_load_preserves_fields():
    with temp_checkpoint_dir() as checkpoint_dir:
        store = CheckpointStore(checkpoint_dir)
        checkpoint = make_checkpoint()

        store.save(checkpoint)
        loaded = store.load(checkpoint.session_id, checkpoint.checkpoint_id)

    assert loaded == checkpoint
    assert loaded is not checkpoint
    assert loaded.messages == checkpoint.messages
    assert loaded.recovery_summary == checkpoint.recovery_summary
    assert loaded.context_snapshot == checkpoint.context_snapshot
    assert loaded.tool_call_snapshot == checkpoint.tool_call_snapshot
    assert loaded.file_change_snapshot == checkpoint.file_change_snapshot
    assert loaded.metadata == checkpoint.metadata


def test_checkpoint_store_load_missing_returns_none():
    with temp_checkpoint_dir() as checkpoint_dir:
        store = CheckpointStore(checkpoint_dir)

        assert store.load("session-a", "missing-checkpoint") is None


def test_checkpoint_store_list_for_session_is_stably_sorted():
    with temp_checkpoint_dir() as checkpoint_dir:
        store = CheckpointStore(checkpoint_dir)
        later = replace(
            make_checkpoint(),
            checkpoint_id="20260603-120001-bbbbbbbb",
            created_at="2026-06-03T12:00:01+00:00",
        )
        earlier = replace(
            make_checkpoint(),
            checkpoint_id="20260603-120000-aaaaaaaa",
            created_at="2026-06-03T12:00:00+00:00",
        )
        store.save(later)
        store.save(earlier)

        checkpoints = store.list_for_session("session-a")

    assert [checkpoint.checkpoint_id for checkpoint in checkpoints] == [
        "20260603-120000-aaaaaaaa",
        "20260603-120001-bbbbbbbb",
    ]


def test_checkpoint_store_latest_for_session_returns_latest_checkpoint():
    with temp_checkpoint_dir() as checkpoint_dir:
        store = CheckpointStore(checkpoint_dir)
        first = replace(
            make_checkpoint(),
            checkpoint_id="20260603-120000-aaaaaaaa",
            created_at="2026-06-03T12:00:00+00:00",
        )
        second = replace(
            make_checkpoint(),
            checkpoint_id="20260603-120001-bbbbbbbb",
            created_at="2026-06-03T12:00:01+00:00",
        )
        store.save(first)
        store.save(second)

        latest = store.latest_for_session("session-a")

    assert latest == second


def test_build_context_snapshot_does_not_store_full_long_context():
    context = ContextStub(text="x" * 700, metadata={"budget": {"total_truncated": False}})

    snapshot = build_context_snapshot(context)

    assert snapshot["has_text"] is True
    assert snapshot["char_count"] == 700
    assert len(snapshot["text_preview"]) == 500
    assert snapshot["text_truncated"] is True
    assert snapshot["metadata"] == {"budget": {"total_truncated": False}}


def test_build_tool_call_snapshot_does_not_modify_original_tool_calls():
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "run_command",
                "arguments": "{\"command\": \"pytest\", \"api_key\": \"secret\"}",
            },
        }
    ]
    before = copy.deepcopy(tool_calls)

    snapshot = build_tool_call_snapshot(tool_calls)

    assert tool_calls == before
    assert snapshot == [
        {
            "tool_call_id": "call_1",
            "name": "run_command",
            "arguments_preview": "{\"api_key\": \"[REDACTED]\", \"command\": \"pytest\"}",
            "arguments_truncated": False,
        }
    ]


def test_build_file_change_snapshot_with_missing_project_root_is_unavailable():
    snapshot = build_file_change_snapshot(None)

    assert snapshot["available"] is False
    assert snapshot["reason"] == "project_root_not_provided"
    assert snapshot["status_short"] == []
    assert snapshot["diff_names"] == []
    assert snapshot["cached_diff_names"] == []


def test_restore_conversation_from_checkpoint_restores_messages_and_recovery_summary():
    checkpoint = make_checkpoint()

    conversation = restore_conversation_from_checkpoint(checkpoint)

    assert conversation.as_messages() == checkpoint.messages
    assert conversation.recovery_summary == checkpoint.recovery_summary
