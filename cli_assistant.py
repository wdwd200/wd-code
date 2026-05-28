import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CONFIG_PATH = Path(__file__).with_name("model_config.json")


def load_config(path):
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Failed to read config {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise SystemExit(f"Config {path} must be a JSON object.")
    return data


def save_config(path, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


def first_value(*values):
    for value in values:
        if value:
            return value
    return None


def normalize_base_url(base_url):
    return base_url.rstrip("/")


def build_runtime_config(args):
    config_path = Path(args.config).expanduser()
    saved_config = load_config(config_path)

    base_url = first_value(args.base_url, os.getenv("OPENAI_BASE_URL"), saved_config.get("base_url"), DEFAULT_BASE_URL)
    api_key = first_value(args.api_key, os.getenv("OPENAI_API_KEY"), saved_config.get("api_key"))
    model = first_value(args.model, os.getenv("OPENAI_MODEL"), saved_config.get("model"))

    runtime = {
        "base_url": normalize_base_url(base_url),
        "api_key": api_key,
        "model": model,
    }

    missing = [key for key, value in runtime.items() if not value]
    if missing:
        raise SystemExit(
            "Missing required config: "
            + ", ".join(missing)
            + ". Edit model_config.json, pass command line flags, or set OPENAI_* env vars."
        )

    if args.save_config:
        save_config(config_path, runtime)
        print(f"Saved config to {config_path}")

    return runtime


def request_chat_completion(config, messages):
    url = f"{config['base_url']}/chat/completions"
    payload = json.dumps(
        {
            "model": config["model"],
            "messages": messages,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed: {exc.reason}") from exc

    try:
        data = json.loads(response_body)
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unexpected response: {response_body}") from exc


def run_repl(config):
    messages = [
        {
            "role": "system",
            "content": "You are a concise CLI programming assistant.",
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
            assistant_reply = request_chat_completion(config, messages)
        except RuntimeError as exc:
            messages.pop()
            print(f"Error: {exc}", file=sys.stderr)
            continue

        messages.append({"role": "assistant", "content": assistant_reply})
        print(f"\nAssistant> {assistant_reply}")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Minimal OpenAI-compatible CLI assistant demo.")
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL, for example https://api.openai.com/v1")
    parser.add_argument("--api-key", help="API key for the model provider")
    parser.add_argument("--model", help="Model name")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help=f"Config file path. Default: {DEFAULT_CONFIG_PATH}")
    parser.add_argument("--save-config", action="store_true", help="Save resolved base_url, api_key, and model to config")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    config = build_runtime_config(args)
    run_repl(config)


if __name__ == "__main__":
    main()
