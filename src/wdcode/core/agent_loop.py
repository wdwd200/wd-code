import sys

from wdcode.cli.commands import is_exit_command
from wdcode.core.conversation import Conversation
from wdcode.core.tool_loop import run_tool_loop


def run_agent_loop(client, tool_registry=None):
    conversation = Conversation()

    print("Mini CLI Assistant. Type"
          " /exit or /quit to stop.")
    while True:
        try:
            user_input = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return

        if not user_input:
            continue
        if is_exit_command(user_input):
            print("Bye.")
            return

        checkpoint = conversation.checkpoint()
        conversation.add_user_message(user_input)

        try:
            assistant_reply = run_tool_loop(
                client=client,
                conversation=conversation,
                tool_registry=tool_registry,
            )
        except RuntimeError as exc:
            conversation.rollback(checkpoint)
            print(f"Error: {exc}", file=sys.stderr)
            continue

        print(f"\nAssistant> {assistant_reply}")
