import copy

import pytest

from wdcode.session.recovery import build_recovery_summary, split_messages_for_recovery


def make_messages(count):
    messages = [{"role": "system", "content": "system prompt"}]
    for index in range(1, count):
        if index % 3 == 1:
            messages.append({"role": "user", "content": f"user request {index}"})
        elif index % 3 == 2:
            messages.append({"role": "assistant", "content": f"assistant progress {index}"})
        else:
            messages.append(
                {
                    "role": "tool",
                    "name": "read_file",
                    "content": f"tool result {index}",
                    "tool_call_id": f"call_{index}",
                }
            )
    return messages


def test_build_recovery_summary_returns_none_when_messages_are_recent_only():
    messages = make_messages(4)

    summary = build_recovery_summary(messages, keep_recent_messages=4)

    assert summary is None


def test_build_recovery_summary_returns_rule_based_summary_for_old_messages():
    messages = make_messages(8)

    summary = build_recovery_summary(messages, keep_recent_messages=3)

    assert summary is not None
    assert summary.summary.startswith("# Recovery Summary")
    assert "Earlier conversation contained 5 messages." in summary.summary
    assert "Recent messages kept outside this summary: 3." in summary.summary
    assert "## User requests" in summary.summary
    assert "user request 1" in summary.summary
    assert "## Assistant/tool progress" in summary.summary
    assert "assistant progress 2" in summary.summary
    assert "## Tool results" in summary.summary
    assert "read_file: tool result 3" in summary.summary
    assert summary.source_message_count == 5
    assert summary.recent_message_count == 3
    assert summary.metadata == {"generated_by": "rule_based", "truncated": False}


def test_split_messages_for_recovery_returns_old_and_recent_copies():
    messages = make_messages(6)

    old_messages, recent_messages = split_messages_for_recovery(messages, keep_recent_messages=2)
    recent_messages[0]["content"] = "mutated"

    assert [message["content"] for message in old_messages] == [
        "system prompt",
        "user request 1",
        "assistant progress 2",
        "tool result 3",
    ]
    assert [message["content"] for message in messages[-2:]] == [
        "user request 4",
        "assistant progress 5",
    ]


def test_build_recovery_summary_truncates_with_marker():
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "long request " * 100},
        {"role": "assistant", "content": "recent answer"},
    ]

    summary = build_recovery_summary(
        messages,
        max_summary_chars=120,
        keep_recent_messages=1,
    )

    assert summary is not None
    assert summary.metadata["truncated"] is True
    assert summary.summary.endswith("[TRUNCATED: recovery_summary]")
    assert len(summary.summary) <= 120


def test_build_recovery_summary_rejects_invalid_max_summary_chars():
    with pytest.raises(ValueError, match="max_summary_chars"):
        build_recovery_summary(make_messages(3), max_summary_chars=0)


def test_build_recovery_summary_rejects_invalid_keep_recent_messages():
    with pytest.raises(ValueError, match="keep_recent_messages"):
        build_recovery_summary(make_messages(3), keep_recent_messages=0)


def test_split_messages_for_recovery_rejects_invalid_keep_recent_messages():
    with pytest.raises(ValueError, match="keep_recent_messages"):
        split_messages_for_recovery(make_messages(3), keep_recent_messages=0)


def test_build_recovery_summary_does_not_modify_original_messages():
    messages = make_messages(6)
    before = copy.deepcopy(messages)

    build_recovery_summary(messages, keep_recent_messages=2)

    assert messages == before
