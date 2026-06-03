from wdcode.context.provider import ContextBundle
from wdcode.core.conversation import Conversation
from wdcode.core.message_builder import build_model_messages


def test_message_builder_preserves_conversation_messages_with_empty_context():
    conversation = Conversation()
    conversation.add_user_message("hello")

    messages = build_model_messages(
        conversation=conversation,
        context=ContextBundle(),
    )

    assert messages == conversation.as_messages()


def test_message_builder_does_not_mutate_conversation_messages():
    conversation = Conversation()
    conversation.add_user_message("hello")
    before = conversation.as_messages()

    build_model_messages(
        conversation=conversation,
        context=ContextBundle(text="placeholder context"),
    )

    assert conversation.as_messages() == before


def test_message_builder_inserts_non_empty_context_after_system_prompt():
    conversation = Conversation()
    conversation.add_user_message("hello")

    messages = build_model_messages(
        conversation=conversation,
        context=ContextBundle(text="# Project Context"),
    )

    assert messages == [
        conversation.as_messages()[0],
        {"role": "system", "content": "# Project Context"},
        conversation.as_messages()[1],
    ]
    assert conversation.as_messages() == [
        conversation.as_messages()[0],
        {"role": "user", "content": "hello"},
    ]


def test_message_builder_inserts_recovery_summary_after_system_prompt():
    conversation = Conversation(
        recovery_summary={
            "summary": "# Recovery Summary\n\nEarlier request: build session support.",
            "source_message_count": 20,
            "recent_message_count": 4,
            "metadata": {"generated_by": "rule_based"},
        }
    )
    conversation.add_user_message("continue")

    messages = build_model_messages(
        conversation=conversation,
        context=ContextBundle(),
    )

    assert messages == [
        conversation.as_messages()[0],
        {
            "role": "system",
            "content": (
                "# Session Recovery Summary\n\n"
                "# Recovery Summary\n\nEarlier request: build session support."
            ),
        },
        conversation.as_messages()[1],
    ]
    assert conversation.as_messages() == [
        conversation.as_messages()[0],
        {"role": "user", "content": "continue"},
    ]


def test_message_builder_orders_recovery_summary_before_context():
    conversation = Conversation(recovery_summary={"summary": "# Recovery Summary\n\nOld work"})
    conversation.add_user_message("continue")

    messages = build_model_messages(
        conversation=conversation,
        context=ContextBundle(text="# Project Context"),
    )

    assert messages == [
        conversation.as_messages()[0],
        {
            "role": "system",
            "content": "# Session Recovery Summary\n\n# Recovery Summary\n\nOld work",
        },
        {"role": "system", "content": "# Project Context"},
        conversation.as_messages()[1],
    ]


def test_message_builder_inserts_compression_summary_after_recovery_summary():
    conversation = Conversation(
        recovery_summary={"summary": "# Recovery Summary\n\nOld work"},
        compression_summary={
            "summary": "# Compressed Conversation History\n\nCompressed old history",
            "kept_recent_message_count": 2,
        },
    )
    conversation.add_user_message("old request")
    conversation.add_assistant_message("old answer")
    conversation.add_user_message("recent request")

    messages = build_model_messages(
        conversation=conversation,
        context=ContextBundle(text="# Project Context"),
    )

    assert messages == [
        conversation.as_messages()[0],
        {
            "role": "system",
            "content": "# Session Recovery Summary\n\n# Recovery Summary\n\nOld work",
        },
        {
            "role": "system",
            "content": "# Compressed Conversation History\n\nCompressed old history",
        },
        {"role": "system", "content": "# Project Context"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "recent request"},
    ]


def test_message_builder_compression_summary_keeps_only_recent_messages():
    conversation = Conversation(
        compression_summary={
            "summary": "# Compressed Conversation History\n\nCompressed old history",
            "kept_recent_message_count": 3,
        },
    )
    for index in range(5):
        conversation.add_user_message(f"request {index}")

    messages = build_model_messages(conversation=conversation, context=ContextBundle())

    assert messages == [
        conversation.as_messages()[0],
        {
            "role": "system",
            "content": "# Compressed Conversation History\n\nCompressed old history",
        },
        {"role": "user", "content": "request 2"},
        {"role": "user", "content": "request 3"},
        {"role": "user", "content": "request 4"},
    ]
    assert conversation.as_messages() == [
        conversation.as_messages()[0],
        {"role": "user", "content": "request 0"},
        {"role": "user", "content": "request 1"},
        {"role": "user", "content": "request 2"},
        {"role": "user", "content": "request 3"},
        {"role": "user", "content": "request 4"},
    ]
