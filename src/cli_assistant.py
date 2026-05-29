import argparse
import sys
from pathlib import Path

from agent_loop import run_agent_loop
from config import DEFAULT_CONFIG_PATH, build_runtime_config
from llm_client import LLMClient
from tools import create_default_registry

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
    tool_registry = create_default_registry(PROJECT_ROOT)
    run_agent_loop(client, tool_registry=tool_registry)


if __name__ == "__main__":
    main()
