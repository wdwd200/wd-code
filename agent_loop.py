import sys


SYSTEM_PROMPT = "You are a concise CLI programming assistant."


def run_agent_loop(client):
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ]

    print("Mini CLI Assistant. Type /exit or /quit to stop.")
    while True:
        try:
            user_input = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return

        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            print("Bye.")
            return

        messages.append({"role": "user", "content": user_input})

        try:
            assistant_reply = client.chat(messages)
        except RuntimeError as exc:
            messages.pop()
            print(f"Error: {exc}", file=sys.stderr)
            continue

        messages.append({"role": "assistant", "content": assistant_reply})
        print(f"\nAssistant> {assistant_reply}")
