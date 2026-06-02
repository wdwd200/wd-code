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
