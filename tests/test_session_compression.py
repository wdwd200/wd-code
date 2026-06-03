import copy
import json

import pytest

from wdcode.session.compression import (
    TRUNCATION_MARKER,
    CompressionPolicy,
    ConversationCompression,
    build_conversation_compression,
    conversation_compression_from_dict,
    conversation_compression_to_dict,
    extract_key_files_from_messages,
    extract_key_tool_results,
    split_messages_for_compression,
)


def make_messages(count=8):
    messages = [{"role": "system", "content": "system"}]
    for index in range(count):
        messages.append(
            {
                "role": "user",
                "content": f"request {index} touching src/wdcode/core/agent_loop.py",
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": f"progress {index} in tests/test_session_compression.py",
            }
        )
    return messages


def test_build_conversation_compression_returns_none_below_trigger():
    messages = make_messages(count=2)

    compression = build_conversation_compression(
        messages,
        policy=CompressionPolicy(trigger_message_count=10, keep_recent_messages=4),
    )

    assert compression is None


def test_build_conversation_compression_returns_summary_above_trigger():
    messages = make_messages(count=4)

    compression = build_conversation_compression(
        messages,
        recovery_summary={"summary": "old recovery"},
        policy=CompressionPolicy(trigger_message_count=4, keep_recent_messages=3),
    )

    assert compression is not None
    assert compression.summary.startswith("# Compressed Conversation History")
    assert "Earlier user requests" in compression.summary
    assert "Assistant progress" in compression.summary
    assert "Key tool results" in compression.summary
    assert "Key files" in compression.summary
    assert "Based partly on existing recovery summary" in compression.summary
    assert compression.source_message_count == len(messages)
    assert compression.kept_recent_message_count == 3
    assert compression.compressed_message_count == len(messages) - 3
    assert compression.source_range == {"start_index": 0, "end_index": len(messages) - 4}
    assert compression.metadata["method"] == "deterministic-rule-based"


def test_split_messages_for_compression_returns_old_and_recent_without_mutation():
    messages = make_messages(count=3)
    before = copy.deepcopy(messages)

    old_messages, recent_messages = split_messages_for_compression(
        messages,
        keep_recent_messages=4,
    )
    old_messages[0]["content"] = "changed"
    recent_messages[0]["content"] = "changed"

    assert len(old_messages) == len(messages) - 4
    assert len(recent_messages) == 4
    assert messages == before


def test_split_messages_for_compression_rejects_invalid_keep_recent():
    with pytest.raises(ValueError, match="keep_recent_messages"):
        split_messages_for_compression(make_messages(), keep_recent_messages=0)


def test_build_conversation_compression_truncates_long_summary():
    messages = make_messages(count=20)

    compression = build_conversation_compression(
        messages,
        policy=CompressionPolicy(
            trigger_message_count=4,
            keep_recent_messages=2,
            max_summary_chars=220,
        ),
    )

    assert compression is not None
    assert TRUNCATION_MARKER in compression.summary
    assert compression.metadata["truncated"] is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trigger_message_count": 0},
        {"keep_recent_messages": 0},
        {"max_summary_chars": 0},
        {"max_tool_result_chars": 0},
        {"max_key_files": 0},
    ],
)
def test_compression_policy_rejects_non_positive_values(kwargs):
    with pytest.raises(ValueError):
        CompressionPolicy(**kwargs)


def test_extract_key_files_from_messages_finds_and_deduplicates_paths_in_order():
    messages = [
        {
            "role": "user",
            "content": (
                "Please update src/wdcode/core/agent_loop.py and "
                "tests/test_session_compression.py."
            ),
        },
        {
            "role": "assistant",
            "content": "Already mentioned src/wdcode/core/agent_loop.py.",
            "tool_calls": [
                {
                    "function": {
                        "arguments": json.dumps(
                            {
                                "path": "docs/PROJECT_STATE.md",
                                "api_key": "do-not-keep",
                            }
                        )
                    }
                }
            ],
        },
    ]

    assert extract_key_files_from_messages(messages) == [
        "src/wdcode/core/agent_loop.py",
        "tests/test_session_compression.py",
        "docs/PROJECT_STATE.md",
    ]


def test_extract_key_files_rejects_invalid_max_files():
    with pytest.raises(ValueError, match="max_files"):
        extract_key_files_from_messages(make_messages(), max_files=0)


def test_extract_key_tool_results_keeps_preview_not_full_output():
    long_output = "x" * 1200
    messages = [
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "run_command",
            "content": json.dumps(
                {
                    "ok": False,
                    "data": {"stdout": long_output},
                    "error": "failed",
                    "metadata": {"tool_name": "run_command"},
                }
            ),
        }
    ]

    results = extract_key_tool_results(messages, max_result_chars=200)

    assert results == [
        {
            "tool_call_id": "call_1",
            "name": "run_command",
            "content_preview": results[0]["content_preview"],
            "truncated": True,
        }
    ]
    assert len(results[0]["content_preview"]) <= 200
    assert long_output not in results[0]["content_preview"]


def test_conversation_compression_to_dict_is_json_serializable():
    compression = ConversationCompression(
        summary="# Compressed Conversation History\n\nsummary",
        source_message_count=8,
        kept_recent_message_count=2,
        compressed_message_count=6,
        key_files=["src/wdcode/session/compression.py"],
        key_tool_results=[{"tool_call_id": "call_1", "content_preview": "ok"}],
        source_range={"start_index": 0, "end_index": 5},
        metadata={"method": "deterministic-rule-based", "token": "secret"},
    )

    payload = conversation_compression_to_dict(compression)
    restored = conversation_compression_from_dict(payload)

    json.dumps(payload)
    assert payload["metadata"]["token"] == "[REDACTED]"
    assert restored is not None
    assert restored.summary == compression.summary
    assert restored.key_files == compression.key_files


def test_build_conversation_compression_does_not_mutate_messages():
    messages = make_messages(count=5)
    before = copy.deepcopy(messages)

    build_conversation_compression(
        messages,
        policy=CompressionPolicy(trigger_message_count=4, keep_recent_messages=3),
    )

    assert messages == before
