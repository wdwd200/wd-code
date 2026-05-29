import argparse
import json
import os
import sys
from pathlib import Path

from agent_loop import run_agent_loop
from llm_client import LLMClient


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
    client = LLMClient(
        base_url=config["base_url"],
        api_key=config["api_key"],
        model=config["model"],
    )
    run_agent_loop(client)


if __name__ == "__main__":
    main()
